"""Database connection settings, read from individual environment
variables — never a single pre-built connection string. This matters:
a manually concatenated "postgresql://user:password@host/db" string
breaks if the password contains characters like "@", "/", or "#", and
credentials must never appear as a source-code constant. Each
component is read separately here and handed to SQLAlchemy's
URL.create() (see db/engine.py), which percent-encodes every component
correctly.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("control_plane.config")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_size: int
    pool_pre_ping: bool
    pool_timeout_seconds: float
    connect_timeout_seconds: float
    command_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            # "postgres" is this Compose project's internal DNS name
            # for the existing PostgreSQL service (see
            # docker-compose.yml); the internal port is always 5432
            # regardless of whatever host port POSTGRES_PORT maps to
            # for external access, so it is intentionally not reused
            # here.
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_INTERNAL_PORT", "5432")),
            user=_require_env("POSTGRES_USER"),
            password=_require_env("POSTGRES_PASSWORD"),
            database=_require_env("POSTGRES_DB"),
            pool_size=int(os.environ.get("CONTROL_PLANE_DB_POOL_SIZE", "5")),
            pool_pre_ping=True,
            pool_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_POOL_TIMEOUT_SECONDS", "5")),
            connect_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_CONNECT_TIMEOUT_SECONDS", "5")),
            command_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_COMMAND_TIMEOUT_SECONDS", "10")),
        )


@dataclass(frozen=True)
class WebhookSettings:
    """Phase 3C: the shared secret the Alertmanager -> control-plane
    webhook (api/webhook_auth.py) checks incoming Bearer tokens
    against. Deliberately NOT required at startup the way the database
    settings are: an unconfigured token must not crash this
    service's read-only API (see docs/api/control-plane.md) — instead
    it makes every webhook request fail closed (401), since
    `token` is None and no supplied value can ever equal it. The same
    value is generated and mirrored into
    observability/alertmanager/secrets/webhook-token by
    scripts/init-webhook-secret.sh.
    """

    token: str | None

    @classmethod
    def from_env(cls) -> "WebhookSettings":
        raw = os.environ.get("CONTROL_PLANE_WEBHOOK_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class LifecycleSettings:
    """Phase 3D: the shared secret the human/operator lifecycle
    endpoint (PATCH /api/v1/incidents/{id}/status, api/auth.py's
    require_lifecycle_token) checks incoming Bearer tokens against.

    Deliberately a SEPARATE environment variable and a SEPARATE
    app.state attribute from WebhookSettings above — never the same
    value. Alertmanager is only ever given the webhook token (see
    observability/alertmanager/secrets/webhook-token); it has no way to
    learn this one, so it cannot invoke the lifecycle endpoint, by
    construction, not merely by convention.

    Same non-blocking-startup philosophy as WebhookSettings: an
    unconfigured token must not crash this service — it just makes
    every lifecycle request fail closed (401), since `token` is None
    and no supplied value can ever equal it. Generated and kept in
    sync by the same scripts/init-webhook-secret.sh that handles the
    webhook token, but — unlike it — never mirrored into any file
    Alertmanager (or anything else) can read; it reaches this service
    purely as an environment variable.
    """

    token: str | None

    @classmethod
    def from_env(cls) -> "LifecycleSettings":
        raw = os.environ.get("CONTROL_PLANE_LIFECYCLE_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class RemediationTokenSettings:
    """Phase 8: three separate, never-interchangeable Bearer tokens for
    the remediation-proposal domain. Same non-blocking-startup
    philosophy as WebhookSettings/LifecycleSettings — an unconfigured
    token just makes its own endpoint fail closed (401), it never
    crashes this service.

    - `proposal_token` (CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN) — held
      ONLY by agent-runtime-service. Authorizes creating a proposal
      only; cannot approve/reject, cannot record an execution result,
      cannot touch the incident lifecycle endpoint.
    - `approver_token` (CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN) — held
      ONLY by a human/operator (or a CI acceptance script simulating
      one). Never given to agent-runtime-service, tool-gateway,
      investigator-service, or retrieval-service.
    - `executor_token` (CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN) — held
      ONLY by tool-gateway. Authorizes recording execution start/result
      only; cannot create or approve/reject a proposal.
    """

    proposal_token: str | None
    approver_token: str | None
    executor_token: str | None

    @classmethod
    def from_env(cls) -> "RemediationTokenSettings":
        def _opt(name: str) -> str | None:
            raw = os.environ.get(name, "")
            return raw if raw.strip() else None

        return cls(
            proposal_token=_opt("CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN"),
            approver_token=_opt("CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN"),
            executor_token=_opt("CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN"),
        )


@dataclass(frozen=True)
class KubernetesIngestionTokenSettings:
    """Phase 12B-D: the shared secret the Kubernetes finding-ingestion
    endpoint (POST /internal/v1/kubernetes/findings, api/auth.py's
    require_kubernetes_ingestion_token) checks incoming Bearer tokens
    against. Same non-blocking-startup philosophy as every other token
    here: an unconfigured token just makes that one endpoint fail
    closed (401). A SEPARATE credential from every one of the other
    five -- Alertmanager, agent-runtime-service, a human operator, and
    tool-gateway must never be able to present this one, by
    construction, and this one must never be able to present theirs."""

    token: str | None

    @classmethod
    def from_env(cls) -> "KubernetesIngestionTokenSettings":
        raw = os.environ.get("CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class AwsIngestionTokenSettings:
    """Phase 13: the shared secret the AWS finding-ingestion endpoint
    (POST /internal/v1/aws/findings, api/auth.py's
    require_aws_ingestion_token) checks incoming Bearer tokens against.
    Same non-blocking-startup philosophy as every other token here. A
    SEPARATE credential from every one of the other six -- Gate 4: "Do
    not reuse the Kubernetes ingestion token" -- by construction, not
    merely by convention."""

    token: str | None

    @classmethod
    def from_env(cls) -> "AwsIngestionTokenSettings":
        raw = os.environ.get("CONTROL_PLANE_AWS_INGESTION_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class OrganizationContextSettings:
    """Phase 14: the fail-closed activation switch for tenant-aware,
    actor-verified authorization on the incident GET endpoints and the
    remediation-decision endpoint.

    Defaults to `False` so every existing unauthenticated local-dev
    behavior (every CI script, every pre-Phase-14 test, every existing
    acceptance script) is completely unchanged by default -- this is
    additive, not a silent behavior change. When explicitly set to
    `true` (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true), those
    endpoints require a valid, signed service assertion (see
    core/authz.py) identifying the real actor's organization/role, and
    every incident read/mutation is scoped to that organization -- a
    request with no assertion, an invalid assertion, or an assertion
    for the wrong organization fails closed (401/403/404), it is never
    silently downgraded to the old unauthenticated behavior.

    This is deliberately a single global toggle, not per-route: Gate 5
    requires that trust boundary to be uniform and not something a
    caller can selectively avoid by hitting a GET route the toggle
    "forgot" to cover.
    """

    enabled: bool

    @classmethod
    def from_env(cls) -> "OrganizationContextSettings":
        raw = os.environ.get("CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "false")
        return cls(enabled=raw.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class LegacyIngestionSettings:
    """Phase 14 correction round, Issue 4: the explicit boundary
    between (a) legacy local/demo observations (Alertmanager/
    Kubernetes/AWS finding ingestion via a single shared static
    per-source token, unconditionally assigned to the fixed
    `LEGACY_LOCAL_DEVELOPMENT_ORGANIZATION_ID` -- Gate 6's real
    per-tenant ingestion association is explicitly NOT implemented)
    and (b) a genuinely secure, multi-tenant deployment.

    `allow_legacy_ingestion` defaults to `True` -- when
    `OrganizationContextSettings.enabled` is `False` (the pre-Phase-14
    local-dev/CI default), this setting is never even consulted;
    every ingestion endpoint behaves exactly as it always has. Once
    organization-context enforcement IS enabled, this flag becomes the
    explicit, operator-visible choice of whether to ALSO keep the
    legacy, non-tenant-aware ingestion pipeline running (the default,
    so existing CI/local-dev ingestion scripts keep working even in a
    secure-mode test run) or to disable it (`false`) -- a real secure
    deployment that does NOT want every Alertmanager/Kubernetes/AWS
    finding silently landing in one shared legacy organization should
    set this to `false` rather than assume multi-tenant ingestion
    exists merely because `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true`.
    Disabled ingestion fails closed (503), never silently accepted and
    discarded.
    """

    allow_legacy_ingestion: bool

    @classmethod
    def from_env(cls) -> "LegacyIngestionSettings":
        raw = os.environ.get("CONTROL_PLANE_ALLOW_LEGACY_INGESTION", "true")
        return cls(allow_legacy_ingestion=raw.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class ServiceAssertionSettings:
    """Phase 14: verification settings for the short-lived, signed
    service assertion the web-console BFF mints (per authenticated
    browser request, from a freshly re-checked Better Auth session +
    live organization-membership lookup -- never cached, never
    client-supplied) and this service verifies independently before
    trusting ANY of it (Gate 5: "Never treat an unsigned X-User-ID,
    X-Role, or X-Organization-ID header as trusted authorization").

    `secret` is a symmetric HS256 signing key, shared between
    web-console (the ORIGINAL signer, from a real browser session) and
    every service that verifies or RELAYS an assertion -- this
    service, agent-runtime-service, and investigator-service -- never
    exposed to a browser, never the same value as any of the Bearer
    tokens in this module.

    Phase 14 correction round, Blocker 1: `trusted_issuers` (plural)
    replaces a single fixed issuer string. web-console mints the
    FIRST assertion for a request (iss="web-console"); when
    agent-runtime-service or investigator-service needs to forward
    that same, already-verified human actor's identity to ANOTHER
    internal service (e.g. agent-runtime-service calling this
    service's own incident-evidence GETs, or investigator-service
    calling them on agent-runtime-service's behalf), it mints a
    DERIVED assertion carrying the IDENTICAL verified
    sub/org/role -- never re-deriving or trusting a client-supplied
    value -- signed with iss=<that relaying service's own name> so
    this service can tell, for audit purposes, whether an assertion
    came directly from a browser or was relayed by an internal
    service. Every value here is still cryptographically verified
    with the SAME shared secret regardless of which trusted issuer
    signed it -- a relaying service can mint a derived assertion only
    for the EXACT actor it itself already independently verified; it
    can never fabricate a different org/role (see
    core/authz.py::sign_derivative_assertion's own docstring and its
    mirrors in agent-runtime-service/investigator-service).

    `audience` remains a single, pinned value (this service always
    expects "control-plane", regardless of who signed the token) so a
    token minted for a different downstream service can never be
    replayed here. Same non-blocking-startup philosophy as every other
    secret in this module: an unconfigured secret does not crash this
    service -- every assertion simply fails to verify (treated as
    absent/invalid), which only matters once
    OrganizationContextSettings.enabled is True, at which point it
    makes the gated endpoints fail closed.
    """

    secret: str | None
    trusted_issuers: frozenset[str]
    audience: str
    max_clock_skew_seconds: float

    @classmethod
    def from_env(cls) -> "ServiceAssertionSettings":
        raw = os.environ.get("SERVICE_ASSERTION_SIGNING_SECRET", "")
        raw_issuers = os.environ.get(
            "SERVICE_ASSERTION_TRUSTED_ISSUERS", "web-console,agent-runtime-service,investigator-service"
        )
        return cls(
            secret=raw if raw.strip() else None,
            trusted_issuers=frozenset(i.strip() for i in raw_issuers.split(",") if i.strip()),
            audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE", "control-plane"),
            max_clock_skew_seconds=float(os.environ.get("SERVICE_ASSERTION_MAX_CLOCK_SKEW_SECONDS", "30")),
        )


# Phase 14: the fixed, documented UUID of the "legacy local-development
# organization" every pre-Phase-14 reliability.incidents row is
# backfilled to by V10__add_organization_scoping.sql. A real,
# well-known constant -- never "whichever user signs up first" and
# never a production fallback for an unrecognized tenant (Gate 4
# explicitly prohibits both). Deliberately defined here (not only in
# the SQL migration) so application code (this module, authz.py, and
# this service's tests) can refer to the SAME value the migration
# used, rather than re-deriving or guessing it.
LEGACY_LOCAL_DEVELOPMENT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class InternalServiceReadTokenSettings:
    """Phase 14 correction round, Issue 3: THREE SEPARATE, distinct
    trusted-service-identity credentials -- one per internal caller
    (agent-runtime-service, investigator-service, tool-gateway) --
    checked against a DEDICATED header (`X-Internal-Service-Token`,
    core/authz.py::INTERNAL_SERVICE_TOKEN_HEADER), never `Authorization`
    or `X-Service-Assertion`.

    Why this exists: once CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is
    enabled, every GET route this service exposes requires a verified
    actor (core/authz.py::get_actor_context) -- which correctly closes
    the "an unauthenticated direct HTTP call can read tenant-sensitive
    data" gap (Issue 2), but ALSO breaks every existing internal
    service's own read calls (agent-runtime-service's
    ControlPlaneClient.get_incident, investigator-service's own
    control-plane client, tool-gateway's GetProposal), none of which
    ever sent (or could meaningfully construct) a per-human-actor
    assertion. Each of these three tokens grants ONLY the bounded
    "read incidents/evidence/remediation-proposal state for already-
    authorized internal orchestration" capability
    (core/authz.py::get_actor_or_internal_reader) -- never the
    human-approval decision endpoint (api/remediation.py::decide_remediation_proposal
    continues to require get_actor_context, a REAL human actor,
    unconditionally -- Issue 3: "A machine credential must not
    impersonate an arbitrary human approver").

    Why no per-resource organization binding is enforced for these
    specific tokens (Issue 3: "organization/resource binding where
    necessary"): the authorization decision ("may this actor touch
    THIS incident") is already made, independently, at the single
    human-facing entry point BEFORE any of these three services ever
    makes an internal read call on that human's behalf (agent-runtime-
    service's own create_agent_run/resume_agent_run; investigator-
    service's own create_investigation, which independently re-derives
    and checks this exact binding using ITS OWN internal read token
    before trusting an evidence fetch -- see
    investigator_service/authz.py). Re-deriving it a second time at
    this layer would be redundant, not a closed gap.

    Same non-blocking-startup philosophy as every other token in this
    module: unconfigured just means every one of these three identities
    fails closed for this specific credential, nothing else.
    """

    agent_runtime_token: str | None
    investigator_token: str | None
    tool_gateway_token: str | None

    @classmethod
    def from_env(cls) -> "InternalServiceReadTokenSettings":
        def _opt(name: str) -> str | None:
            raw = os.environ.get(name, "")
            return raw if raw.strip() else None

        return cls(
            agent_runtime_token=_opt("CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME"),
            investigator_token=_opt("CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR"),
            tool_gateway_token=_opt("CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY"),
        )

    def configured_tokens(self) -> tuple[tuple[str, str], ...]:
        """(service_name, token) pairs for every CONFIGURED (non-None)
        token -- used by core/authz.py to check an incoming header
        against all three without caring which one matched, and by
        resolve_write_tokens's own anti-collision guard below."""
        pairs = (
            ("agent-runtime-service", self.agent_runtime_token),
            ("investigator-service", self.investigator_token),
            ("tool-gateway", self.tool_gateway_token),
        )
        return tuple((name, token) for name, token in pairs if token is not None)


def resolve_write_tokens(
    webhook_token: str | None,
    lifecycle_token: str | None,
    remediation_proposal_token: str | None = None,
    remediation_approver_token: str | None = None,
    remediation_executor_token: str | None = None,
    kubernetes_ingestion_token: str | None = None,
    aws_ingestion_token: str | None = None,
    agent_runtime_internal_read_token: str | None = None,
    investigator_internal_read_token: str | None = None,
    tool_gateway_internal_read_token: str | None = None,
) -> tuple[
    str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None
]:
    """Post-review correction: an application-level guard against any
    TWO of this service's write-endpoint tokens being configured
    identically.

    scripts/init-webhook-secret.sh / scripts/init-remediation-secrets.sh
    refuse to produce such a combination in the first place — but
    nothing stops an operator from hand-editing .env, or setting these
    environment variables directly in some other deployment mechanism,
    bypassing both scripts entirely. If that happens, the whole reason
    these are separate credentials — Alertmanager must never invoke the
    human/operator lifecycle endpoint; agent-runtime-service must never
    approve/reject or record an execution result; tool-gateway must
    never create or approve a proposal; a human approver's credential
    must never double as anything an automated service could present —
    is silently defeated: a single leaked/observed token would then
    authorize more than one write path. This function is called once,
    at startup (main.py's lifespan), after every token is independently
    read from the environment, and is deliberately a plain function
    (not reaching into app.state itself) so it is directly unit-testable
    without constructing the whole FastAPI app.

    For every PAIR of the six tokens that are both configured
    (non-None) and equal, BOTH members of that pair are returned as
    None — i.e. every endpoint either of them would authorize fails
    closed, exactly as if neither token had ever been configured —
    rather than letting either authorize the other's endpoint(s). This
    does not crash the process (consistent with the non-blocking-startup
    philosophy every other setting in this module already follows): a
    misconfigured secret must not take down the read-only API. Every
    misconfiguration is logged as an error server-side by NAME only;
    no token value is ever logged.

    A token being unconfigured (None) is unaffected by this check for
    any pair it is not part of, and continues to fail closed only for
    its own endpoint(s), same as before this function existed.
    """
    names = (
        "CONTROL_PLANE_WEBHOOK_TOKEN",
        "CONTROL_PLANE_LIFECYCLE_TOKEN",
        "CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN",
        "CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN",
        "CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN",
        "CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN",
        "CONTROL_PLANE_AWS_INGESTION_TOKEN",
        # Phase 14 correction round, Issue 3: the three new internal
        # read-only service identities join the SAME anti-collision
        # guard -- none of them may ever equal each other OR any
        # existing write-capable token (e.g. an internal read token
        # accidentally set to the same value as
        # CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN would let a
        # read-only internal service's leaked credential be replayed
        # as a human approval decision).
        "CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME",
        "CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR",
        "CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY",
    )
    values = [
        webhook_token,
        lifecycle_token,
        remediation_proposal_token,
        remediation_approver_token,
        remediation_executor_token,
        kubernetes_ingestion_token,
        aws_ingestion_token,
        agent_runtime_internal_read_token,
        investigator_internal_read_token,
        tool_gateway_internal_read_token,
    ]
    cleared = [False] * len(values)
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] is not None and values[j] is not None and values[i] == values[j]:
                logger.error(
                    "%s and %s are configured identically — every endpoint either one would "
                    "authorize will fail closed until they are set to two different values",
                    names[i],
                    names[j],
                )
                cleared[i] = True
                cleared[j] = True

    resolved = [None if cleared[i] else values[i] for i in range(len(values))]
    return tuple(resolved)  # type: ignore[return-value]
