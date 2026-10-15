-- Phase 6: durable retrieval index (RAG) for retrieval-service.
--
-- NEVER modifies V1__create_incident_schema.sql,
-- V2__add_occurrence_watermark.sql, V3__create_incident_audit.sql, or
-- V4__harden_incident_audit.sql -- all four are already applied to the
-- real local development database (confirmed via `flyway info` before
-- this migration was written), and editing any of them would
-- invalidate Flyway's recorded checksum for it. This is purely
-- additive DDL: one new extension and one new table in the SAME
-- "reliability" schema those migrations already own (never "public").
--
-- Ownership: this table is written to ONLY by retrieval-service's own
-- explicit indexer (python -m retrieval_service.indexer / `make
-- rag-index`) -- never by control-plane, never by investigator-service
-- (which holds no PostgreSQL credentials at all, Phase 5), and never
-- as a side effect of a search request (retrieval-service's HTTP API
-- is read-only -- see services/retrieval-service's own read-only
-- guarantee tests). control-plane's reliability.incidents and
-- reliability.incident_events are never written to by anything in
-- this migration or by anything that reads from the table it creates.

CREATE EXTENSION IF NOT EXISTS vector;

-- Allowed source types (Phase 6 scope only -- see
-- docs/architecture/phase-6-rag-retrieval.md for why no
-- investigation-history/approval/remediation/LangGraph-state table is
-- introduced here; those are later phases):
--   knowledge            - a chunk of source-controlled operational
--                          knowledge (knowledge/runbooks/*.md)
--   historical_incident  - a chunk of a real incident's bounded,
--                          sanitized textual representation, built
--                          from control-plane's existing GET APIs
--                          (never a direct reliability.incidents read)
CREATE TABLE reliability.retrieval_chunks (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    source_type     TEXT        NOT NULL
                                 CHECK (source_type IN ('knowledge', 'historical_incident')),

    -- A stable, deterministic identifier for the SOURCE this chunk
    -- came from -- a relative knowledge-file path (e.g.
    -- "runbooks/checkout-server-errors.md") for source_type='knowledge',
    -- or the incident's own UUID (as text) for
    -- source_type='historical_incident'. Never a filesystem path
    -- outside the explicitly allowlisted knowledge root -- enforced in
    -- application code (indexer.py), not here; this column only
    -- records whatever key the indexer decided on.
    source_key      TEXT        NOT NULL CHECK (btrim(source_key) <> ''),

    -- Stable ordering of chunks within one source_key, starting at 0.
    -- Deterministic chunking (retrieval_service/chunking.py) always
    -- reproduces the same chunk_index for the same input, which is
    -- exactly what makes the uniqueness constraint below idempotent.
    chunk_index     INTEGER     NOT NULL CHECK (chunk_index >= 0),

    title           TEXT        NOT NULL,
    content         TEXT        NOT NULL CHECK (btrim(content) <> ''),

    -- SHA-256 hex digest of `content` (64 lowercase hex chars) --
    -- lets re-indexing detect "this exact chunk is unchanged" without
    -- comparing the full text, and lets a search response disclose a
    -- stable content fingerprint without echoing the whole chunk back.
    content_hash    TEXT        NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),

    -- Allowlisted, structured provenance (e.g. incident severity/
    -- status for a historical_incident chunk, or a runbook's covered
    -- alert name for a knowledge chunk) -- never free-text, never a
    -- secret; application-enforced, same convention as
    -- reliability.incident_events.metadata in V3.
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
                                 CHECK (jsonb_typeof(metadata) = 'object'),

    -- Phase 6 §4's embedding-space isolation requirement: vectors from
    -- an incompatible provider/model/dimension must never be compared
    -- against each other. "<provider>:<model>:<dimension>", e.g.
    -- "local-lexical:hashing-v1:1536" or "openai:text-embedding-3-small:1536".
    -- A real cosine-distance search always filters on this column
    -- first (see retrieval_service/search.py) -- never relies on
    -- vector dimension alone to detect a mismatch.
    embedding_space TEXT        NOT NULL CHECK (btrim(embedding_space) <> ''),

    -- One fixed dimension across every provider/space this schema
    -- supports (Phase 6 §3/§4) -- chosen to match OpenAI's
    -- text-embedding-3-small, and the deterministic local provider is
    -- built to the same fixed size so both spaces can coexist in this
    -- one column without ever being compared to each other (enforced
    -- by the embedding_space filter above, not by this column type).
    embedding       vector(1536) NOT NULL,

    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Idempotent indexing (Phase 6 §6/§7): re-indexing an unchanged
    -- source converges to the SAME row (an UPSERT keyed on this exact
    -- tuple, including embedding_space -- re-indexing under a
    -- different embedding space intentionally creates a parallel set
    -- of rows rather than colliding with an incompatible one), never a
    -- duplicate.
    CONSTRAINT retrieval_chunks_source_chunk_space_uniq
        UNIQUE (source_type, source_key, chunk_index, embedding_space)
);

-- updated_at bookkeeping only, same pattern as
-- reliability.set_updated_at() from V1 (that trigger function is
-- scoped to reliability.incidents specifically, so a parallel,
-- identically-named-in-intent function is defined here rather than
-- reusing it across tables with different column sets).
CREATE FUNCTION reliability.set_retrieval_chunks_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER retrieval_chunks_set_updated_at
    BEFORE UPDATE ON reliability.retrieval_chunks
    FOR EACH ROW
    EXECUTE FUNCTION reliability.set_retrieval_chunks_updated_at();

-- Supporting indexes for the query patterns retrieval-service actually
-- needs: a source-type/source-key lookup (used by the indexer's own
-- "which chunks already exist for this source" / stale-chunk-cleanup
-- queries) and a per-embedding-space vector similarity search.
CREATE INDEX retrieval_chunks_source_idx
    ON reliability.retrieval_chunks (source_type, source_key);

-- Cosine-distance HNSW index (pgvector, Phase 6 §3's "appropriate
-- pgvector index where supported"), scoped per embedding_space via a
-- plain composite btree+vector arrangement is not how pgvector indexes
-- work -- instead, every search query filters `embedding_space = $1`
-- first (a cheap equality predicate backed by the index below) and
-- orders by `embedding <=> $2` (cosine distance, backed by the HNSW
-- index), exactly matching this corpus's expected scale (small,
-- curated knowledge base + this platform's own real incidents, not a
-- web-scale corpus) -- default HNSW build parameters (m=16,
-- ef_construction=64) are left unchanged, since nothing about this
-- corpus's size justifies tuning them.
CREATE INDEX retrieval_chunks_embedding_space_idx
    ON reliability.retrieval_chunks (embedding_space);

CREATE INDEX retrieval_chunks_embedding_hnsw_idx
    ON reliability.retrieval_chunks
    USING hnsw (embedding vector_cosine_ops);
