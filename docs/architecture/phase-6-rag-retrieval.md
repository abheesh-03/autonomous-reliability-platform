# Phase 6: RAG and historical incident retrieval

Phase 6 **extends** Phase 5's read-only AI incident investigator. It
does not replace, weaken, or reopen anything Phase 5 already closed
out — every Phase 5 guarantee (strictly read-only, hard prompt
character ceiling, fabricated-citation rejection, deterministic
validated-only summary, no PostgreSQL credentials for
investigator-service, no write-capable control-plane token) remains
true after this phase, and is re-verified by `scripts/verify-rag.sh`
alongside the new RAG-specific checks.

Before investigator-service calls the LLM, it can now retrieve two
kinds of background context:

1. source-controlled operational knowledge (`knowledge/runbooks/*.md`); and
2. real historical incidents, read through control-plane's existing
   `GET` APIs.

This is genuine retrieval-augmented generation — a real vector index,
real embeddings, real cosine-distance search — but it remains a
**human-invoked, single-pass investigator**. There is no agent loop,
no iterative retrieval, no tool-calling by the LLM, and the LLM never
constructs a retrieval query or any kind of database query itself.
LangGraph and autonomous/iterative investigation remain Phase 7.

## Architecture

```
                    +---------------------+
                    | control-plane GETs  |
                    +----------+----------+
                               |
                        indexing only
                               |
                               v
source-controlled      +--------------------+
knowledge -----------> | retrieval-service  |
                       |                    |
                       | PostgreSQL/pgvector|
                       +---------+----------+
                                 ^
                                 |
                           read-only search
                                 |
                       +---------+----------+
                       | investigator       |
                       | service            |
                       +---------+----------+
                                 |
                           bounded RAG context
                                 |
                                 v
                                LLM
```

### Why retrieval-service is a separate deployable

- **Credential boundary**: retrieval-service is the only new
  application in this phase that holds PostgreSQL credentials. It
  owns exactly one table, `reliability.retrieval_chunks`.
  investigator-service continues to hold **zero** PostgreSQL
  credentials and **neither** of control-plane's write-capable Bearer
  tokens — unchanged from Phase 5. Merging retrieval into
  investigator-service would have handed it a database credential for
  the first time; merging it into control-plane would have put a
  vector index and an embedding-provider credential inside the one
  service every other application depends on. Keeping it separate
  means a retrieval-service outage, a pgvector problem, or an
  embedding-provider failure degrades only RAG context — it never
  touches control-plane's own read/write paths or investigator-service's
  Phase 5 evidence pipeline (see "Graceful degradation" below).
- **Write boundary**: retrieval-service's HTTP API
  (`POST /api/v1/retrieval/search`) is **search-only** — it never
  writes. The only code allowed to write
  `reliability.retrieval_chunks` is its own explicit, offline indexer
  (`python -m retrieval_service.indexer` / `make rag-index`), run as a
  deliberate developer/CI operation, never as a side effect of an
  HTTP request. This is checked structurally (AST-level), not just by
  convention — see `services/retrieval-service/tests/test_read_only_guarantees.py`.
- **No generic agent**: retrieval-service has no knowledge of
  incidents, investigations, or the LLM at all — it is a narrow
  search index. investigator-service decides what to search for and
  how to use the results; retrieval-service never initiates anything.

## PostgreSQL / pgvector image

The `postgres` Compose service was switched from the official
`postgres:18` image to **`pgvector/pgvector:pg18`** — a
pgvector-maintained image built from PostgreSQL 18 that bundles the
pgvector extension (confirmed: `vector.control`'s `default_version`
is `0.8.7`).

This is **not a downgrade**: both images reported the identical
PostgreSQL version (`18.6`) at the time this phase was implemented,
and — confirmed empirically before adopting the image — both images
use the exact same `PGDATA=/var/lib/postgresql/18/docker` path and the
exact same `/var/lib/postgresql` volume mount point as the official
image. The only differences are the base OS packaging and the bundled
pgvector extension.

**Data safety during the image change** (proven locally before this
phase was considered complete, against this repository's own real,
accumulated `postgres_data` volume — not a fresh database):

1. Captured `count(*)` and a `md5(string_agg(...))` content
   fingerprint of every row in `reliability.incidents` and
   `reliability.incident_events` under the OLD image
   (`postgres:18`): 79 incidents, 153 events, fingerprints
   `e1c4c5ed...` / `fa8b3a93...`.
2. `docker compose stop postgres` (never `down -v`, never a volume
   deletion).
3. Swapped the image to `pgvector/pgvector:pg18` in
   `docker-compose.yml`.
4. `docker compose up -d postgres` against the SAME, unmodified
   `postgres_data` volume. Container started healthy on the first
   attempt.
5. Re-ran the exact same counts and fingerprints: 79 incidents, 153
   events, **identical** fingerprints. Byte-for-byte preserved.
6. One real, expected artifact of the base-OS change: PostgreSQL
   logged a collation-version mismatch warning (`2.41` vs. `2.36` —
   the two images use different Debian base images with different
   glibc collation data). This is a standard, well-documented
   PostgreSQL maintenance step after any base-OS/glibc change (the
   same thing a normal host OS upgrade would require) — resolved with
   `ALTER DATABASE ... REFRESH COLLATION VERSION`, which touches only
   catalog metadata, never row data. Re-confirmed 79 incidents present
   immediately after.
7. `flyway info` against the swapped-image database confirmed V1–V4
   were already applied and untouched (`Schema version: 4`) before
   V5 was ever written.

No `docker compose down -v` was run at any point. No data was
manually recreated to hide a problem — the one real finding (the
collation warning) is reported here, not hidden.

## Migration V5

`database/migrations/V5__create_retrieval_index.sql` — purely
additive; V1–V4 are never modified. Creates the `vector` extension
and one new table in the existing `reliability` schema (never
`public`):

```
reliability.retrieval_chunks (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type     TEXT NOT NULL CHECK (source_type IN ('knowledge', 'historical_incident')),
    source_key      TEXT NOT NULL CHECK (btrim(source_key) <> ''),
    chunk_index     INTEGER NOT NULL CHECK (chunk_index >= 0),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL CHECK (btrim(content) <> ''),
    content_hash    TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    embedding_space TEXT NOT NULL CHECK (btrim(embedding_space) <> ''),
    embedding       vector(1536) NOT NULL,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT retrieval_chunks_source_chunk_space_uniq
        UNIQUE (source_type, source_key, chunk_index, embedding_space)
)
```

Indexes: `(source_type, source_key)` btree (the indexer's own
stale-chunk-cleanup lookups), `(embedding_space)` btree, and an HNSW
index (`USING hnsw (embedding vector_cosine_ops)`, default build
parameters) for cosine-distance search.

A real empirical finding during implementation: `CREATE EXTENSION
vector` installs the `vector` type and its operators (`<=>`) into
whichever schema the connecting client's `search_path` resolves to —
for this repository's Flyway configuration (`FLYWAY_SCHEMAS:
reliability`), that is the `reliability` schema, not `public`
(confirmed via `\dx`). retrieval-service's own database pool
(`db.py`) sets `search_path=reliability,public` on every connection so
both the `vector` type cast and the `<=>` operator resolve correctly
regardless of which schema a plain `psql` session would otherwise
default to.

No investigation-history, approval, remediation, or LangGraph-state
table is introduced — those are later phases, out of scope here.

## Embedding providers and embedding-space isolation

`EmbeddingProvider` is a small Protocol (`name`, `model`, `dimension`,
`embedding_space`, `async embed(texts) -> vectors`) with two
implementations:

- **`LocalLexicalEmbeddingProvider`** (default, `provider="local"`):
  a **deterministic LEXICAL feature-hashing embedding** — tokenizes
  text, hashes each token with `hashlib.sha256` (never Python's
  randomized builtin `hash()`) into one of 1536 buckets with a
  sign bit from a different byte of the same digest, accumulates, and
  L2-normalizes. The exact same text always produces the exact same
  vector, in any process, on any machine, forever — confirmed by
  spawning a **separate** interpreter process and comparing output
  byte-for-byte. This is explicitly **not** a neural or semantic
  model: it has no notion of word meaning, synonyms, or context, only
  shared tokens. It needs no credential and makes no network call —
  this is what normal development, CI, and `scripts/verify-rag.sh`
  all use.
- **`OpenAIEmbeddingProvider`** (`provider="openai"`): a real,
  configurable embedding model (default `text-embedding-3-small`),
  via `RETRIEVAL_EMBEDDING_API_KEY` — a credential **distinct** from
  investigator-service's `INVESTIGATOR_LLM_API_KEY`. Every call
  passes `dimensions=1536` explicitly (OpenAI's `text-embedding-3-*`
  models support this truncation parameter), so the real provider's
  vectors are always the same fixed size as the schema's own
  `vector(1536)` column and the local provider's own output. Selecting
  `provider="openai"` without a configured key is an explicit startup
  error (`EmbeddingProviderNotConfiguredError`) — never a silent
  fallback to the local provider for the indexer. Any provider call
  failure is wrapped in `EmbeddingProviderError` carrying only the
  exception's type name, never its raw message (the same reasoning as
  investigator-service's own `ProviderError`: an upstream SDK's
  error-formatting behavior is not guaranteed to never include a
  credential).

**Embedding-space isolation**: every row records
`embedding_space = "<provider>:<model>:<dimension>"` (e.g.
`"local-lexical:hashing-v1:1536"` or
`"openai:text-embedding-3-small:1536"`). Every search query filters on
this column FIRST, before the cosine-distance ORDER BY — vectors from
an incompatible provider/model are structurally excluded from ever
being compared, not merely "unlikely to match" because they share a
dimension.

**Real OpenAI embedding smoke-test status**: NOT smoke-tested with a
real credential in this implementation — no `RETRIEVAL_EMBEDDING_API_KEY`
was available in this environment. This mirrors Phase 5's own, already
-documented limitation for `INVESTIGATOR_LLM_API_KEY`. The missing-key
explicit-failure path (`EmbeddingProviderNotConfiguredError`, never a
silent local-provider fallback for the indexer) and the error-secrecy
path (`EmbeddingProviderError` never exposing a raw SDK message) are
both unit-tested against a controlled failure double instead.

## Source-controlled knowledge and chunking

`knowledge/runbooks/*.md` — four runbooks, one per real alert rule
this repository's own `observability/prometheus/rules/alerts.yml`
already defines: `CheckoutServerErrors`, `CheckoutHighLatency`,
`TelemetryPipelineUnavailable`, `CollectorRefusingTelemetry`. Each
explains what the alert means (the real PromQL expression and `for:`
duration it fires from), what evidence actually distinguishes
candidate causes (real Prometheus metric names, real Loki/Tempo
limitations already documented elsewhere in this repository, real
checkout-service call order), and only READ-ONLY investigation
guidance — no invented infrastructure, SLAs, Kubernetes commands, or
tooling that doesn't exist in this repository.

`chunking.py`'s `chunk_text(text, max_chars, overlap_chars)` is
deterministic: stable ordering (never dependent on filesystem/wall-
clock state), a Markdown-heading-aware paragraph accumulator (a `#`
line always starts a new accumulation unit when one is already in
progress), bounded chunk size, bounded overlap, and a hard-split
fallback for any single block that alone exceeds `max_chars`. A
`sha256` `content_hash` is computed per chunk.

`knowledge.py`'s `load_knowledge_documents(knowledge_root)` reads
`*.md` files recursively from exactly ONE allowlisted root — set only
by `RETRIEVAL_KNOWLEDGE_ROOT` (an operator/deployment configuration
value, mounted read-only into the Compose container at `/knowledge`),
never a request parameter. It defends against a symlink inside the
root that resolves outside it (the resolved real path must still be a
descendant of the root) and returns documents in deterministic,
sorted-by-relative-path order.

## Historical incident indexing

`historical.py`'s `build_historical_incident_text` builds a bounded,
redacted textual representation from real control-plane fields only
(id, title, description, severity, source, status, first/last-seen,
resolved timestamp, and the full audit timeline) — read exclusively
through control-plane's existing `GET /api/v1/incidents`,
`GET /api/v1/incidents/{id}`, and `GET /api/v1/incidents/{id}/events`
(all fully paginated by `clients/control_plane.py`), never a direct
`reliability.incidents` read. An incident with zero audit events
renders an explicit `"(no audit events recorded for this incident)"`
line — never an invented timeline. `redaction.py` (kept consistent by
hand with investigator-service's own module, since these are separate
deployables) applies the same best-effort credential-shaped-pattern
redaction before this text is ever chunked or embedded.

## Indexing lifecycle and idempotency

`python -m retrieval_service.indexer` (`make rag-index`) is the ONLY
code path allowed to write `reliability.retrieval_chunks`. It:

1. indexes every knowledge document under the allowlisted root;
2. reads and indexes every CURRENT historical incident through
   control-plane's GET APIs (bounded by
   `RETRIEVAL_MAX_HISTORICAL_INCIDENTS`);
3. reports counts only (document/chunk/incident counts, the active
   embedding space) — never a credential;
4. is idempotent: `db.upsert_chunk` targets the exact uniqueness
   constraint V5 defines (`source_type, source_key, chunk_index,
   embedding_space`) with an `ON CONFLICT ... DO UPDATE` that only
   touches a row when its content/title/metadata actually changed;
   `db.delete_chunks_beyond` removes stale chunks when a document
   shrinks; `db.delete_sources_not_in` removes chunks for a knowledge
   file that was deleted entirely. Historical incidents deliberately
   get NO full-corpus "delete sources not in" cleanup — incidents are
   never deleted in this platform, and `RETRIEVAL_MAX_HISTORICAL_INCIDENTS`
   is a per-run budget, not a claim that incidents outside it no
   longer exist; treating a budget-truncated page as "these are gone"
   would delete genuinely valid retrieval data.

Proven against the real stack (`scripts/verify-rag.sh`): running the
indexer twice in a row with unchanged sources produces the exact same
total chunk count both times.

## Retrieval API

`POST /api/v1/retrieval/search` (read-only; the query is never
persisted):

```json
{
  "query": "...",
  "exclude_incident_id": "<optional UUID>",
  "knowledge_limit": 3,
  "historical_incident_limit": 3
}
```

Validated by Pydantic (`extra="forbid"` — no arbitrary filter
expression from the caller): query length (1–10,000 chars, further
bounded server-side by `RETRIEVAL_MAX_QUERY_LENGTH`), both limits
(0–50, further bounded by `RETRIEVAL_MAX_RESULT_LIMIT`),
`exclude_incident_id` as a real UUID. No per-request provider
selection — the active embedding provider is a startup-time
configuration choice only.

Response: separate `knowledge`/`historical_incidents` groups, each
item carrying `id` (the durable `retrieval_chunks.id`), `source_type`,
`source_key`, `title`, a bounded `excerpt`, `similarity` (documented
explicitly as a RETRIEVAL RANKING score — `1 - cosine distance` —
**never** a probability and **never** an LLM confidence value),
`metadata`, and `embedding_space`. When `exclude_incident_id` is
given, every query is parameterized with `source_key <> $N` — that
incident can never appear in its own historical results (verified
against the real database by `scripts/verify-rag.sh`).

## Investigator-service RAG integration

`clients/retrieval.py`'s `RetrievalClient` is a plain, read-only HTTP
client (same trust boundary as the Prometheus/Loki/Tempo clients) —
any failure becomes `RetrievalUnavailableError`.
`investigator.py`'s `_build_retrieval_query` builds the query in
APPLICATION CODE ONLY, from bounded, redacted current-incident fields
(title, description, source, severity) — never from unbounded raw
logs, and the LLM is never involved in constructing it.

Flow (`Investigator.investigate`): collect Phase 5 evidence exactly as
before → build the retrieval query → call retrieval-service → degrade
to `retrieval_context.outcome="unavailable"` on any failure (never
failing the whole investigation) → build the prompt (evidence AND
retrieved context together) → one LLM call → validate E AND K/H
citations → return the report.

## E vs. K vs. H citation semantics

This distinction is structural, not just documentation:

- **`E<n>`** — current-incident evidence (Phase 5, unchanged).
- **`K<n>`** — retrieved knowledge context.
- **`H<n>`** — retrieved historical-incident context.

`Observation` has only an `evidence_ids` field — there is no field for
it to put a K/H id into even if the model tried; any K/H-shaped string
placed there is validated against the E-only shown-id set and
rejected as fabricated, exactly like any other unknown id.

`Hypothesis` gained `supporting_context_ids`/`conflicting_context_ids`
alongside its existing `supporting_evidence_ids`/
`conflicting_evidence_ids`. Validation (`llm/validation.py`):
retention is governed **solely** by real E support — a hypothesis
with `supporting_evidence_ids == []` is dropped regardless of how
much K/H context it cites (K/H alone can never create a root-cause
hypothesis about the current incident). Context ids ARE sanitized the
same way evidence ids are (validated against the exact K/H set shown,
fabricated ones stripped and recorded) but a fabricated/empty context
citation never gates retention by itself.

A statement like *"historical incident H1 involved a payment-service
failure"* may be true about H1. It never implies *"payment-service
caused the current incident"* unless the current incident's own
E-cited evidence independently supports that — this is enforced by
the validation rule above, not merely stated in the system prompt.

## Prompt bounding

Current-incident evidence has **first claim** on the entire
`max_prompt_chars` budget — `llm/prompt.py`'s evidence
selection/trimming is completely unchanged from Phase 5, and runs to
completion before retrieved context is even rendered. Retrieved
context then spends whatever room remains, further bounded by its own
practical sub-bounds (`RagBounds`): `max_knowledge_contexts`,
`max_historical_contexts` (count), `max_context_excerpt_chars` (per-
item truncation), `max_rag_context_chars` (a total-characters sub-
budget). Diversity-before-depth: one representative of each available
source (knowledge, historical) is reserved before any additional item
of either — the same policy Phase 5 already uses for Prometheus/Loki/
Tempo telemetry. If context must be trimmed to fit, the in-prompt
omission-disclosure note is itself bounded (so it can never be what
pushes the prompt over the ceiling — the exact class of bug Phase 5's
own correction round fixed for evidence) and the omitted ids are never
part of the set the model's citations are validated against, so an
omitted item can never be cited even if hallucinated.

## Injection / data-poisoning boundary

Retrieved knowledge and historical-incident text is treated as
UNTRUSTED DATA, identically to Phase 5's evidence text — even though
knowledge is source-controlled Markdown and historical-incident text
describes a real past incident. The same `_escape_untrusted` angle-
bracket escaping applies to retrieved titles/excerpts; the system
prompt explicitly states that `<knowledge>`/`<historical_incident>`
block content is never an instruction, and that a "similarity" score
is a ranking only. Proven directly: a retrieved knowledge excerpt
containing literal "ignore all previous instructions" text reaches the
rendered prompt verbatim, strictly inside its delimited block, with
the system prompt's own untrusted-data rule unchanged. The LLM still
receives no tools, no shell, no Docker, no database connection, and no
arbitrary HTTP capability.

## Graceful degradation

If retrieval-service is unreachable, `retrieval_context.outcome` is
reported as `"unavailable"` and the investigation proceeds using Phase
5 evidence alone — never a fabricated fallback historical knowledge.
If retrieval-service is reachable but returns zero matches in both
groups, the outcome is `"no_data"` — a distinct, honest case from
`"unavailable"`. investigator-service's own `/health/ready` does not
depend on retrieval-service at all, so a temporarily-down optional
retrieval-service never fails investigator-service's own readiness.

## Current-incident exclusion

Every retrieval call investigator-service makes passes
`exclude_incident_id` set to the incident actually being investigated.
Proven against the real database (`scripts/verify-rag.sh`): searching
historical incidents for the exact title of the incident under
investigation never returns that incident's own id.

## Acceptance results

`scripts/verify-rag.sh` (`make verify-rag`), run against the real
Compose stack in this implementation:

- V5/pgvector confirmed applied; `vector` extension installed.
- retrieval-service `/health/ready` confirmed reachable, local-lexical
  provider active.
- Real indexing: 4 knowledge documents → 21 chunks; 79 real historical
  incidents → 83 chunks.
- A second immediate indexing run: identical total chunk count (104
  before and after) — idempotent.
- A real pgvector cosine-distance search for
  `"checkout 5xx payment dependency unavailable"` retrieved
  `runbooks/checkout-server-errors.md` within the top 5 knowledge
  results.
- A real historical-incident search excluding the current incident
  returned real results, never including the excluded incident
  itself.
- A real, RAG-integrated investigation (deterministic stub LLM
  provider) returned `retrieval_context.outcome="ok"` with 3 real
  knowledge items and 3 real historical items, every one carrying
  real provenance (`source_key`, `similarity`, `embedding_space`).
- Every E/K/H citation in the real response was independently
  re-verified against the response's own `evidence`/`retrieval_context`
  — zero fabricated citations, direct observations cited E only, and
  the (empty, in this deterministic-stub run) hypothesis list
  satisfied "at least one real E citation" vacuously-but-correctly.
- The current incident row and its complete, fully-paginated audit
  trail were confirmed byte-for-byte unchanged before vs. after the
  entire indexing/search/investigation sequence.

See the final handoff report for this phase for the literal command
output.

## Known limitations

- The deterministic local hash embedding is LEXICAL, not a neural
  semantic model — two sentences using different words for the same
  concept are not specially related by it.
- The real OpenAI embedding path (`RETRIEVAL_EMBEDDING_PROVIDER=openai`)
  has not been smoke-tested with a real credential in this
  implementation (no credential was available) — the missing-key and
  error-secrecy paths are unit-tested instead.
- The retrieval corpus is intentionally small (4 runbooks; however
  many real incidents this platform has accumulated).
- Historical-incident retrieval quality depends entirely on how many
  real incidents this platform has actually accumulated — a
  fresh/near-empty database will have little or nothing to find
  (handled honestly: `scripts/verify-rag.sh` reports this explicitly
  in standalone/local mode rather than fabricating history).
- No reranker.
- No investigation persistence (this report is computed and returned,
  never stored).
- No LangGraph, no autonomous/iterative investigation loop.
- No remediation, no human-approval workflow, no automatic action
  execution.
- No operations-console frontend.

All of the above are the same category of honestly-stated limitation
Phase 5 already established for itself — not hidden, not glossed over.
