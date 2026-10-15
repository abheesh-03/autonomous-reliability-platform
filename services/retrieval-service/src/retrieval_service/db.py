"""This service's ONLY database access: a narrow asyncpg pool scoped
to exactly one table, reliability.retrieval_chunks (Phase 6 §2/§10).
Every query below is schema-qualified and parameterized -- never
string-built from caller input (Phase 6 §9: "no arbitrary SQL/filter
expression from the caller"). No other table in the "reliability"
schema is ever read or written here.

The `vector` type was installed into the "reliability" schema by
V5__create_retrieval_index.sql (not "public" -- confirmed empirically
against the real database: `CREATE EXTENSION vector` resolves into
whichever schema the migration tool's search_path/default schema
points at, which for this repository's Flyway configuration is
"reliability"). Every vector literal is therefore bound as plain TEXT
and cast with the fully schema-qualified `::reliability.vector(1536)`
in SQL text -- this works regardless of the CONNECTING client's own
search_path (confirmed empirically too), so this module never needs
to `SET search_path` itself.
"""

import json
from dataclasses import dataclass

import asyncpg

from retrieval_service.config import EMBEDDING_DIMENSION, DatabaseSettings

_VECTOR_CAST = f"reliability.vector({EMBEDDING_DIMENSION})"


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in embedding) + "]"


@dataclass(frozen=True)
class RetrievalChunkRow:
    id: int
    source_type: str
    source_key: str
    chunk_index: int
    title: str
    content: str
    content_hash: str
    metadata: dict
    embedding_space: str
    distance: float


async def create_pool(settings: DatabaseSettings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        min_size=1,
        max_size=5,
        # The `vector` extension (and its operators, e.g. `<=>`) was
        # installed into the "reliability" schema, not "public" --
        # confirmed empirically against the real database. The
        # `::reliability.vector(1536)` type casts below resolve
        # regardless of search_path, but pgvector's DISTANCE OPERATORS
        # (`<=>`) are resolved by PostgreSQL's operator lookup, which
        # IS governed by search_path and cannot be schema-qualified
        # inline the same way a type cast can without the more verbose
        # `OPERATOR(reliability.<=>)` syntax -- setting search_path
        # once per connection here is simpler and covers both.
        server_settings={"search_path": "reliability,public"},
    )


async def upsert_chunk(
    conn: asyncpg.Pool | asyncpg.Connection,
    *,
    source_type: str,
    source_key: str,
    chunk_index: int,
    title: str,
    content: str,
    content_hash: str,
    metadata: dict,
    embedding_space: str,
    embedding: list[float],
) -> None:
    """Idempotent by construction: V5's uniqueness constraint
    (source_type, source_key, chunk_index, embedding_space) is this
    statement's own ON CONFLICT target, so re-indexing unchanged
    content converges onto the SAME row rather than duplicating it
    (Phase 6 §6/§8).

    `conn` may be a `Pool` (each call gets its own implicit
    connection/transaction) or a `Connection` already inside a
    transaction the caller controls -- `indexer.py`'s
    `_index_one_source` passes a single acquired `Connection` so every
    chunk upsert for one source shares the same atomic transaction
    (Phase 6 correction round: "atomic per-source indexing")."""
    await conn.execute(
        f"""
        INSERT INTO reliability.retrieval_chunks
            (source_type, source_key, chunk_index, title, content, content_hash, metadata, embedding_space, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::{_VECTOR_CAST})
        ON CONFLICT (source_type, source_key, chunk_index, embedding_space)
        DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            content_hash = EXCLUDED.content_hash,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding
        WHERE
            reliability.retrieval_chunks.content_hash IS DISTINCT FROM EXCLUDED.content_hash
            OR reliability.retrieval_chunks.title IS DISTINCT FROM EXCLUDED.title
            OR reliability.retrieval_chunks.metadata IS DISTINCT FROM EXCLUDED.metadata
        """,
        source_type,
        source_key,
        chunk_index,
        title,
        content,
        content_hash,
        json.dumps(metadata, sort_keys=True),
        embedding_space,
        _vector_literal(embedding),
    )


async def delete_chunks_beyond(
    conn: asyncpg.Pool | asyncpg.Connection,
    *,
    source_type: str,
    source_key: str,
    embedding_space: str,
    keep_below_chunk_index: int,
) -> int:
    """Stale-chunk cleanup (Phase 6 §6): deletes chunks for this exact
    source whose chunk_index is now >= the current (re-chunked)
    document's own chunk count -- e.g. a document that shrank from 5
    chunks to 3 leaves chunk_index 3 and 4 behind as stale rows unless
    this runs. Never touches a DIFFERENT source_key or
    embedding_space.

    `conn` -- see `upsert_chunk`'s own docstring: `indexer.py` passes
    the same acquired `Connection` here as it used for that source's
    upserts, so this delete is part of the SAME atomic transaction."""
    result = await conn.execute(
        """
        DELETE FROM reliability.retrieval_chunks
        WHERE source_type = $1 AND source_key = $2 AND embedding_space = $3 AND chunk_index >= $4
        """,
        source_type,
        source_key,
        embedding_space,
        keep_below_chunk_index,
    )
    return _rowcount(result)


async def delete_sources_not_in(
    pool: asyncpg.Pool, *, source_type: str, embedding_space: str, keep_source_keys: list[str]
) -> int:
    """Deletes every chunk for `source_type`/`embedding_space` whose
    source_key is no longer among the current corpus (e.g. a runbook
    file removed from knowledge/runbooks/) -- never touches a
    different source_type or embedding_space, and a currently-empty
    `keep_source_keys` (nothing collected this run) deletes nothing by
    design, never the entire corpus, to avoid a transient collection
    failure wiping out a previously-good index."""
    if not keep_source_keys:
        return 0
    result = await pool.execute(
        """
        DELETE FROM reliability.retrieval_chunks
        WHERE source_type = $1 AND embedding_space = $2 AND NOT (source_key = ANY($3::text[]))
        """,
        source_type,
        embedding_space,
        keep_source_keys,
    )
    return _rowcount(result)


async def count_chunks(pool: asyncpg.Pool, *, source_type: str | None = None) -> int:
    if source_type is None:
        return await pool.fetchval("SELECT count(*) FROM reliability.retrieval_chunks")
    return await pool.fetchval(
        "SELECT count(*) FROM reliability.retrieval_chunks WHERE source_type = $1", source_type
    )


async def search_chunks(
    pool: asyncpg.Pool,
    *,
    source_type: str,
    embedding_space: str,
    query_embedding: list[float],
    limit: int,
    exclude_source_key: str | None = None,
) -> list[RetrievalChunkRow]:
    """Read-only cosine-distance search, scoped to exactly one
    source_type and one embedding_space (Phase 6 §4/§9) -- an
    incompatible embedding space is never compared against, by
    construction (the WHERE clause, not vector dimension alone).
    Deterministic tie-breaking: ties in distance are broken by `id
    ASC` (Phase 6 §17's "deterministic tie-breaking" requirement).
    """
    if exclude_source_key is not None:
        rows = await pool.fetch(
            f"""
            SELECT id, source_type, source_key, chunk_index, title, content, content_hash, metadata,
                   embedding_space, embedding <=> $1::{_VECTOR_CAST} AS distance
            FROM reliability.retrieval_chunks
            WHERE source_type = $2 AND embedding_space = $3 AND source_key <> $4
            ORDER BY embedding <=> $1::{_VECTOR_CAST} ASC, id ASC
            LIMIT $5
            """,
            _vector_literal(query_embedding),
            source_type,
            embedding_space,
            exclude_source_key,
            limit,
        )
    else:
        rows = await pool.fetch(
            f"""
            SELECT id, source_type, source_key, chunk_index, title, content, content_hash, metadata,
                   embedding_space, embedding <=> $1::{_VECTOR_CAST} AS distance
            FROM reliability.retrieval_chunks
            WHERE source_type = $2 AND embedding_space = $3
            ORDER BY embedding <=> $1::{_VECTOR_CAST} ASC, id ASC
            LIMIT $4
            """,
            _vector_literal(query_embedding),
            source_type,
            embedding_space,
            limit,
        )

    return [
        RetrievalChunkRow(
            id=r["id"],
            source_type=r["source_type"],
            source_key=r["source_key"],
            chunk_index=r["chunk_index"],
            title=r["title"],
            content=r["content"],
            content_hash=r["content_hash"],
            metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else dict(r["metadata"]),
            embedding_space=r["embedding_space"],
            distance=float(r["distance"]),
        )
        for r in rows
    ]


def _rowcount(result: str) -> int:
    # asyncpg's Pool.execute returns a command-tag string like
    # "DELETE 3" -- parsed defensively rather than assumed.
    parts = result.split()
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0
