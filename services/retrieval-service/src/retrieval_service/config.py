"""Environment-variable settings for retrieval-service (Phase 6).

Follows the same conventions as investigator_service/config.py and
control_plane/core/config.py: every setting comes from an individual
environment variable (never a pre-built connection string, never a
hardcoded credential), and bounded values are clamped to a sane
[minimum, maximum] range rather than able to silently disable a real
bound.

This service DOES hold PostgreSQL credentials (Phase 6 §2/§10: it owns
reliability.retrieval_chunks) -- unlike investigator-service, which
holds none. It never reads CONTROL_PLANE_WEBHOOK_TOKEN or
CONTROL_PLANE_LIFECYCLE_TOKEN; its control-plane client only ever
issues GET requests (see clients/control_plane.py).

The embedding credential (`RETRIEVAL_EMBEDDING_API_KEY`) is
deliberately a SEPARATE environment variable from
investigator-service's `INVESTIGATOR_LLM_API_KEY` -- a real deployment
may reasonably want a different (or scoped-down) OpenAI credential for
embeddings than for the investigation LLM call, and this service has
no reason to ever see the other one.
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("retrieval_service.config")


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


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


# Fixed across both embedding providers and the pgvector schema (Phase
# 6 §3/§4) -- database/migrations/V5__create_retrieval_index.sql's
# `embedding vector(1536)` column is not configurable at runtime, so
# this is a constant, not an environment variable: changing it would
# require a new migration, not a new deployment setting.
EMBEDDING_DIMENSION = 1536


@dataclass(frozen=True)
class DatabaseSettings:
    """Connection settings for this service's OWN narrow access to
    reliability.retrieval_chunks (and nothing else -- see
    db.py, whose every query is scoped to that one table).
    """

    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            host=os.environ.get("RETRIEVAL_POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "postgres")),
            port=_int_env("RETRIEVAL_POSTGRES_PORT", 5432),
            user=os.environ.get("POSTGRES_USER", ""),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            database=os.environ.get("POSTGRES_DB", ""),
        )


@dataclass(frozen=True)
class EmbeddingSettings:
    """`provider`: "local" (default) uses the deterministic, offline
    lexical hashing provider -- always available, never needs a
    credential, and is what normal CI and the deterministic retrieval-
    quality smoke test both use. "openai" uses a real OpenAI embedding
    model and REQUIRES `api_key`; selecting it without a configured key
    is an explicit startup error (Phase 6 §4: "If the real provider is
    selected but not configured, fail explicitly"), never a silent
    fallback to the local provider.
    """

    provider: Literal["local", "openai"]
    api_key: str | None
    model: str
    base_url: str | None
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "EmbeddingSettings":
        raw_key = os.environ.get("RETRIEVAL_EMBEDDING_API_KEY", "")
        base_url = os.environ.get("RETRIEVAL_EMBEDDING_BASE_URL", "").strip() or None
        provider = os.environ.get("RETRIEVAL_EMBEDDING_PROVIDER", "local").strip().lower()
        if provider not in ("local", "openai"):
            provider = "local"
        return cls(
            provider=provider,  # type: ignore[arg-type]
            api_key=raw_key if raw_key.strip() else None,
            model=os.environ.get("RETRIEVAL_EMBEDDING_MODEL", "text-embedding-3-small"),
            base_url=base_url,
            timeout_seconds=_float_env("RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", 30.0),
        )


@dataclass(frozen=True)
class ControlPlaneSettings:
    base_url: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ControlPlaneSettings":
        return cls(
            base_url=os.environ.get("RETRIEVAL_CONTROL_PLANE_URL", "http://control-plane:8000"),
            connect_timeout_seconds=_float_env("RETRIEVAL_CONNECT_TIMEOUT_SECONDS", 5.0),
            request_timeout_seconds=_float_env("RETRIEVAL_REQUEST_TIMEOUT_SECONDS", 10.0),
        )


@dataclass(frozen=True)
class IndexingBounds:
    """Bounds for the explicit indexer only (Phase 6 §6/§7/§8) -- the
    HTTP search API never writes, so none of these apply to it (see
    SearchBounds below).

    `knowledge_root` is the ONLY filesystem root the indexer will ever
    read from -- never a request parameter, never arbitrary host paths
    (Phase 6 §6: "Do not allow a request parameter to index arbitrary
    host paths"). It is a plain, explicit, operator-set configuration
    value.
    """

    knowledge_root: str
    max_chunk_chars: int
    chunk_overlap_chars: int
    max_historical_incidents: int
    max_audit_events_per_incident: int
    max_incident_text_length: int

    @classmethod
    def from_env(cls) -> "IndexingBounds":
        return cls(
            knowledge_root=os.environ.get("RETRIEVAL_KNOWLEDGE_ROOT", "/knowledge"),
            max_chunk_chars=_clamped_int_env("RETRIEVAL_MAX_CHUNK_CHARS", 1200, 200, 8000),
            chunk_overlap_chars=_clamped_int_env("RETRIEVAL_CHUNK_OVERLAP_CHARS", 150, 0, 2000),
            max_historical_incidents=_clamped_int_env("RETRIEVAL_MAX_HISTORICAL_INCIDENTS", 200, 1, 5000),
            max_audit_events_per_incident=_clamped_int_env(
                "RETRIEVAL_MAX_AUDIT_EVENTS_PER_INCIDENT", 100, 1, 2000
            ),
            max_incident_text_length=_clamped_int_env("RETRIEVAL_MAX_INCIDENT_TEXT_LENGTH", 2000, 100, 10000),
        )


@dataclass(frozen=True)
class SearchBounds:
    """Bounds for POST /api/v1/retrieval/search (Phase 6 §9) -- a
    read-only endpoint. Every one of these is a hard validation ceiling
    on the REQUEST, not a tunable the caller can raise past this
    service's own configured maximum.
    """

    max_query_length: int
    max_result_limit: int
    default_result_limit: int
    max_excerpt_chars: int

    @classmethod
    def from_env(cls) -> "SearchBounds":
        return cls(
            max_query_length=_clamped_int_env("RETRIEVAL_MAX_QUERY_LENGTH", 2000, 10, 10000),
            max_result_limit=_clamped_int_env("RETRIEVAL_MAX_RESULT_LIMIT", 10, 1, 50),
            default_result_limit=_clamped_int_env("RETRIEVAL_DEFAULT_RESULT_LIMIT", 3, 1, 50),
            max_excerpt_chars=_clamped_int_env("RETRIEVAL_MAX_EXCERPT_CHARS", 500, 50, 5000),
        )


@dataclass(frozen=True)
class OrganizationContextSettings:
    """Phase 14 correction round, Issue 2/3: the SAME shared
    environment variable (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT)
    control-plane/agent-runtime-service/investigator-service all read
    -- one global secure-mode switch, never independently enabled
    per service."""

    enabled: bool

    @classmethod
    def from_env(cls) -> "OrganizationContextSettings":
        raw = os.environ.get("CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "false")
        return cls(enabled=raw.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class ServiceAssertionSettings:
    """Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A:
    resolving `exclude_incident_id`'s REAL owning organization (see
    search.py::_resolve_historical_organization_scope) proves which
    tenant owns the incident -- it does NOT prove the CALLER is
    actually authorized for that tenant. A valid
    RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR alone only proves "this
    is really investigator-service's own process"; it never identifies
    which real human actor investigator-service is acting on behalf of
    for THIS specific request. This module verifies a signed
    `X-Service-Assertion` investigator-service relays (mirrors its own
    identical relay to control-plane, `investigator_service.authz`) --
    carrying the REAL, already-verified actor whose organization must
    then be compared, in search.py, against the incident's real
    organization before ANY tenant-private historical result is
    returned. Same shared HS256 secret as every other service;
    `trusted_issuers` is deliberately narrow (investigator-service
    only -- no other service calls this one), and `audience` is this
    service's OWN identity, distinct from every other service's."""

    secret: str | None
    trusted_issuers: frozenset[str]
    audience: str
    max_clock_skew_seconds: float

    @classmethod
    def from_env(cls) -> "ServiceAssertionSettings":
        raw = os.environ.get("SERVICE_ASSERTION_SIGNING_SECRET", "")
        raw_issuers = os.environ.get("SERVICE_ASSERTION_TRUSTED_ISSUERS_RETRIEVAL", "investigator-service")
        return cls(
            secret=raw if raw.strip() else None,
            trusted_issuers=frozenset(i.strip() for i in raw_issuers.split(",") if i.strip()),
            audience=os.environ.get("SERVICE_ASSERTION_AUDIENCE_RETRIEVAL", "retrieval-service"),
            max_clock_skew_seconds=_float_env("SERVICE_ASSERTION_MAX_CLOCK_SKEW_SECONDS", 30.0),
        )


@dataclass(frozen=True)
class InternalCallerTokenSettings:
    """Phase 14 correction round, Issue 2/3: closes "a direct HTTP
    call to this service's own exposed port (127.0.0.1:8002) bypasses
    investigator-service" -- this service's only legitimate caller.
    Checked against `X-Internal-Service-Token`
    (RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR); never a human-actor
    credential -- this service has no browser-facing API."""

    investigator_caller_token: str | None

    @classmethod
    def from_env(cls) -> "InternalCallerTokenSettings":
        raw = os.environ.get("RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR", "")
        return cls(investigator_caller_token=raw if raw.strip() else None)
