"""FastAPI application factory for retrieval-service (Phase 6).

This process's HTTP surface is SEARCH-ONLY (Phase 6 §9/§10):
POST /api/v1/retrieval/search never writes to
reliability.retrieval_chunks. The only code path that ever writes to
it is the separate, explicit indexer (`python -m
retrieval_service.indexer` / `make rag-index`), which is never invoked
from an HTTP handler in this app.

This service DOES hold PostgreSQL credentials (unlike
investigator-service, which holds none) -- it owns
reliability.retrieval_chunks. It never reads
CONTROL_PLANE_WEBHOOK_TOKEN or CONTROL_PLANE_LIFECYCLE_TOKEN, and its
control-plane client (used only by the indexer, not by this HTTP app)
has no write method at all.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from retrieval_service import db
from retrieval_service.api.health import router as health_router
from retrieval_service.api.search import router as search_router
from retrieval_service.config import (
    DatabaseSettings,
    EmbeddingSettings,
    InternalCallerTokenSettings,
    OrganizationContextSettings,
    SearchBounds,
    ServiceAssertionSettings,
)
from retrieval_service.embeddings.provider import EmbeddingProviderNotConfiguredError, LocalLexicalEmbeddingProvider
from retrieval_service.indexer import build_embedding_provider

logger = logging.getLogger("retrieval_service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_settings = DatabaseSettings.from_env()
    embedding_settings = EmbeddingSettings.from_env()
    search_bounds = SearchBounds.from_env()

    try:
        embedding_provider = build_embedding_provider(embedding_settings)
    except EmbeddingProviderNotConfiguredError:
        # Non-blocking startup, same philosophy as investigator-service's
        # own LLM provider: this process still starts and still serves
        # /health/ready honestly (reporting the misconfiguration), but
        # falls back to the local provider only for the HTTP app's own
        # read path -- this never happens for the indexer, which raises
        # the same error directly and refuses to index anything (Phase
        # 6 §4: "fail explicitly", never a silent fallback there).
        logger.warning(
            "RETRIEVAL_EMBEDDING_PROVIDER=openai but RETRIEVAL_EMBEDDING_API_KEY is not set -- "
            "search will use the deterministic local provider's embedding space, which will not "
            "match any chunk indexed under a real OpenAI embedding space"
        )
        embedding_provider = LocalLexicalEmbeddingProvider()

    pool = await db.create_pool(db_settings)

    app.state.pool = pool
    app.state.embedding_provider = embedding_provider
    app.state.search_bounds = search_bounds
    # Phase 14 correction round, Issue 2/3: non-blocking at startup,
    # same philosophy as the embedding provider above.
    app.state.organization_context_settings = OrganizationContextSettings.from_env()
    app.state.internal_caller_token_settings = InternalCallerTokenSettings.from_env()
    # Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A.
    app.state.service_assertion_settings = ServiceAssertionSettings.from_env()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(
    title="Autonomous Reliability Platform — Retrieval Service",
    description=(
        "Phase 6: a search-only RAG retrieval index over source-controlled operational knowledge "
        "and historical incidents, backed by PostgreSQL + pgvector. Writes happen only via the "
        "separate, explicit indexer (python -m retrieval_service.indexer) -- this HTTP API never "
        "mutates the retrieval index, and holds no write-capable control-plane credential."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(search_router)
