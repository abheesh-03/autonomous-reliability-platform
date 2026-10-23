"""POST /api/v1/retrieval/search -- the one search endpoint this
service exposes beyond health checks (Phase 6 §9). Read-only: the
query is never persisted, and this route never imports or calls
anything in indexer.py/db.py's write functions (see
tests/test_read_only_guarantees.py, which checks this at the AST
level).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from retrieval_service import search as search_module
from retrieval_service.authz import ActorContext, get_relayed_actor, require_internal_caller
from retrieval_service.domain.search import SearchRequest, SearchResponse
from retrieval_service.embeddings.provider import EmbeddingProviderError

logger = logging.getLogger("retrieval_service.api.search")

router = APIRouter(prefix="/api/v1")


@router.post(
    "/retrieval/search",
    response_model=SearchResponse,
    dependencies=[Depends(require_internal_caller)],
)
async def search_retrieval(
    body: SearchRequest,
    request: Request,
    actor: Annotated[ActorContext | None, Depends(get_relayed_actor)],
) -> SearchResponse:
    pool = request.app.state.pool
    provider = request.app.state.embedding_provider
    bounds = request.app.state.search_bounds
    org_context_settings = request.app.state.organization_context_settings

    try:
        return await search_module.search(pool, provider, bounds, body, org_context_settings, actor)
    except EmbeddingProviderError:
        logger.warning("embedding provider failed during search", exc_info=True)
        raise HTTPException(status_code=502, detail="embedding provider request failed")
