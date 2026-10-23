"""Environment-variable settings for the investigator service.

Follows the same conventions as
services/control-plane/src/control_plane/core/config.py: every
setting is read from an individual environment variable (never a
pre-built connection string or a hardcoded credential), and an
unconfigured LLM provider does NOT crash the process at startup — the
non-blocking-startup philosophy every other service in this repository
already follows. GET /health/ready reports provider configuration
honestly; POST /api/v1/investigations fails explicitly (never with a
silently fabricated response) when the provider is unavailable.

This service holds no PostgreSQL credentials and no control-plane
write-capable Bearer token (CONTROL_PLANE_WEBHOOK_TOKEN /
CONTROL_PLANE_LIFECYCLE_TOKEN) — it only ever makes unauthenticated GET
requests to control-plane's existing read-only API.
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("investigator_service.config")


@dataclass(frozen=True)
class OrganizationContextSettings:
    """Phase 14 correction round, Issue 3: mirrors
    control_plane.core.config.OrganizationContextSettings exactly --
    the SAME shared environment variable
    (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT) as control-plane and
    agent-runtime-service, so this platform's secure mode is ONE
    global toggle, never independently enabled per service (Issue 3's
    own warning: "Ensure internal authorization does not silently
    disable the human tenant checks")."""

    enabled: bool

    @classmethod
    def from_env(cls) -> "OrganizationContextSettings":
        raw = os.environ.get("CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "false")
        return cls(enabled=raw.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class InternalServiceTokenSettings:
    """Phase 14 correction round, Issue 3: closes the "direct HTTP
    call bypasses the frontend" gap this service's own exposed port
    (127.0.0.1:8001) otherwise leaves open once secure mode is on --
    see docs/architecture/phase-14-security-multitenancy.md.

    `agent_runtime_caller_token` is what THIS service CHECKS incoming
    POST /api/v1/investigations requests against (only
    agent-runtime-service is configured with the matching value) --
    never a human-actor credential; this service has no browser-facing
    API and never will. `control_plane_token`/`retrieval_token` are
    this service's OWN distinct internal-read identities, presented to
    control-plane and retrieval-service respectively (never reused
    for one another, and never the same value as
    `agent_runtime_caller_token` -- see main.py's own startup
    validation).

    Why no per-request human-organization re-verification is layered
    on top of this (Issue 3: "organization/resource binding where
    necessary", judged not necessary here): the tenant-authorization
    decision for "may this actor investigate this incident" is already
    made, independently, at agent-runtime-service's own
    create_agent_run/resume_agent_run API boundary (see
    agent_runtime_service/api/agent_runs.py and its own real
    cross-tenant tests) BEFORE it ever calls this endpoint -- this
    service is reachable ONLY via that already-authorized internal
    call once this token is required, never directly by a browser.
    """

    agent_runtime_caller_token: str | None
    control_plane_token: str
    retrieval_token: str

    @classmethod
    def from_env(cls) -> "InternalServiceTokenSettings":
        raw_caller = os.environ.get("INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME", "")
        return cls(
            agent_runtime_caller_token=raw_caller if raw_caller.strip() else None,
            control_plane_token=os.environ.get("CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR", ""),
            retrieval_token=os.environ.get("RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR", ""),
        )


@dataclass(frozen=True)
class ServiceAssertionSettings:
    """Phase 14 correction round, Blocker 1: verifies a signed service
    assertion agent-runtime-service RELAYS alongside its own existing
    `agent_runtime_caller_token` (that token is UNCHANGED and still
    independently required by `require_internal_caller` -- this is
    additive, never a replacement). Carries the real human actor
    agent-runtime-service's own API boundary already verified, so THIS
    service can, in turn, mint a FURTHER-derived assertion
    (`iss="investigator-service"`) when it reads incident evidence
    from control-plane -- control-plane's own incident/evidence routes
    no longer accept a bare internal token at all (see
    control_plane.core.authz's own Blocker-1 fix).

    Same shared HS256 secret as every other service
    (SERVICE_ASSERTION_SIGNING_SECRET); `trusted_issuers` here is
    narrower than control-plane's own -- only agent-runtime-service
    ever calls this service, never web-console directly -- and
    `audience` is this service's OWN identity
    (SERVICE_ASSERTION_AUDIENCE, default "investigator-service"),
    distinct from control-plane's or agent-runtime-service's audience
    values (an assertion minted for one backend must not be replayable
    against another)."""

    secret: str | None
    trusted_issuers: frozenset[str]
    audience: str
    max_clock_skew_seconds: float
    # The audience THIS service uses when IT relays a further-derived
    # assertion onward to control-plane -- mirrors
    # agent_runtime_service.config.ServiceAssertionSettings's own
    # `control_plane_audience` field/env-var name exactly.
    control_plane_audience: str
    # Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A: the
    # audience THIS service uses when it relays a derived assertion to
    # retrieval-service, carrying the real actor on whose behalf it is
    # searching -- retrieval-service's own `_resolve_historical_organization_scope`
    # requires this to authorize a tenant-scoped historical search at
    # all (a bare internal token is no longer sufficient by itself).
    retrieval_audience: str

    @classmethod
    def from_env(cls) -> "ServiceAssertionSettings":
        raw = os.environ.get("SERVICE_ASSERTION_SIGNING_SECRET", "")
        raw_issuers = os.environ.get("SERVICE_ASSERTION_TRUSTED_ISSUERS", "agent-runtime-service")
        return cls(
            secret=raw if raw.strip() else None,
            trusted_issuers=frozenset(i.strip() for i in raw_issuers.split(",") if i.strip()),
            audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE", "investigator-service"),
            max_clock_skew_seconds=_float_env("SERVICE_ASSERTION_MAX_CLOCK_SKEW_SECONDS", 30.0),
            control_plane_audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_CONTROL_PLANE", "control-plane"),
            retrieval_audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_RETRIEVAL", "retrieval-service"),
        )


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _clamped_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Phase 5 correction round: an environment variable must never be
    able to silently disable a practical evidence bound (e.g. setting
    INVESTIGATOR_MAX_LOKI_LINES to 0 or to 10 million). Out-of-range
    values are clamped to [minimum, maximum] and logged, never crash
    the process and never silently accepted."""
    value = _int_env(name, default)
    if value < minimum:
        logger.warning("%s=%s is below the minimum %s; clamping to %s", name, value, minimum, minimum)
        return minimum
    if value > maximum:
        logger.warning("%s=%s exceeds the maximum %s; clamping to %s", name, value, maximum, maximum)
        return maximum
    return value


@dataclass(frozen=True)
class TelemetrySettings:
    """Base URLs for the three read-only observability sources this
    service queries. Each already defaults to this stack's own
    internal Compose DNS name (see docker-compose.yml) — overridable
    for local, non-Compose development only.
    """

    control_plane_url: str
    prometheus_url: str
    loki_url: str
    tempo_url: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "TelemetrySettings":
        return cls(
            control_plane_url=os.environ.get("INVESTIGATOR_CONTROL_PLANE_URL", "http://control-plane:8000"),
            prometheus_url=os.environ.get("INVESTIGATOR_PROMETHEUS_URL", "http://prometheus:9090"),
            loki_url=os.environ.get("INVESTIGATOR_LOKI_URL", "http://loki:3100"),
            tempo_url=os.environ.get("INVESTIGATOR_TEMPO_URL", "http://tempo:3200"),
            connect_timeout_seconds=_float_env("INVESTIGATOR_CONNECT_TIMEOUT_SECONDS", 5.0),
            request_timeout_seconds=_float_env("INVESTIGATOR_REQUEST_TIMEOUT_SECONDS", 10.0),
        )


@dataclass(frozen=True)
class RetrievalSettings:
    """Phase 6 §11: the read-only RAG retrieval client. `url` is a
    plain HTTP URL to retrieval-service's search-only API -- the same
    trust boundary as Prometheus/Loki/Tempo's URLs above, never a
    PostgreSQL credential (this service still holds none). A blank
    `url` disables retrieval entirely (same non-blocking-startup
    philosophy as LLMSettings): the investigation still proceeds using
    Phase 5 evidence alone, with retrieval_context.outcome reported as
    "unavailable" (Phase 6 §16)."""

    url: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "RetrievalSettings":
        return cls(
            url=os.environ.get("INVESTIGATOR_RETRIEVAL_URL", "").strip(),
            connect_timeout_seconds=_float_env("INVESTIGATOR_RETRIEVAL_CONNECT_TIMEOUT_SECONDS", 3.0),
            request_timeout_seconds=_float_env("INVESTIGATOR_RETRIEVAL_REQUEST_TIMEOUT_SECONDS", 8.0),
        )


@dataclass(frozen=True)
class LLMSettings:
    """The one real, configurable LLM provider (Phase 5 §6): OpenAI's
    Chat Completions API, selected via INVESTIGATOR_LLM_API_KEY being
    present — never hardcoded, never defaulted to a real value.

    Deliberately NOT required at startup (same non-blocking philosophy
    as WebhookSettings/LifecycleSettings in control-plane): an absent
    key means this service still starts and still serves incident
    evidence collection, but `configured` is False, `/health/ready`
    reports that honestly, and POST /api/v1/investigations returns an
    explicit "provider not configured" response rather than a fake
    investigation.

    `base_url` defaults to OpenAI's own API and is only overridden for
    an OpenAI-compatible self-hosted/proxy endpoint — never used to
    let anything outside this allowlisted configuration point at an
    arbitrary network location (the LLM itself never supplies a URL,
    only this environment variable does, read once at startup).

    `provider`: "openai" (default) uses the real provider above,
    gated on `api_key` being present. "stub" forces the deterministic,
    offline StubProvider regardless of any configured key — used ONLY
    by scripts/verify-investigator.sh (via INVESTIGATOR_LLM_PROVIDER=stub)
    to exercise this service's real HTTP/evidence pipeline end-to-end in
    CI without ever needing a real, paid API key. Never the default;
    a deployment that never sets INVESTIGATOR_LLM_PROVIDER always uses
    the real provider path.
    """

    provider: Literal["openai", "stub"]
    api_key: str | None
    model: str
    base_url: str | None
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        if self.provider == "stub":
            return True
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "LLMSettings":
        raw_key = os.environ.get("INVESTIGATOR_LLM_API_KEY", "")
        base_url = os.environ.get("INVESTIGATOR_LLM_BASE_URL", "").strip() or None
        provider = os.environ.get("INVESTIGATOR_LLM_PROVIDER", "openai").strip().lower()
        if provider not in ("openai", "stub"):
            provider = "openai"
        return cls(
            provider=provider,  # type: ignore[arg-type]
            api_key=raw_key if raw_key.strip() else None,
            model=os.environ.get("INVESTIGATOR_LLM_MODEL", "gpt-4o-mini"),
            base_url=base_url,
            timeout_seconds=_float_env("INVESTIGATOR_LLM_TIMEOUT_SECONDS", 30.0),
        )


@dataclass(frozen=True)
class EvidenceBounds:
    """Hard caps on evidence collection — Phase 5 §5's "bound
    everything" requirement. Every one of these is read from an
    environment variable but CLAMPED to a sane [minimum, maximum]
    range (see `_clamped_int_env`) — none of them can be set to a
    value that would defeat the point of having a bound at all.

    `max_audit_events` bounds RETRIEVAL (how many real audit events
    this service will ever fetch for one incident) — see
    evidence_collector.py for how a retrieval that hits this cap is
    reported as "partial", never silently presented as the complete
    history. `max_prompt_evidence_items`/`max_prompt_chars` instead
    bound what is actually shown to the model (llm/prompt.py) —
    independent of how much was collected, deliberately reserving one
    representative item per available telemetry source (Prometheus,
    Loki, Tempo) before any additional telemetry or audit history, and
    deliberately reserving room for that telemetry even when the audit
    history alone would otherwise fill the whole budget.

    `max_prompt_chars` (Phase 5 correction round #2, issue 2) bounds
    ONLY the rendered USER prompt returned by `build_prompts` — never
    the fixed, non-data-dependent SYSTEM_PROMPT constant, which
    contains no evidence content and so cannot be a vector for an
    oversized prompt. This is a REAL hard bound, enforced on every
    code path: if even the mandatory minimum content (the incident
    identity item plus fixed scaffolding) cannot fit, `build_prompts`
    raises `llm.prompt.PromptTooLargeError` rather than ever returning
    a user prompt longer than this value.
    """

    max_audit_events: int
    max_prometheus_series: int
    max_loki_lines: int
    max_loki_line_length: int
    max_tempo_traces: int
    max_incident_text_length: int
    evidence_window_before_seconds: int
    evidence_window_after_seconds: int
    max_prompt_evidence_items: int
    max_prompt_chars: int

    @classmethod
    def from_env(cls) -> "EvidenceBounds":
        return cls(
            max_audit_events=_clamped_int_env("INVESTIGATOR_MAX_AUDIT_EVENTS", 200, 1, 2000),
            max_prometheus_series=_clamped_int_env("INVESTIGATOR_MAX_PROMETHEUS_SERIES", 10, 5, 500),
            max_loki_lines=_clamped_int_env("INVESTIGATOR_MAX_LOKI_LINES", 20, 1, 500),
            max_loki_line_length=_clamped_int_env("INVESTIGATOR_MAX_LOKI_LINE_LENGTH", 500, 50, 5000),
            max_tempo_traces=_clamped_int_env("INVESTIGATOR_MAX_TEMPO_TRACES", 5, 1, 50),
            max_incident_text_length=_clamped_int_env("INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH", 2000, 100, 10000),
            evidence_window_before_seconds=_clamped_int_env("INVESTIGATOR_WINDOW_BEFORE_SECONDS", 900, 60, 86400),
            evidence_window_after_seconds=_clamped_int_env("INVESTIGATOR_WINDOW_AFTER_SECONDS", 900, 60, 86400),
            max_prompt_evidence_items=_clamped_int_env("INVESTIGATOR_MAX_PROMPT_EVIDENCE_ITEMS", 80, 5, 500),
            max_prompt_chars=_clamped_int_env("INVESTIGATOR_MAX_PROMPT_CHARS", 40_000, 2_000, 200_000),
        )


@dataclass(frozen=True)
class RagBounds:
    """Phase 6 §14: separate, practical bounds for retrieved context --
    deliberately independent of EvidenceBounds above, which governs
    current-incident evidence only. Retrieved context always competes
    for space INSIDE the existing `max_prompt_chars` hard ceiling
    (never a separate, additional ceiling that could let the overall
    prompt exceed it) and is always the lowest-priority material: see
    llm/prompt.py's `build_prompts`, which gives current-incident
    evidence first claim on the whole budget and only spends what's
    left on retrieved context, trimming retrieved context first (never
    evidence) if the two together would exceed the ceiling.

    `max_rag_context_chars` is a further, usually-tighter sub-budget
    within whatever room is left after evidence -- it exists so
    retrieved context has its own small, predictable footprint even
    when the overall prompt ceiling is generously sized.
    """

    max_knowledge_contexts: int
    max_historical_contexts: int
    max_context_excerpt_chars: int
    max_rag_context_chars: int

    @classmethod
    def from_env(cls) -> "RagBounds":
        return cls(
            max_knowledge_contexts=_clamped_int_env("INVESTIGATOR_MAX_KNOWLEDGE_CONTEXTS", 3, 0, 20),
            max_historical_contexts=_clamped_int_env("INVESTIGATOR_MAX_HISTORICAL_CONTEXTS", 3, 0, 20),
            max_context_excerpt_chars=_clamped_int_env("INVESTIGATOR_MAX_CONTEXT_EXCERPT_CHARS", 500, 50, 5000),
            max_rag_context_chars=_clamped_int_env("INVESTIGATOR_MAX_RAG_CONTEXT_CHARS", 6000, 0, 100_000),
        )
