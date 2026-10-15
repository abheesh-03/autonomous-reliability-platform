"""Real-database regression test for atomic per-source indexing
(Phase 6 correction round, issue 1): "if any operation fails, preserve
that source's previously indexed state."

This is a deliberate, narrow exception to this test suite's usual
"never touch a real database" rule (see test_indexer.py's own
docstring) -- db.py's ON CONFLICT upsert and PostgreSQL's own
transaction rollback are exactly the kind of behavior a monkeypatched
fake cannot prove; only a real connection can. It is still entirely
self-contained and safe: every row it writes/reads/deletes is scoped
under a single run-unique `source_key` this test generates itself
(`test-atomic-rollback-<uuid4>`), which can never collide with a real
knowledge file path or a real incident UUID, and the test deletes its
own rows in a `finally` block regardless of outcome. It never touches
`reliability.incidents`/`reliability.incident_events` at all.

Gracefully SKIPPED (not failed) when no real database is reachable --
e.g. the Docker-isolated `make retrieval-test` run, which has no
postgres service linked. Run it against the real stack with, for
example:

    docker run --rm --network autonomous-reliability-platform_default \\
      -v "$(pwd)/services/retrieval-service:/app" -w /app \\
      -e RETRIEVAL_POSTGRES_HOST=postgres \\
      -e POSTGRES_USER=... -e POSTGRES_PASSWORD=... -e POSTGRES_DB=... \\
      python:3.13-slim bash -c "pip install -q -e '.[dev]' && pytest tests/test_db_transaction.py -v"

Setting `RETRIEVAL_REQUIRE_REAL_DB=true` turns the graceful skip above
into a hard FAILURE instead -- used by CI's dedicated "Verify
real-database transaction rollback (Phase 6)" step (run after
PostgreSQL is healthy and Flyway has applied V1-V5), so this real
rollback proof is actually enforced there, never silently skipped.
The normal, fast `make retrieval-test` / "Run retrieval-service tests"
CI step never sets this variable, so it is unaffected and still skips
exactly as before.
"""

import os
import uuid

import pytest

from retrieval_service import db, indexer
from retrieval_service.config import DatabaseSettings, IndexingBounds
from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider

TEST_BOUNDS = IndexingBounds(
    knowledge_root="/unused",
    max_chunk_chars=40,
    chunk_overlap_chars=0,
    max_historical_incidents=200,
    max_audit_events_per_incident=100,
    max_incident_text_length=2000,
)

# Three paragraphs, chosen (and confirmed empirically) to chunk into
# exactly three predictable chunks under TEST_BOUNDS above -- one
# paragraph per chunk, no hard-split fallback involved.
NEW_TEXT = (
    "Paragraph one content here.\n\n"
    "Paragraph two content here.\n\n"
    "Paragraph three content here."
)


def _require_real_db() -> bool:
    return os.environ.get("RETRIEVAL_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    """FAILS (never skips) when RETRIEVAL_REQUIRE_REAL_DB is set --
    CI's dedicated real-database step uses this so an unavailable
    database is a loud, red failure, never a silently-green skip.
    Otherwise (the normal fast unit-test run, which never sets this
    variable) behaves exactly as before: a graceful skip."""
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture
async def real_pool():
    settings = DatabaseSettings(
        host=os.environ.get("RETRIEVAL_POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
        port=int(os.environ.get("RETRIEVAL_POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", ""),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        database=os.environ.get("POSTGRES_DB", ""),
    )
    if not (settings.user and settings.password and settings.database):
        _unavailable(
            "no real database credentials configured (POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB) -- "
            "skipping the real-database atomic-transaction regression test"
        )
    try:
        pool = await db.create_pool(settings)
    except Exception as exc:  # noqa: BLE001 -- connection failure means "skip" or "fail", decided by _unavailable
        _unavailable(f"real database not reachable at {settings.host}:{settings.port}: {exc}")

    yield pool
    await pool.close()


async def _fetch_rows(pool, source_key: str, embedding_space: str) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT chunk_index, content, content_hash
        FROM reliability.retrieval_chunks
        WHERE source_type = 'knowledge' AND source_key = $1 AND embedding_space = $2
        ORDER BY chunk_index ASC
        """,
        source_key,
        embedding_space,
    )
    return [dict(r) for r in rows]


async def test_atomic_per_source_indexing_rolls_back_entire_source_on_mid_batch_failure(real_pool, monkeypatch):
    provider = LocalLexicalEmbeddingProvider()
    source_key = f"test-atomic-rollback-{uuid.uuid4()}"
    embedding_space = provider.embedding_space

    try:
        # 1. Seed a "previously indexed state" for this source: two
        # chunks, written normally (its own, separate, already-
        # committed transaction) -- exactly what a prior successful
        # `make rag-index` run would have left behind.
        old_chunks = ["OLD content chunk zero", "OLD content chunk one"]
        old_embeddings = await provider.embed(old_chunks)
        async with real_pool.acquire() as conn, conn.transaction():
            for idx, (chunk, embedding) in enumerate(zip(old_chunks, old_embeddings, strict=True)):
                await db.upsert_chunk(
                    conn,
                    source_type="knowledge",
                    source_key=source_key,
                    chunk_index=idx,
                    title="old title",
                    content=chunk,
                    content_hash=indexer.content_hash(chunk),
                    metadata={},
                    embedding_space=embedding_space,
                    embedding=embedding,
                )

        before_rows = await _fetch_rows(real_pool, source_key, embedding_space)
        assert [r["content"] for r in before_rows] == old_chunks

        # 2. Re-index this exact source with THREE new chunks, but
        # inject a failure after the FIRST chunk write succeeds --
        # simulating a crashed connection / constraint violation / any
        # failure partway through a real re-index.
        real_upsert_chunk = db.upsert_chunk
        call_count = {"n": 0}

        async def _failing_upsert_chunk(conn, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("injected failure after one chunk write (test)")
            return await real_upsert_chunk(conn, **kwargs)

        monkeypatch.setattr(indexer.db, "upsert_chunk", _failing_upsert_chunk)

        with pytest.raises(RuntimeError, match="injected failure"):
            await indexer._index_one_source(
                real_pool,
                provider,
                source_type="knowledge",
                source_key=source_key,
                title="new title",
                text=NEW_TEXT,
                metadata={},
                bounds=TEST_BOUNDS,
            )

        # 3. The entire source update must have rolled back: the two
        # ORIGINAL rows survive, completely unchanged -- not the one
        # new chunk that "succeeded" before the injected failure, not
        # a partial mix, and the stale-chunk DELETE (which never even
        # ran, since the loop failed first) never touched anything
        # either.
        after_rows = await _fetch_rows(real_pool, source_key, embedding_space)
        assert after_rows == before_rows, (
            f"source's previously-indexed state was not preserved after a mid-batch failure: "
            f"before={before_rows} after={after_rows}"
        )
    finally:
        await real_pool.execute(
            "DELETE FROM reliability.retrieval_chunks WHERE source_type = 'knowledge' AND source_key = $1",
            source_key,
        )


async def test_atomic_per_source_indexing_succeeds_end_to_end_without_injected_failure(real_pool):
    """Sanity companion to the rollback test above: the SAME real
    transaction path commits normally and produces exactly the
    expected rows when nothing fails."""
    provider = LocalLexicalEmbeddingProvider()
    source_key = f"test-atomic-success-{uuid.uuid4()}"
    embedding_space = provider.embedding_space

    try:
        chunk_count = await indexer._index_one_source(
            real_pool,
            provider,
            source_type="knowledge",
            source_key=source_key,
            title="new title",
            text=NEW_TEXT,
            metadata={},
            bounds=TEST_BOUNDS,
        )
        assert chunk_count == 3
        rows = await _fetch_rows(real_pool, source_key, embedding_space)
        assert len(rows) == 3
        assert [r["chunk_index"] for r in rows] == [0, 1, 2]
    finally:
        await real_pool.execute(
            "DELETE FROM reliability.retrieval_chunks WHERE source_type = 'knowledge' AND source_key = $1",
            source_key,
        )
