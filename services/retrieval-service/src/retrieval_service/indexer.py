"""The explicit, offline indexer (Phase 6 §8). The ONLY code in this
service allowed to write reliability.retrieval_chunks -- the HTTP API
(api/search.py) never writes anything (see
tests/test_read_only_guarantees.py).

Run as: `python -m retrieval_service.indexer` (see `make rag-index`).
Never exposed as a public HTTP mutation endpoint (Phase 6 §8).

Indexes, in order:
  1. source-controlled knowledge (knowledge.py's allowlisted root).
  2. current historical incidents, read ONLY through control-plane's
     existing GET APIs (clients/control_plane.py) -- never a direct
     reliability.incidents read, and this module never calls a
     control-plane write endpoint (it has no Bearer token to do so
     with in the first place).

Idempotent (Phase 6 §6/§8): re-running immediately with unchanged
sources upserts onto the exact same rows (db.upsert_chunk's own
ON CONFLICT target) and deletes nothing, since nothing is stale --
proven by scripts/verify-rag.sh running this twice and comparing row
counts.

Never prints a credential: the only values ever printed below are
counts, source keys/titles, and the embedding space identifier (a
provider:model:dimension string, never a key).
"""

import asyncio
import logging

from retrieval_service import db
from retrieval_service.chunking import chunk_text, content_hash
from retrieval_service.clients.control_plane import ControlPlaneClient
from retrieval_service.config import ControlPlaneSettings, DatabaseSettings, EmbeddingSettings, IndexingBounds
from retrieval_service.embeddings.provider import (
    EmbeddingProvider,
    EmbeddingProviderNotConfiguredError,
    LocalLexicalEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from retrieval_service.historical import build_historical_incident_text
from retrieval_service.knowledge import load_knowledge_documents

logger = logging.getLogger("retrieval_service.indexer")


def build_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    if settings.provider == "openai":
        if not settings.api_key:
            raise EmbeddingProviderNotConfiguredError(
                "RETRIEVAL_EMBEDDING_PROVIDER=openai but RETRIEVAL_EMBEDDING_API_KEY is not set -- "
                "refusing to silently fall back to the local lexical provider"
            )
        return OpenAIEmbeddingProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
        )
    return LocalLexicalEmbeddingProvider()


async def _index_one_source(
    pool,
    provider: EmbeddingProvider,
    *,
    source_type: str,
    source_key: str,
    title: str,
    text: str,
    metadata: dict,
    bounds: IndexingBounds,
) -> int:
    chunks = chunk_text(text, bounds.max_chunk_chars, bounds.chunk_overlap_chars)
    if not chunks:
        return 0

    embeddings = await provider.embed(chunks)

    # Atomic per-source indexing (Phase 6 correction round): every
    # chunk upsert for THIS source, plus the stale-chunk cleanup that
    # trims it down to its current chunk count, run inside ONE real
    # PostgreSQL transaction via a single acquired connection. If
    # anything fails partway through -- a dropped connection, a
    # constraint violation on a later chunk -- the whole transaction
    # rolls back and this source's previously-indexed rows are left
    # exactly as they were; a half-written source (some new chunks
    # committed, stale ones not yet cleaned up, or vice versa) can
    # never be observed by a concurrent search. Deliberately scoped to
    # ONE source at a time -- never the whole corpus -- so a failure
    # indexing one knowledge file or one historical incident can never
    # roll back every other source already committed earlier in this
    # same run (see index_knowledge/index_historical_incidents, which
    # call this once per source and commit independently).
    async with pool.acquire() as conn, conn.transaction():
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            await db.upsert_chunk(
                conn,
                source_type=source_type,
                source_key=source_key,
                chunk_index=idx,
                title=title,
                content=chunk,
                content_hash=content_hash(chunk),
                metadata=metadata,
                embedding_space=provider.embedding_space,
                embedding=embedding,
            )
        await db.delete_chunks_beyond(
            conn,
            source_type=source_type,
            source_key=source_key,
            embedding_space=provider.embedding_space,
            keep_below_chunk_index=len(chunks),
        )
    return len(chunks)


async def index_knowledge(pool, provider: EmbeddingProvider, bounds: IndexingBounds) -> dict:
    documents = load_knowledge_documents(bounds.knowledge_root)
    total_chunks = 0
    for doc in documents:
        total_chunks += await _index_one_source(
            pool,
            provider,
            source_type="knowledge",
            source_key=doc.source_key,
            title=doc.title,
            text=doc.text,
            metadata={},
            bounds=bounds,
        )

    # Full-corpus stale-source cleanup is safe here: the knowledge root
    # is always fully enumerable in one run (small, curated, no
    # artificial per-run budget truncates it) -- a file removed from
    # knowledge/runbooks/ is genuinely gone, not merely "outside this
    # run's page".
    deleted_sources = await db.delete_sources_not_in(
        pool,
        source_type="knowledge",
        embedding_space=provider.embedding_space,
        keep_source_keys=[doc.source_key for doc in documents],
    )
    return {"documents": len(documents), "chunks": total_chunks, "stale_sources_removed": deleted_sources}


async def index_historical_incidents(
    pool, provider: EmbeddingProvider, control_plane: ControlPlaneClient, bounds: IndexingBounds
) -> dict:
    incidents = await control_plane.list_all_incidents(max_incidents=bounds.max_historical_incidents)
    total_chunks = 0
    for incident in incidents:
        events, events_total = await control_plane.get_all_events(
            str(incident.id), max_events=bounds.max_audit_events_per_incident
        )
        text = build_historical_incident_text(incident, events, events_total, bounds.max_incident_text_length)
        total_chunks += await _index_one_source(
            pool,
            provider,
            source_type="historical_incident",
            source_key=str(incident.id),
            title=incident.title,
            text=text,
            metadata={
                "severity": incident.severity,
                "status": incident.status,
                "source": incident.source,
            },
            bounds=bounds,
        )

    # Deliberately NO full-corpus "delete sources not in" cleanup here
    # (Phase 6 §7/§20): incidents are never deleted in this platform,
    # and max_historical_incidents is a per-run BUDGET, not a claim
    # that every incident outside it no longer exists -- treating a
    # bound-truncated page as "these incidents are gone" would delete
    # genuinely valid historical retrieval data. Within-incident stale
    # chunk cleanup (via _index_one_source's own delete_chunks_beyond)
    # still applies normally.
    return {"incidents": len(incidents), "chunks": total_chunks}


async def run() -> dict:
    db_settings = DatabaseSettings.from_env()
    embedding_settings = EmbeddingSettings.from_env()
    control_plane_settings = ControlPlaneSettings.from_env()
    bounds = IndexingBounds.from_env()

    provider = build_embedding_provider(embedding_settings)
    pool = await db.create_pool(db_settings)
    control_plane = ControlPlaneClient(
        control_plane_settings.base_url,
        control_plane_settings.connect_timeout_seconds,
        control_plane_settings.request_timeout_seconds,
    )

    try:
        knowledge_result = await index_knowledge(pool, provider, bounds)
        historical_result = await index_historical_incidents(pool, provider, control_plane, bounds)
    finally:
        await pool.close()

    return {
        "embedding_space": provider.embedding_space,
        "knowledge": knowledge_result,
        "historical_incidents": historical_result,
    }


def _print_summary(result: dict) -> None:
    print(f"embedding_space: {result['embedding_space']}")
    k = result["knowledge"]
    print(
        f"knowledge: {k['documents']} document(s), {k['chunks']} chunk(s) indexed"
        f" ({k['stale_sources_removed']} stale source(s) removed)"
    )
    h = result["historical_incidents"]
    print(f"historical_incidents: {h['incidents']} incident(s), {h['chunks']} chunk(s) indexed")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run())
    _print_summary(result)


if __name__ == "__main__":
    main()
