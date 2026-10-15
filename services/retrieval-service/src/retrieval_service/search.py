"""Read-only search (Phase 6 §9/§10). This module, and the HTTP route
that calls it (api/search.py), NEVER write to
reliability.retrieval_chunks -- see db.py, which exposes no write
function this module imports; and tests/test_read_only_guarantees.py,
which asserts that fact at the AST level.
"""

import asyncpg

from retrieval_service import db
from retrieval_service.config import SearchBounds
from retrieval_service.domain.search import SearchRequest, SearchResponse, SearchResultItem
from retrieval_service.embeddings.provider import EmbeddingProvider


def _truncate_excerpt(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "...[truncated]"


async def search(
    pool: asyncpg.Pool, provider: EmbeddingProvider, bounds: SearchBounds, request: SearchRequest
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

    historical_rows = (
        await db.search_chunks(
            pool,
            source_type="historical_incident",
            embedding_space=provider.embedding_space,
            query_embedding=query_embedding,
            limit=historical_limit,
            exclude_source_key=str(request.exclude_incident_id) if request.exclude_incident_id else None,
        )
        if historical_limit > 0
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
