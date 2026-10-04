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
