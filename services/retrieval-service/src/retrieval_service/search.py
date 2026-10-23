"""Read-only search (Phase 6 §9/§10). This module, and the HTTP route
that calls it (api/search.py), NEVER write to
reliability.retrieval_chunks -- see db.py, which exposes no write
function this module imports; and tests/test_read_only_guarantees.py,
which asserts that fact at the AST level.
"""

import logging

import asyncpg

from retrieval_service import db
from retrieval_service.authz import ActorContext
from retrieval_service.config import OrganizationContextSettings, SearchBounds
from retrieval_service.domain.search import SearchRequest, SearchResponse, SearchResultItem
from retrieval_service.embeddings.provider import EmbeddingProvider

logger = logging.getLogger("retrieval_service.search")


def _truncate_excerpt(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "...[truncated]"


async def _resolve_historical_organization_scope(
    pool: asyncpg.Pool,
    org_context_settings: OrganizationContextSettings,
    request: SearchRequest,
    actor: ActorContext | None,
) -> tuple[str | None, bool]:
    """Phase 14 correction round, Blocker 2 + FINAL MACHINE-IDENTITY
    TENANT-BOUNDARY FIX (Issue A): decides what `organization_id` (if
    any) governs the historical-incident tenant filter, and whether
    historical search may proceed at all.

    Legacy/local-development mode (the shared
    CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT toggle disabled):
    preserves this endpoint's exact pre-Phase-14 behavior -- the
    caller-supplied `request.organization_id` (optionally None,
    meaning unscoped) is used as-is. This is the ONLY code path that
    still trusts a client-supplied organization_id, and only while
    this service is explicitly run in that isolated development mode.

    Secure mode (enabled): `request.organization_id` is NEVER trusted
    for this decision, regardless of what value it holds. Resolving
    `exclude_incident_id`'s REAL owning organization (Blocker 2) proves
    which tenant owns the incident -- it does NOT by itself prove the
    CALLER is authorized to see that tenant's data; a valid internal
    read token alone only proves "this is really investigator-service",
    never "this request's claimed actor/tenant is real" (Issue A: "An
    authenticated internal caller can name ANY existing incident ID
    and obtain the owning organization's historical retrieval
    results" -- resolving an object's real organization is not
    equivalent to authorizing the caller for that organization).

    The actual authorization decision is therefore now TWO independent
    facts that must BOTH hold:
      1. `exclude_incident_id` resolves to a real incident (Blocker 2,
         unchanged) -- a resource-bound grant, never a free-form claim.
      2. A relayed, verified actor assertion (`get_relayed_actor`) is
         present, AND that actor's own `organization_id` matches the
         incident's real owning organization exactly (Issue A) -- never
         the bare internal token alone, never incident-id possession
         alone, and never a client-supplied organization_id.
    Returns `(None, False)` (meaning: run no historical search at all)
    whenever either fact is missing -- an honest "cannot establish
    tenant scope", never a fabricated/unscoped result and never an HTTP
    error (the request's global `knowledge` results are unaffected).
    """
    if not org_context_settings.enabled:
        return (str(request.organization_id) if request.organization_id else None), True

    if request.exclude_incident_id is None:
        logger.warning(
            "organization-context enforcement is enabled but no exclude_incident_id was supplied -- "
            "historical-incident search cannot establish a trusted tenant scope; returning no results"
        )
        return None, False

    organization_id = await db.get_incident_organization_id(pool, str(request.exclude_incident_id))
    if organization_id is None:
        logger.warning(
            "organization-context enforcement is enabled but exclude_incident_id=%s does not resolve to a "
            "real incident -- historical-incident search cannot establish a trusted tenant scope; "
            "returning no results",
            request.exclude_incident_id,
        )
        return None, False

    if actor is None:
        logger.warning(
            "organization-context enforcement is enabled but no relayed actor assertion was presented -- "
            "an internal credential alone cannot authorize a tenant-scoped historical search; "
            "returning no results"
        )
        return None, False

    if actor.organization_id != organization_id:
        logger.warning(
            "organization-context enforcement is enabled but the relayed actor's organization does not "
            "match exclude_incident_id=%s's real owning organization -- refusing to disclose another "
            "tenant's historical evidence; returning no results",
            request.exclude_incident_id,
        )
        return None, False

    return organization_id, True


async def search(
    pool: asyncpg.Pool,
    provider: EmbeddingProvider,
    bounds: SearchBounds,
    request: SearchRequest,
    org_context_settings: OrganizationContextSettings,
    actor: ActorContext | None = None,
) -> SearchResponse:
    query = request.query.strip()[: bounds.max_query_length]
    knowledge_limit = min(request.knowledge_limit, bounds.max_result_limit)
    historical_limit = min(request.historical_incident_limit, bounds.max_result_limit)

    [query_embedding] = await provider.embed([query])

    knowledge_rows = (
        await db.search_chunks(
            pool,
            source_type="knowledge",
            embedding_space=provider.embedding_space,
            query_embedding=query_embedding,
            limit=knowledge_limit,
        )
        if knowledge_limit > 0
        else []
    )

    organization_id, may_search_historical = await _resolve_historical_organization_scope(
        pool, org_context_settings, request, actor
    )

    historical_rows = (
        await db.search_chunks(
            pool,
            source_type="historical_incident",
            embedding_space=provider.embedding_space,
            query_embedding=query_embedding,
            limit=historical_limit,
            exclude_source_key=str(request.exclude_incident_id) if request.exclude_incident_id else None,
            organization_id=organization_id,
        )
        if historical_limit > 0 and may_search_historical
        else []
    )

    def to_item(row: db.RetrievalChunkRow) -> SearchResultItem:
        return SearchResultItem(
            id=row.id,
            source_type=row.source_type,
            source_key=row.source_key,
            title=row.title,
            excerpt=_truncate_excerpt(row.content, bounds.max_excerpt_chars),
            # Cosine distance in [0, 2] -> a ranking score in roughly
            # [-1, 1], higher is "ranked closer". Documented in
            # domain.search.SearchResultItem as ranking-only, never a
            # probability or confidence value.
            similarity=1.0 - row.distance,
            metadata=row.metadata,
            embedding_space=row.embedding_space,
        )

    return SearchResponse(
        knowledge=[to_item(r) for r in knowledge_rows],
        historical_incidents=[to_item(r) for r in historical_rows],
        embedding_space=provider.embedding_space,
    )
