"""Environment-variable settings for agent-runtime-service (Phase 7).

Follows the same conventions as investigator_service/config.py and
retrieval_service/config.py: every setting comes from an individual
environment variable, never a pre-built connection string with a
hardcoded credential.

This service DOES hold PostgreSQL credentials (Phase 7's own durable
LangGraph checkpoint store) -- but deliberately NOT the broad
POSTGRES_USER/POSTGRES_PASSWORD role the rest of this platform's
application code uses. It connects as a dedicated, least-privileged
`agent_runtime` role (see scripts/init-agent-runtime-db.sh), which
cannot read or write reliability.incidents / reliability.incident_events
/ reliability.retrieval_chunks at all -- proven by a real PostgreSQL
test, not merely asserted (see tests/test_db_privilege_boundary.py).

It never reads CONTROL_PLANE_WEBHOOK_TOKEN or
CONTROL_PLANE_LIFECYCLE_TOKEN -- its control-plane client has no write
method at all, and its investigator client has exactly one method,
a POST to investigator-service's own already-read-only/computational
`/api/v1/investigations` endpoint.
"""

import logging
import os
from dataclasses import dataclass

from psycopg.conninfo import make_conninfo

logger = logging.getLogger("agent_runtime_service.config")

# The identity (role, schema) the dedicated checkpoint connection MUST
# use -- an architectural security constant (Phase 7 correction round,
# finding #6), never a normal operator tuning knob. scripts/init-agent-runtime-db.sh
# provisions exactly this role/schema; test_db_privilege_boundary.py's
# real-PostgreSQL proof connects AS exactly this role. Allowing either
# to silently drift (e.g. an operator accidentally setting
# AGENT_RUNTIME_DB_USER=postgres) would make that proof refer to a
# role the running service never actually uses -- see
# CheckpointDbSettings.from_env's fail-closed validation below.
REQUIRED_CHECKPOINT_DB_USER = "agent_runtime"
REQUIRED_CHECKPOINT_DB_SCHEMA = "agent_runtime"


class InvalidCheckpointIdentityError(RuntimeError):
    """Raised at startup if AGENT_RUNTIME_DB_USER/AGENT_RUNTIME_DB_SCHEMA
    are explicitly set to anything other than the required constant --
    fail closed rather than silently run with a broader role/schema."""


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
    value = _int_env(name, default)
    if value < minimum:
        logger.warning("%s=%s is below the minimum %s; clamping to %s", name, value, minimum, minimum)
        return minimum
    if value > maximum:
        logger.warning("%s=%s exceeds the maximum %s; clamping to %s", name, value, maximum, maximum)
        return maximum
    return value


@dataclass(frozen=True)
class CheckpointDbSettings:
    """The dedicated, least-privileged checkpoint database connection
    (Phase 7's own -- never the shared POSTGRES_USER/POSTGRES_PASSWORD
    role). `schema` is where this role's own `search_path` already
    points (set once by scripts/init-agent-runtime-db.sh at the ROLE
    level) -- this setting exists for this service's OWN explicit,
    schema-qualified readiness/introspection queries, never to grant
    additional access itself.
    """

    host: str
    port: int
    user: str
    password: str
    database: str
    schema: str
    # Post-commit fix (GitHub Actions run #33): a genuinely small,
    # bounded psycopg_pool.AsyncConnectionPool -- replaces the prior
    # single process-lifetime connection, which a real `docker compose
    # restart postgres` (an existing Phase 3E acceptance behavior, not
    # new) permanently killed, leaving /health/ready AdminShutdown-ing
    # forever until agent-runtime-service itself was restarted. A pool
    # detects and replaces a dead connection on its own; this is
    # psycopg_pool's own built-in resilience, not custom reconnection
    # logic (see checkpointer.py). Intentionally small -- Phase 7 is
    # not a scalability phase and this is not a production-sized pool.
    pool_min_size: int
    pool_max_size: int
    pool_open_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "CheckpointDbSettings":
        user = os.environ.get("AGENT_RUNTIME_DB_USER", REQUIRED_CHECKPOINT_DB_USER)
        schema = os.environ.get("AGENT_RUNTIME_DB_SCHEMA", REQUIRED_CHECKPOINT_DB_SCHEMA)
        if user != REQUIRED_CHECKPOINT_DB_USER:
            raise InvalidCheckpointIdentityError(
                f"AGENT_RUNTIME_DB_USER={user!r} is not the required dedicated, least-privileged "
                f"checkpoint role {REQUIRED_CHECKPOINT_DB_USER!r} -- refusing to start rather than "
                "silently connect as a different, potentially broader role"
            )
        if schema != REQUIRED_CHECKPOINT_DB_SCHEMA:
            raise InvalidCheckpointIdentityError(
                f"AGENT_RUNTIME_DB_SCHEMA={schema!r} is not the required dedicated checkpoint schema "
                f"{REQUIRED_CHECKPOINT_DB_SCHEMA!r} -- refusing to start rather than silently create "
                "LangGraph's checkpoint tables somewhere else"
            )
        pool_min_size = _clamped_int_env("AGENT_RUNTIME_DB_POOL_MIN_SIZE", 1, 1, 10)
        pool_max_size = _clamped_int_env("AGENT_RUNTIME_DB_POOL_MAX_SIZE", 4, 1, 10)
        if pool_max_size < pool_min_size:
            logger.warning(
                "AGENT_RUNTIME_DB_POOL_MAX_SIZE=%s is below AGENT_RUNTIME_DB_POOL_MIN_SIZE=%s; raising max to match min",
                pool_max_size,
                pool_min_size,
            )
            pool_max_size = pool_min_size
        return cls(
            host=os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "postgres")),
            port=_int_env("AGENT_RUNTIME_DB_PORT", _int_env("POSTGRES_INTERNAL_PORT", 5432)),
            user=user,
            password=os.environ.get("AGENT_RUNTIME_DB_PASSWORD", ""),
            database=os.environ.get("POSTGRES_DB", ""),
            schema=schema,
            pool_min_size=pool_min_size,
            pool_max_size=pool_max_size,
            pool_open_timeout_seconds=_float_env("AGENT_RUNTIME_DB_POOL_OPEN_TIMEOUT_SECONDS", 10.0),
        )

    def conn_string(self) -> str:
        # Phase 7 correction round (finding #10): built via psycopg's
        # own `make_conninfo` -- a real libpq keyword/value conninfo
        # string, correctly quoting/escaping any reserved character
        # (`@`, `:`, `/`, `?`, `#`, whitespace, ...) in `password`.
        # This service's OWN auto-generated password
        # (scripts/init-agent-runtime-db.sh's `secrets.token_hex(32)`,
        # hex digits only) could never trigger this, but an
        # operator-supplied password is not guaranteed to be URI-safe,
        # and a naive f-string/URI build silently breaks on one that
        # isn't. sslmode is left at its client default (local Compose
        # network, same as every other service's plain-Postgres
        # local-development trust boundary already documented
        # elsewhere in this repo). NEVER log or print this value.
        return make_conninfo(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            dbname=self.database,
        )


@dataclass(frozen=True)
class ControlPlaneSettings:
    base_url: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ControlPlaneSettings":
        return cls(
            base_url=os.environ.get("AGENT_RUNTIME_CONTROL_PLANE_URL", "http://control-plane:8000"),
            connect_timeout_seconds=_float_env("AGENT_RUNTIME_CONNECT_TIMEOUT_SECONDS", 5.0),
            request_timeout_seconds=_float_env("AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS", 10.0),
        )


@dataclass(frozen=True)
class InvestigatorSettings:
    base_url: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "InvestigatorSettings":
        return cls(
            base_url=os.environ.get("AGENT_RUNTIME_INVESTIGATOR_URL", "http://investigator-service:8001"),
            connect_timeout_seconds=_float_env("AGENT_RUNTIME_CONNECT_TIMEOUT_SECONDS", 5.0),
            # Investigation requests involve a real LLM call -- a
            # materially longer bound than a plain GET, matching
            # investigator-service's own INVESTIGATOR_LLM_TIMEOUT_SECONDS
            # default (30s) plus margin for its own evidence collection.
            request_timeout_seconds=_float_env("AGENT_RUNTIME_INVESTIGATOR_TIMEOUT_SECONDS", 60.0),
        )


@dataclass(frozen=True)
class InternalReadTokenSettings:
    """Phase 14 correction round, Issue 3: this service's own
    distinct, bounded internal-service-read identity, presented to
    control-plane (and, for run_investigation, re-derived into a
    SEPARATE assertion forwarded to investigator-service -- see
    graph/nodes.py) -- never usable as a human-approval credential.
    Mirrors control_plane.core.config.InternalServiceReadTokenSettings'
    own agent_runtime_token exactly (same literal value on both
    services)."""

    control_plane_token: str
    investigator_token: str

    @classmethod
    def from_env(cls) -> "InternalReadTokenSettings":
        return cls(
            control_plane_token=os.environ.get("CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME", ""),
            investigator_token=os.environ.get("INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME", ""),
        )


@dataclass(frozen=True)
class RemediationSettings:
    """Phase 8: the ONE remediation credential this service holds for
    control-plane -- CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN. Never
    CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN or
    CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN (this module never even
    reads either environment variable), never
    CONTROL_PLANE_WEBHOOK_TOKEN/CONTROL_PLANE_LIFECYCLE_TOKEN, and
    never PAYMENT_FAULT_INJECTION_TOKEN/PAYMENT_REMEDIATION_TOKEN --
    see tests/test_read_only_guarantees.py's structural proof.
    Deliberately non-blocking at startup (empty string default): an
    unconfigured token just means control-plane's own
    require_remediation_proposal_token fails every create-proposal
    call closed (401) -- never a crash."""

    proposal_token: str

    @classmethod
    def from_env(cls) -> "RemediationSettings":
        return cls(proposal_token=os.environ.get("CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN", ""))


@dataclass(frozen=True)
class ToolGatewaySettings:
    """Phase 8: the ONE tool-gateway credential this service holds --
    TOOL_GATEWAY_EXECUTION_TOKEN. This token alone never authorizes an
    action (tool-gateway independently re-verifies control-plane's own
    approved proposal on every call) -- see
    docs/architecture/phase-8-human-approval-remediation.md."""

    base_url: str
    execution_token: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ToolGatewaySettings":
        return cls(
            base_url=os.environ.get("AGENT_RUNTIME_TOOL_GATEWAY_URL", "http://tool-gateway:8004"),
            execution_token=os.environ.get("TOOL_GATEWAY_EXECUTION_TOKEN", ""),
            connect_timeout_seconds=_float_env("AGENT_RUNTIME_CONNECT_TIMEOUT_SECONDS", 5.0),
            # Execution involves a real downstream mutation + independent
            # verification round-trip inside tool-gateway -- a materially
            # longer bound than a plain GET, matching the generous margin
            # InvestigatorSettings already gives a real LLM call.
            request_timeout_seconds=_float_env("AGENT_RUNTIME_TOOL_GATEWAY_TIMEOUT_SECONDS", 30.0),
        )


@dataclass(frozen=True)
class OrganizationContextSettings:
    """Phase 14: mirrors control_plane.core.config.OrganizationContextSettings
    exactly -- the SAME environment variable
    (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT), so both services are
    always enabled/disabled together, never independently (a mismatch
    would mean this service trusts a run as tenant-scoped while
    control-plane still treats it as unscoped, or vice versa)."""

    enabled: bool

    @classmethod
    def from_env(cls) -> "OrganizationContextSettings":
        raw = os.environ.get("CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "false")
        return cls(enabled=raw.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class ServiceAssertionSettings:
    """Phase 14: mirrors control_plane.core.config.ServiceAssertionSettings
    exactly -- verifies the SAME signed assertion web-console's BFF
    minted for control-plane, using the SAME shared HS256 secret
    (SERVICE_ASSERTION_SIGNING_SECRET) and the SAME pinned issuer. The
    audience is deliberately DIFFERENT from control-plane's
    (SERVICE_ASSERTION_AUDIENCE_AGENT_RUNTIME, defaulting to
    "agent-runtime-service") -- an assertion minted for one backend
    must not be replayable against the other; the BFF mints a separate
    assertion per downstream call with the matching audience."""

    secret: str | None
    issuer: str
    audience: str
    max_clock_skew_seconds: float
    # Phase 14 correction round, Blocker 1: the audiences THIS service
    # mints its own DERIVED assertions for, when relaying an
    # already-verified actor onward -- never the audience it verifies
    # INCOMING assertions against (that's `audience`, above, fixed to
    # this service's own identity). Mirrors control-plane's/
    # investigator-service's own `SERVICE_ASSERTION_AUDIENCE` default
    # exactly, so a derived assertion lands on the SAME audience value
    # the receiving service already expects of a directly-minted one.
    control_plane_audience: str
    investigator_audience: str

    @classmethod
    def from_env(cls) -> "ServiceAssertionSettings":
        raw = os.environ.get("SERVICE_ASSERTION_SIGNING_SECRET", "")
        return cls(
            secret=raw if raw.strip() else None,
            issuer=os.environ.get("SERVICE_ASSERTION_ISSUER", "web-console"),
            audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_AGENT_RUNTIME", "agent-runtime-service"),
            max_clock_skew_seconds=_float_env("SERVICE_ASSERTION_MAX_CLOCK_SKEW_SECONDS", 30.0),
            control_plane_audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_CONTROL_PLANE", "control-plane"),
            investigator_audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_INVESTIGATOR", "investigator-service"),
        )


@dataclass(frozen=True)
class RuntimeBounds:
    """Practical bounds for this service's own API surface -- never a
    claim about investigator-service's own bounds (which it owns and
    enforces itself)."""

    max_history_items: int
    max_error_detail_chars: int
    # Phase 7 correction round (finding #4): bounds free-text fields
    # (title/description/source/source_fingerprint) copied from
    # control-plane's incident response before they enter durable graph
    # state -- see text_safety.py. Mirrors investigator-service's own
    # INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH default/range exactly (same
    # underlying V1 schema, same risk).
    max_incident_text_chars: int
    # Phase 7 correction round (follow-up, finding #3): a hard ceiling
    # on an InvestigationReport's own SERIALIZED SIZE before it may
    # enter durable graph state -- Phase 5/6 bound individual
    # evidence/prompt fields but impose no ceiling on the investigator's
    # output as a whole. Default (512 KiB) chosen with generous
    # headroom over a real, measured report from this environment (a
    # 32-evidence-item, full-RAG-provenance report serialized to
    # ~20.8 KB) -- roughly 25x headroom, not a tight fit.
    max_investigation_report_bytes: int

    @classmethod
    def from_env(cls) -> "RuntimeBounds":
        return cls(
            max_history_items=_clamped_int_env("AGENT_RUNTIME_MAX_HISTORY_ITEMS", 50, 1, 500),
            max_error_detail_chars=_clamped_int_env("AGENT_RUNTIME_MAX_ERROR_DETAIL_CHARS", 300, 50, 2000),
            max_incident_text_chars=_clamped_int_env("AGENT_RUNTIME_MAX_INCIDENT_TEXT_LENGTH", 2000, 100, 10000),
            max_investigation_report_bytes=_clamped_int_env(
                "AGENT_RUNTIME_MAX_INVESTIGATION_REPORT_BYTES", 524_288, 10_000, 5_000_000
            ),
        )
