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
        return cls(
            host=os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "postgres")),
            port=_int_env("AGENT_RUNTIME_DB_PORT", _int_env("POSTGRES_INTERNAL_PORT", 5432)),
            user=user,
            password=os.environ.get("AGENT_RUNTIME_DB_PASSWORD", ""),
            database=os.environ.get("POSTGRES_DB", ""),
            schema=schema,
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
