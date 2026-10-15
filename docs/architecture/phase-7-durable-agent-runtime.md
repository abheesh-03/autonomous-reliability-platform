# Phase 7: durable LangGraph agent runtime and investigation orchestration

## 1. Purpose

Phases 5 and 6 built a read-only AI investigator that answers a single
HTTP request: given an incident, collect evidence, retrieve relevant
knowledge/history, and return one structured report. That investigation
lives and dies inside one HTTP request/response cycle — if the process
crashes mid-request, the work is gone, there is no record that it was
ever attempted, and there is no way to resume it.

Phase 7 turns that single-shot investigation into a **durable agent
run**: an execution with explicit graph state, persisted checkpoints
after every node, an inspectable execution history, and the ability to
resume exactly where it left off after a process crash or restart. It
does this by wrapping the existing, unmodified Phase 5/6 investigation
pipeline in a small LangGraph `StateGraph`, backed by a real PostgreSQL
checkpoint store.

Phase 7 is **durable read-only orchestration only**. It does not
mutate an incident, does not call any control-plane write endpoint,
does not execute remediation, and does not introduce any Phase 8
functionality (human approval, `interrupt()`, rollback, scaling,
restart-the-service tooling). See §15.

## 2. Why LangGraph now

A single HTTP request is sufficient for "ask the investigator a
question." It is not sufficient for an **agent** that needs to survive
process restarts, be inspected mid-flight, or be resumed safely after a
partial failure — durability, resumability, and inspectable history are
exactly the problems a graph execution engine with a real checkpointer
solves, rather than re-deriving ad hoc (a custom state machine plus a
hand-rolled persistence table would duplicate what LangGraph already
provides, tested, for this exact problem).

Phase 7 uses LangGraph's `StateGraph` with an async, PostgreSQL-backed
checkpoint saver (`AsyncPostgresSaver`, from `langgraph-checkpoint-postgres`).
Versions were verified by direct installation, not guessed, and are
pinned exactly in `services/agent-runtime-service/pyproject.toml`:

- `langgraph==1.2.15`
- `langgraph-checkpoint==4.3.0`
- `langgraph-checkpoint-postgres==3.2.0`
- `psycopg[binary,pool]==3.3.6`

`AsyncPostgresSaver` is psycopg3-based (confirmed by reading its real
source — an earlier assumption that it was asyncpg-based was wrong and
corrected before any application code was written). `InMemorySaver` is
used only in this service's own focused unit tests, where persistence
itself is not under test (`tests/test_graph.py`, `tests/test_api_agent_runs.py`)
— the real runtime (`main.py`) always uses `AsyncPostgresSaver`.

## 3. Why agent-runtime-service is separate

agent-runtime-service is a new, eighth backend service — not a module
added to investigator-service. Two reasons, both load-bearing:

1. **Credential boundary.** investigator-service holds zero database
   credentials today (Phase 5 §8) and zero write-capable control-plane
   tokens. Adding a LangGraph checkpoint database connection to it
   would hand it its first database credential ever, widening its
   blast radius for no investigative benefit. agent-runtime-service
   holds exactly one credential family: its own dedicated,
   least-privileged checkpoint-database role (§8) — nothing else.
2. **Separation of concerns.** investigator-service remains the single
   canonical investigation engine (unchanged API, unchanged behavior,
   unchanged Phase 5/6 guarantees — see §4's `run_investigation` node).
   agent-runtime-service owns only durability and orchestration: it
   calls investigator-service's existing `POST /api/v1/investigations`
   exactly as any other caller would, and never reimplements evidence
   collection or RAG retrieval itself.

agent-runtime-service does **not**: mutate an incident, call
control-plane's lifecycle `PATCH` endpoint, call Alertmanager's webhook
endpoint, receive `CONTROL_PLANE_WEBHOOK_TOKEN` or
`CONTROL_PLANE_LIFECYCLE_TOKEN`, execute remediation, execute shell
commands or subprocesses, access the Docker socket, or talk to
Kubernetes/AWS/GitHub. See §11 for how this is proven, not just
asserted.

## 4. Graph topology

```
START -> load_incident -> run_investigation -> evaluate_investigation -> finalize -> END
```

A small, real four-node graph — not a fabricated multi-node
architecture. Each arrow is a real LangGraph edge; two are conditional
(routing a classified failure straight to `finalize` instead of
continuing):

- **`load_incident`** — calls control-plane's existing read-only
  `GET /api/v1/incidents/{id}`. Proves the incident genuinely exists,
  captures a bounded, redacted `IncidentSnapshot` (via `text_safety.bound_and_redact`
  — see §5), and classifies failures into two kinds (correction round,
  finding #3): `IncidentNotFoundError` and `ControlPlaneOutputError`
  (a 2xx response that didn't match control-plane's own contract) are
  **terminal** — caught here, routed to `finalize` with
  `status="failed"`; `ControlPlaneUnavailableError` (control-plane
  unreachable or a non-2xx/non-404) is **transient/retryable** —
  deliberately left **uncaught**, so it propagates and the thread
  remains resumable at `load_incident` itself (§9). Never mutates
  anything.
- **`run_investigation`** — calls investigator-service's existing,
  already read-only/computational `POST /api/v1/investigations`. Does
  **not** duplicate Phase 5/6 evidence collection or RAG retrieval;
  investigator-service remains the canonical investigation engine. The
  validated `InvestigationReport` (including its Phase 6
  `retrieval_context` — real K/H provenance) is stored directly in
  durable graph state. Same terminal/transient split as `load_incident`:
  `InvestigatorOutputError` (a 2xx response that didn't match
  investigator-service's own contract — an incompatible/invalid
  upstream shape, not a temporary outage) is terminal;
  `InvestigatorUnavailableError` is transient/retryable, deliberately
  left uncaught.
- **`evaluate_investigation`** — a deterministic, non-LLM orchestration
  check (see `graph/nodes.py::classify_investigation`): classifies the
  investigation as `well_supported` (at least one hypothesis the model
  itself declared **`confidence="high"`**, backed by real evidence,
  with no missing-evidence gaps), `partial` (some signal — observations,
  or a hypothesis with declared gaps, or a `low`/`medium`-confidence
  evidence-backed hypothesis — but not meeting the `well_supported` bar),
  or `inconclusive` (no observations and no hypotheses at all). This is
  a classification over real, already-validated structured fields the
  investigation already produced — never a second AI investigator,
  never a new LLM call, and **never a claim that any root cause is
  confirmed** (renamed from `"conclusive"` — correction round, finding
  #12 — specifically because that word could be misread as implying
  confirmation; this remains orchestration metadata only and does not
  alter investigator-service's own Phase 5/6 epistemic boundary between
  a confirmed observation and an unconfirmed hypothesis).
- **`finalize`** — marks the run `completed` (or `failed`, if an
  earlier node classified a TERMINAL failure) and persists the final
  state. This checkpoint's `next` is always empty — a terminal run is
  never resumable (§9).

## 5. Graph state

An explicit `TypedDict` (`graph/state.py::AgentGraphState`), not
arbitrary Python objects:

```python
class AgentGraphState(TypedDict, total=False):
    run_id: str
    incident_id: str
    status: str                 # "running" | "completed" | "failed"
    started_at: str
    updated_at: str
    completed_at: str | None
    current_node: str
    completed_nodes: Annotated[list[str], operator.add]
    incident_snapshot: dict | None
    investigation_report: dict | None
    result_quality: str | None
    validation_notes: list[str]
    error_code: str | None
    error_detail: str | None
```

Only bounded, JSON-serializable workflow data is ever persisted.
Deliberately never persisted: API keys, Bearer tokens, database
passwords, `Authorization` headers, raw SDK exception text, HTTP
client objects, database connections, or subprocess handles —
confirmed structurally, not just by convention, in
`tests/test_graph.py` and the AST-based checks in
`tests/test_read_only_guarantees.py`. Any user/external text that does
land in persisted state (e.g. `error_detail`) is already bounded by
`RuntimeBounds.max_error_detail_chars`, the same discipline Phase 5/6
already apply to their own evidence text.

**`incident_snapshot` is bounded and redacted before it is ever
persisted** (correction round, finding #4; extended by follow-up
finding #2). control-plane's `reliability.incidents` schema imposes no
length bound on `title`/`description`/`source`/`source_fingerprint` at
all, and independent review reproduced a 5000-character title, an
unredacted `"Bearer TOPSECRET"` description, and (in the follow-up
round) a 5000+ character, `"Bearer TOPSECRET"`-prefixed
`source_fingerprint` all being persisted completely unchanged. Fixed
by `graph/nodes.py::load_incident` passing the validated
`IncidentSnapshot` through `text_safety.bound_and_redact` (a small,
locally-implemented, independently-tested equivalent of
investigator-service's own `redaction.py` pattern set and
`INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH` bound — never an import of
investigator-service's internals; these are separate deployables)
before it enters state at all — now covering all four free-text fields
(`title`, `description`, `source`, `source_fingerprint`); `id`/
`status`/`severity`/the timestamp fields are deliberately untouched,
since none of those are free text. Bounded by
`AGENT_RUNTIME_MAX_INCIDENT_TEXT_LENGTH` (default 2000, same
range/default as investigator-service's own setting) — and that bound
is now a REAL hard ceiling (follow-up finding #1: an earlier version
appended its `"...[truncated]"` suffix AFTER already slicing to the
configured maximum, so the real returned length could exceed it by the
suffix's own length — independently reproduced: `max_chars=2000`
produced a 2014-character string. `text_safety.hard_bound` now reserves
space for the suffix first, so the ENTIRE returned string, including
any suffix, never exceeds the configured maximum; `graph/nodes.py::_safe_detail`
was fixed identically, by delegating to the same helper). Stated
honestly, same as investigator-service's own redaction: best-effort
defense in depth against common accidental-leak shapes, not a
guarantee. Proven by `tests/test_text_safety.py` (the helper in
isolation, including the four fields and the hard-bound invariant) and
`tests/test_graph.py::test_load_incident_bounds_and_redacts_incident_snapshot_before_persisting`
(wired into the real node).

**`investigation_report` now has its own hard SERIALIZED-SIZE ceiling**
(follow-up finding #3). Phase 5/6 bound individual evidence/prompt
fields but impose no ceiling on the investigator's output AS A WHOLE —
a shape-valid report can still be arbitrarily large. `graph/nodes.py::run_investigation`
measures the validated report's own canonical JSON serialization
(`report.model_dump_json()`) in bytes and, if it exceeds
`RuntimeBounds.max_investigation_report_bytes` (default 512 KiB,
clamped `[10_000, 5_000_000]`, configurable via
`AGENT_RUNTIME_MAX_INVESTIGATION_REPORT_BYTES`), rejects it as a
TERMINAL failure (`error_code="investigator_output_too_large"`) —
distinct from `InvestigatorUnavailableError`: an oversized response is
a valid connectivity result with an unacceptable persistence shape,
not an outage. `error_detail` contains only the measured byte count
and the configured limit — never the oversized content itself. The
default was chosen with generous headroom (~25x) over a real report
measured against this environment's own live stack (32 evidence items,
full RAG provenance, ~20.8 KB serialized).

`completed_nodes` deliberately omits an `attempt_counts` field.
Correction round, finding #11: an earlier version of this document
claimed the real number of attempts for a given node is "already fully
derivable from the checkpoint history" — too strong. A node that
crashes, or hits a transient/retryable dependency failure (§4), may
have genuinely executed (including calling the real external
dependency) without ever leaving behind a "this node completed"
checkpoint entry — checkpoint history can only ever UNDERCOUNT
attempts, never overcount, so it is not a complete, exact counter in
general. `attempt_counts` is still correctly omitted, but for a
narrower, honest reason: no Phase 7 behavior currently depends on an
exact count (retries are caller-driven via `resume`, with no internal
retry limit), so there is nothing yet for a counter to guard.

## 6. `thread_id` / `run_id` semantics

Every new agent execution gets its own server-generated `run_id`
(`uuid.uuid4()`). **`incident_id` is never the LangGraph `thread_id`** —
`run_id` is, via `thread_id = str(run_id)`. `incident_id` lives inside
graph state instead. This means:

- the same incident can be investigated by many independent,
  separately-addressable agent runs (proven by
  `tests/test_graph.py::test_same_incident_can_have_multiple_independent_run_ids`
  and `tests/test_api_agent_runs.py::test_two_runs_for_the_same_incident_get_different_run_ids`);
- `thread_id` is a plain UUID string (36 characters) — comfortably
  below any LangGraph/PostgreSQL identifier length limit.

## 7. Checkpoint persistence

The real runtime (`main.py`, via `checkpointer.py::CheckpointStore`)
opens exactly one `AsyncPostgresSaver` via `from_conn_string(...)`
(an `@asynccontextmanager` wrapping one `psycopg.AsyncConnection`,
`autocommit=True`, `prepare_threshold=0`, `row_factory=dict_row`) and
calls `.setup()` once at startup — idempotent, creates
`checkpoint_migrations` / `checkpoints` / `checkpoint_blobs` /
`checkpoint_writes` under this service's own dedicated schema (§8).

Every `ainvoke()` call (both the first real execution via `resume` and
any later resume) passes `durability="sync"` — the strongest of
LangGraph's durability modes: each node's checkpoint is durably
committed to PostgreSQL before the next node starts.
`GET /api/v1/agent-runs/{id}/history` reads real, multiple checkpoints
back via `aget_state_history(...)` — not a single in-memory snapshot —
and returns only safe metadata (step, checkpoint id, node, status,
timestamp, next node(s)); it never exposes a raw checkpoint blob, a
database internal, or a secret.

**Startup is deliberately fail-fast, not degrade-gracefully**
(correction round, finding #1). `main.py`'s `lifespan` awaits
`checkpoint_store.open()` directly and uncaught — a missing or invalid
`AGENT_RUNTIME_DB_PASSWORD` makes the whole ASGI application fail to
start (the container then crash-loops under `restart: unless-stopped`
until the real dependency exists), never a graceful
`/health/ready: 503`. This is intentional: durable PostgreSQL
persistence is this service's core dependency, not an optional one.
An earlier version of `docker-compose.yml`'s own comment claimed the
opposite (a graceful not-ready degradation) — corrected. The practical
implication is ordering: `AGENT_RUNTIME_DB_PASSWORD` must exist in
`.env` **before** Docker Compose ever creates the `agent-runtime-service`
container (Compose resolves `environment:` at container-creation time;
rewriting `.env` afterward does not change an already-created
container). `make db-up`'s recipe is ordered specifically to guarantee
this — see §8 and `scripts/test-db-up-order.sh`.

**Connection strings are built via `psycopg.conninfo.make_conninfo(...)`**,
never a naive f-string/URI (correction round, finding #10). A naive
`f"postgresql://{user}:{password}@{host}:{port}/{database}"` silently
breaks if `password` contains a reserved URI character (`@`, `:`, `/`,
`?`, `#`, whitespace) — this service's own auto-generated password
(hex digits only) could never trigger this, but an operator-supplied
one is not guaranteed to be URI-safe. `make_conninfo` produces a real
libpq keyword/value conninfo string with correct quoting, verified to
round-trip a password containing every one of those reserved
characters (`tests/test_config.py::test_checkpoint_db_settings_conn_string_handles_reserved_uri_characters`).
The resulting value is never logged or printed, under any code path.

## 8. Dedicated PostgreSQL role/schema

agent-runtime-service requires real persistence but must never receive
the existing broad `POSTGRES_USER`/`POSTGRES_PASSWORD` role the rest of
this platform's application code uses. `scripts/init-agent-runtime-db.sh`
provisions, on the **same** PostgreSQL server/database (never a second
database or server):

- a dedicated role, `agent_runtime` (password generated once into
  `.env`, never regenerated on rerun, never printed to stdout/stderr
  on any code path);
- a dedicated schema, `agent_runtime`, owned by that role
  (`CREATE SCHEMA ... AUTHORIZATION agent_runtime`);
- `ALTER ROLE agent_runtime SET search_path TO agent_runtime` — critical,
  because LangGraph's own `setup()` creates its tables with
  *unqualified* names, so this is what makes them land in
  `agent_runtime`, never `public` or `reliability`;
- explicit `REVOKE ALL ON SCHEMA reliability` /
  `REVOKE ALL ON ALL TABLES IN SCHEMA reliability FROM agent_runtime` —
  real, useful defense in depth against a future **direct** grant to
  this role. **Corrected claim (correction round, finding #7):** this
  is **not**, and this document no longer claims it is, a guarantee
  against a future grant to `PUBLIC` or to some other role this role
  might someday be made a member of. PostgreSQL privilege composition
  is additive — a role's effective privileges are the union of
  whatever is granted directly to it, to `PUBLIC`, and (if `INHERIT`)
  to any role it is a member of — so a plain `REVOKE ... FROM agent_runtime`
  removes only a direct grant to `agent_runtime` itself; it is not a
  negative "DENY" that overrides a grant arriving some other way. The
  real, authoritative guarantee is, and remains, the fact that no such
  grant exists anywhere in `database/migrations/` today, re-proven
  against the real database on every CI run (see the table below);
- role-attribute hardening, re-applied on every run:
  `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT`
  — the first five are already PostgreSQL's own defaults for a plain
  `CREATE ROLE`, made explicit and auditable here rather than relied
  upon implicitly; `NOINHERIT` is real, independent hardening: even if
  this role were ever (by operator mistake) granted membership in some
  other role, it would not automatically use that role's privileges
  without an explicit `SET ROLE`.

**user=agent_runtime and schema=agent_runtime are an architectural
security constant, not a normal operator tuning knob** (correction
round, finding #6). An earlier version of `CheckpointDbSettings.from_env()`
accepted any `AGENT_RUNTIME_DB_USER`/`AGENT_RUNTIME_DB_SCHEMA` value
(e.g. `AGENT_RUNTIME_DB_USER=postgres`), which could let the *running*
service diverge from the role `test_db_privilege_boundary.py` always
connects as and proves denied — an incomplete proof if the two ever
disagreed. Fixed: `from_env()` now fails closed (raises
`InvalidCheckpointIdentityError`) if either is set to anything other
than `"agent_runtime"`; `scripts/init-agent-runtime-db.sh` likewise
rejects (rather than silently preserves) an existing `.env` with a
different value. The *running* service's own live connection identity
is independently re-confirmed (not just the startup-time config
validation) via `checkpointer.CheckpointStore.identity()`
(`SELECT current_user, current_schema(), current_setting('search_path')`
against the one real connection this process holds), surfaced as safe
metadata in `/health/ready` and asserted by
`scripts/verify-agent-runtime.sh` against the real, running service.

LangGraph's own checkpoint tables are intentionally **not** a Flyway
migration — they are framework-owned and created by `.setup()` itself;
turning them into a hand-written migration would just be duplicating
LangGraph's own schema management, with no benefit.

This boundary is proven by a real PostgreSQL test connecting **as**
the `agent_runtime` role itself (`tests/test_db_privilege_boundary.py`,
real-database-gated, see §13), not merely asserted:

| Operation | Result |
|---|---|
| Use its own `agent_runtime` schema/tables | **allowed** |
| `SELECT` on `reliability.incidents` | **denied** (`permission denied`) |
| `UPDATE` on `reliability.incidents` | **denied** (`permission denied`) |
| `SELECT` on `reliability.retrieval_chunks` | **denied** (`permission denied`) |
| `INSERT`/`UPDATE`/`DELETE` on `reliability.incident_events` | **denied** (`permission denied`) |

(Correction round, finding #13: an earlier version of this table
claimed `INSERT` denial without a corresponding real test — only
`UPDATE`/`DELETE` were tested. `INSERT` is now independently tested
too, both in `test_db_privilege_boundary.py` and live, against the
real running stack, by `scripts/verify-agent-runtime.sh`.)

The gate fails closed: these tests `pytest.fail()` (not skip) whenever
`AGENT_RUNTIME_REQUIRE_REAL_DB=true`, the flag CI's dedicated
real-database step sets. `test_db_privilege_boundary.py` also directly
asserts that `CheckpointDbSettings.from_env()` resolves to
`user="agent_runtime"`/`schema="agent_runtime"` — the same identity
this file's own tests connect as — so the privilege proof can never
silently refer to a role the live service doesn't actually use.

## 9. Restart/resume semantics

**Create and execute are split (correction round, finding #2 — the
core invariant: "the caller must possess a durable run id before any
fallible external graph work begins").** An earlier version of
`create_agent_run` executed the *entire* graph synchronously before
returning — if the process crashed during that very first execution,
LangGraph left a perfectly valid, resumable checkpoint, but the caller
had never received the `run_id` needed to ever find it again. Fixed:

- **`POST /api/v1/agent-runs`** seeds a durable *initial* checkpoint
  via `graph.aupdate_state(config, initial_state, as_node=START)` —
  LangGraph's real API for writing state "as if it came from" a given
  node (verified directly against the installed LangGraph version
  before this was adopted: it correctly leaves `next` pointing at
  `load_incident`, without executing it). **No external call happens
  in this handler at all.** The response already has a real, durable
  `run_id`, `status="running"`, `current_node="start"`, `resumable=true`.
- **`POST /api/v1/agent-runs/{run_id}/resume`** is what actually
  executes the graph — via `ainvoke(None, config, durability="sync")`.
  This is the exact same call, and the exact same endpoint, whether it
  is running the thread for the very first time or recovering it after
  a crash: from LangGraph's own point of view these are identical —
  continue a thread whose checkpoint has a non-empty `next` — so there
  is no hand-rolled duplicate workflow/state machine here, only this
  one real LangGraph operation serving both cases.

"Resumable" is defined precisely by LangGraph's own checkpoint state:
a thread's real checkpoint has a `next` tuple — empty means the graph
reached a terminal node (`finalize`, whether `status="completed"` or
`status="failed"`) and is **never** resumable; non-empty means the
graph has not yet reached a terminal node — whether because it hasn't
started yet (just seeded), genuinely stopped mid-execution (a process
crash), or hit an uncaught transient/retryable dependency failure (§4)
— and **is** resumable.

- `POST /api/v1/agent-runs/{run_id}/resume` on a resumable thread calls
  `graph.ainvoke(None, config=config, durability="sync")` — LangGraph's
  real resume semantics, picking up from exactly the pending node(s).
  This is never faked by reconstructing new graph state from the API's
  own response shape.
- **Transient/retryable dependency failure during resume** (correction
  round, finding #3): `ControlPlaneUnavailableError`/`InvestigatorUnavailableError`
  propagate uncaught out of `graph.ainvoke()` — the last successfully
  committed checkpoint remains the resume point, so the thread stays
  fully resumable. `api/agent_runs.py::resume_agent_run` is the ONLY
  place either is translated: into a safe, generic, fixed `503`
  (`"control-plane is temporarily unavailable; this agent run remains
  resumable"` / the equivalent for investigator-service) — never the
  raw exception text, and never a persisted `"failed"`/terminal graph
  state (that would make a transient outage permanently unrecoverable,
  exactly what this correction fixes). A later resume, after the
  dependency recovers, continues from the correct node and never
  re-executes an already-committed node — proven directly in
  `tests/test_graph.py` (`test_control_plane_unavailable_propagates_and_leaves_thread_resumable_at_load_incident`,
  `test_investigator_unavailable_propagates_and_leaves_thread_resumable_at_run_investigation`),
  `tests/test_api_agent_runs.py`, and live against the real stack by
  `scripts/verify-agent-runtime.sh` (stopping investigator-service,
  confirming `503` + still-resumable, restoring it, resuming to
  completion).
- `POST /api/v1/agent-runs/{run_id}/resume` on a **terminal** thread
  returns an explicit `409`, rather than silently relying on
  `ainvoke(None, ...)`'s own safe no-op behavior on a completed thread
  (confirmed empirically before this design was adopted) — a caller
  gets a precise, documented status instead of an ambiguous `200`.
  Repeating the resume call is equally safe and equally `409`.
- Restarting the whole `agent-runtime-service` process changes nothing
  about any of this: a brand-new Python runtime instance reads the
  exact same durable PostgreSQL checkpoint state, whether that thread
  is terminal or still mid-flight. This is proven three ways: once in
  `tests/test_checkpoint_durability.py` (destroying and recreating the
  Python runtime objects directly, real-database-gated, for a thread
  mid-flight after an unclassified crash); once against the full real
  Docker Compose stack by `scripts/verify-agent-runtime.sh` **restarting
  the `agent-runtime-service` container while a run is still genuinely
  incomplete** (a real transient investigator-service outage, not a
  synthetic state) and confirming its exact state survives the restart
  byte-for-byte before resuming it to completion; and implicitly for a
  completed run, since every post-restart `GET`/`history`/`resume(409)`
  check in that same script runs against the already-restarted process.

## 10. At-least-once external-call limitation (honest, not hidden)

If the process dies **after** an external call (control-plane GET or
investigator-service POST) succeeded but **before** that node's
checkpoint is durably committed, LangGraph will re-execute that node on
resume — it has no record the external call already happened. Phase 7
does **not** claim exactly-once external invocation; it provides
**at-least-once**.

This is safe today because every external call Phase 7 makes is
read-only or purely computational (a `GET`, and a `POST` to an
already-read-only/computational investigator-service endpoint) — a
redundant re-investigation produces the same kind of report, not a
duplicated side effect. This stops being automatically safe the moment
a node performs a real side-effecting action (remediation,
notification, a write) — which is exactly why Phase 8 (human approval,
`interrupt()`, remediation) is a deliberately separate, later phase
with its own idempotency design, not something bolted onto Phase 7's
current nodes.

## 11. Security / read-only boundaries

agent-runtime-service never holds, and structurally cannot reference,
any write-capable or infrastructure-control credential:

- no `CONTROL_PLANE_WEBHOOK_TOKEN`, no `CONTROL_PLANE_LIFECYCLE_TOKEN`;
- no `POSTGRES_USER`/`POSTGRES_PASSWORD` (only its own dedicated
  `AGENT_RUNTIME_DB_USER`/`AGENT_RUNTIME_DB_PASSWORD`, §8);
- `clients/control_plane.py` has exactly one method (`get_incident`,
  `GET` only — structurally confirmed: no `post`/`put`/`patch`/`delete`
  attribute access anywhere in the module);
- `clients/investigator.py` has exactly one method (`investigate`, one
  `POST` to investigator-service's own already read-only endpoint —
  structurally confirmed: no other write verb anywhere in the module);
- no reference anywhere to control-plane's lifecycle `PATCH` path or
  Alertmanager's webhook path;
- no import of `docker`, `subprocess`, `kubernetes`, `boto3`, or
  `botocore` anywhere in the service;
- no import of `asyncpg` or `sqlalchemy` (its only database access is
  `psycopg`, via `langgraph-checkpoint-postgres`, to its own schema);
- no real-code string literal anywhere in the service names
  `reliability.incidents`, `reliability.incident_events`, or
  `reliability.retrieval_chunks` (docstrings explaining what this
  service deliberately avoids are allowed; real code is not).

All of the above is enforced structurally via AST analysis in
`tests/test_read_only_guarantees.py` (walking real imports/attribute
accesses/string constants, explicitly excluding docstrings) — not
merely a written policy. All upstream URLs are configuration-defined
(`AGENT_RUNTIME_CONTROL_PLANE_URL`, `AGENT_RUNTIME_INVESTIGATOR_URL`);
no LLM-supplied or caller-supplied URL is ever dereferenced.

**Pydantic shape-validation errors never leak upstream field values**
(correction round, finding #5). `pydantic.ValidationError.__str__`
includes each failing field's `input_value` verbatim — an earlier
version of `clients/investigator.py` concatenated this directly into
`InvestigatorOutputError`'s message (independent review reproduced a
fake `sk-...` value from a malformed response appearing in
`str(exc)`, which could then reach durable `error_detail`).
`clients/control_plane.py` had the equivalent gap (`IncidentSnapshot.model_validate`
called with no shape-failure handling of its own). Both are fixed
identically: a fixed, generic exception message (`"...did not match
the expected response contract"`), with only safe, structural metadata
(exception class, `exc.error_count()`, HTTP status) logged — never
`str(exc)`, never the raw response body. Proven by adversarial tests
containing a fake secret in a field that fails shape validation, in
both client test modules, confirming it appears in neither the raised
exception's own message nor (by extension) `error_detail`, the
`AgentRun` API response, or persisted graph state.

`/health/live` never depends on the checkpoint store (restarting the
process would not fix control-plane/investigator-service being down,
so conflating those would only cause unnecessary restart loops).
`/health/ready` honestly reflects only whether the durable checkpointer
itself is usable (a real round-trip against this service's own
schema) — it does not require control-plane or investigator-service to
currently be healthy; a down upstream fails explicitly and
informatively at the specific node that calls it, which is a
per-request outcome, not a process-readiness concern.

## 12. API contract

- **`POST /api/v1/agent-runs`** — body `{"incident_id": "<uuid>"}`
  (`extra="forbid"`; a caller-supplied `thread_id` or `run_id` is
  rejected with `422`). The server generates `run_id`/`thread_id` and
  **seeds a durable initial checkpoint only** (§9, correction round
  finding #2) — it makes NO control-plane/investigator-service call.
  Returns the full `AgentRun` view, `201`,
  `status="running"`/`current_node="start"`/`resumable=true`.
- **`GET /api/v1/agent-runs/{run_id}`** — loads the persisted LangGraph
  state and returns a safe, normalized `AgentRun`. Unknown `run_id`:
  `404`. Never exposes a raw checkpoint blob.
- **`GET /api/v1/agent-runs/{run_id}/history`** — safe checkpoint
  metadata only (step, checkpoint id, node, status, timestamp, next
  node(s)), bounded to `AGENT_RUNTIME_MAX_HISTORY_ITEMS` entries, in
  chronological order. Unknown `run_id`: `404`. Never raw checkpoint
  bytes, database internals, secrets, or raw provider exceptions.
- **`POST /api/v1/agent-runs/{run_id}/resume`** — executes/continues
  the **same** LangGraph thread (never starts a new run; this is also
  what actually runs the graph for the very first time, right after
  creation — §9). Unknown `run_id`: `404`. Terminal/non-resumable run:
  `409`, repeatable safely, never re-executes. A transient/retryable
  dependency failure mid-execution (§9, correction round finding #3):
  `503` with a safe, fixed, generic `detail` message — never the raw
  exception, never a persisted failure — and the run remains
  resumable (confirm via a subsequent `GET`).

## 13. Acceptance proof

- **Unit tests** (`services/agent-runtime-service/tests/`, isolated,
  no real database): **87 passed, 8 skipped** (the 8 skips are the
  real-database-gated tests, correctly skipping when no real database
  is configured).
- **Real PostgreSQL gate** (`AGENT_RUNTIME_REQUIRE_REAL_DB=true`,
  against the live stack): **95 passed, 0 failed, 0 skipped** —
  includes the full privilege-boundary proof (§8, now including a real
  `INSERT` denial and the live-identity-matches-settings proof,
  connecting via the same safe `make_conninfo` builder the real
  application uses) and the full checkpoint durability proof below.
- **Hard-bound proof** (follow-up finding #1): `tests/test_text_safety.py`
  proves `text_safety.hard_bound`'s own invariant directly (an
  over-max input never returns more than `max_chars`, including any
  truncation suffix), and every bounded-field test in that module and
  in `tests/test_graph.py` now asserts `len(value) <= configured_max` —
  never `configured_max + len(suffix)`.
- **`source`/`source_fingerprint` bounding+redaction proof** (follow-up
  finding #2): `tests/test_text_safety.py` proves an oversized
  `source`/`source_fingerprint` is hard-bounded, a credential-shaped
  `source_fingerprint` (the independent review's exact reproduction:
  a `"Bearer ..."`-prefixed, 5000+ character fingerprint) is redacted,
  and clean/normal Alertmanager values pass through unchanged;
  `tests/test_graph.py::test_load_incident_bounds_and_redacts_incident_snapshot_before_persisting`
  proves the same end to end through the real node.
- **Investigation-report serialized-size proof** (follow-up finding
  #3): `tests/test_graph.py::test_oversized_investigation_report_is_rejected_safely`
  proves a structurally shape-valid but oversized report is rejected
  (`error_code="investigator_output_too_large"`), never persisted into
  `investigation_report`, and never echoed raw into `error_detail`
  (only a safe, fixed-shape byte-count message);
  `test_normal_sized_investigation_report_is_unaffected_by_the_size_ceiling`
  proves a real-shaped report is unaffected.
- **Checkpoint durability proof** (`tests/test_checkpoint_durability.py`,
  using the service's own real `build_graph`/`compile_graph`, never a
  toy graph): creates runtime instance A, executes a real graph far
  enough to create real checkpoints, injects a genuinely unclassified
  failure (an uncaught `RuntimeError`, not a classified
  `IncidentNotFoundError`/etc. — an unclassified exception is exactly
  what a real process crash looks like to LangGraph, leaving `next`
  non-empty), destroys instance A (`del` on the store/saver/graph/
  client objects), creates a completely new runtime instance B against
  the same PostgreSQL, resumes the same thread, and confirms: prior
  successful progress was recovered from durable checkpoint state (not
  local Python memory — proven by instance A no longer existing at
  all), the graph reaches completion, and the recovered values match.
  Complemented, at the real-graph-but-`InMemorySaver` level, by
  `tests/test_graph.py`'s two TRANSIENT/RETRYABLE-specific tests (§9)
  using the real classified exception types rather than a raw
  `RuntimeError`.
- **Process-restart + public-API resumability acceptance**
  (`scripts/verify-agent-runtime.sh`, against the real Docker Compose
  stack, stub LLM mode, no paid API key): creates a durable agent run
  (seed only, §9), stops investigator-service to force a REAL transient
  outage, confirms `resume` returns a safe `503` and the run remains
  resumable via `GET`, **restarts the real `agent-runtime-service`
  container while the run is still genuinely incomplete** and confirms
  its exact state survives byte-for-byte, restores investigator-service,
  resumes the SAME `run_id` to completion through the real
  control-plane + investigator-service + Phase 6 RAG pipeline
  (confirming `load_incident` was never re-executed —
  `completed_nodes.count("load_incident") == 1`), inspects safe
  history, confirms `409` on resuming a completed run (twice), and
  confirms `404` on an unknown run across GET/history/resume. Also
  independently re-confirms the live service's own checkpoint
  connection identity via `/health/ready` (§8) and the real `INSERT`
  denial (§8) against this exact running stack.
- **No-mutation proof, two layers** (correction round, finding #8):
  the reused incident's row and its complete, fully-paginated audit
  event list are captured before the agent run and compared
  byte-for-byte after (including after the restart) — unchanged. **In
  addition**, `reliability.incidents`/`reliability.incident_events`
  are compared both by row count AND by a real, deterministic
  full-content fingerprint (`md5(string_agg(row_to_json(t)::text, '|'
  ORDER BY t.id))` over every row in each table) captured before and
  after the entire run — a stronger guarantee than row count alone,
  since a mutation to some OTHER row (never the one selected incident,
  never changing either table's row count) would still change this
  value. Both unchanged.
- **Phase 5 regression**: `services/investigator-service` full test
  suite — unaffected, still passes in full (150/150); `scripts/verify-investigator.sh`
  continues to pass unmodified.
- **Phase 6 regression**: `services/retrieval-service` full test
  suite — unaffected, still passes in full (66/66, 2 skipped);
  `scripts/verify-rag.sh` continues to pass unmodified.
- **Fresh-start ordering regression test** (correction round, finding
  #1): `scripts/test-db-up-order.sh` (no Docker required) statically
  proves `make db-up`'s recipe provisions `AGENT_RUNTIME_DB_PASSWORD`
  into `.env` BEFORE the full `docker compose up -d` that actually
  creates `agent-runtime-service` — see §7 and §8.

## 14. Known limitations (honest, not hidden)

- **At-least-once, not exactly-once**, for external calls around a
  crash (§10) — safe today only because every Phase 7 node is
  read-only/computational.
- **Checkpoint retention is basic/local-development scale** — this
  phase does not implement checkpoint pruning, archival, or a
  retention policy; every checkpoint for every run accumulates in
  `agent_runtime.checkpoints` indefinitely.
- **Concurrent resume requests against the same thread are not
  specifically serialized or tested** (precision correction, follow-up
  finding #5D: an earlier version of this limitation framed the
  concern as "multiple processes" only). Two `resume` requests racing
  against the SAME `run_id`/`thread_id` — whether both are handled by
  ONE `agent-runtime-service` process or by multiple processes — are
  not specifically addressed or load-tested here. LangGraph's own
  PostgreSQL-level locking provides some protection, but this remains
  an untested area, not a proven-safe one. There is also no horizontal
  scaling story yet — one `agent-runtime-service` process is assumed.
- **A created-but-unknown-to-the-caller run can become an orphan**
  (follow-up, finding #6). If `POST /api/v1/agent-runs` durably seeds a
  run but the HTTP response is lost before the caller receives it
  (a connection drop after the server-side commit, before the `201`
  reaches the client), the caller never learns the server-generated
  `run_id` — and Phase 7 has no client-supplied idempotency key and no
  agent-run listing/search endpoint to recover it by. That checkpoint
  then sits unresumed until a future retention/administrative cleanup
  mechanism exists (§14's checkpoint-retention limitation above). This
  is an ordinary distributed-systems edge case, not specific to this
  design; it is not solved in Phase 7 and is left for a future API/
  idempotency/operations phase.
- **`evaluate_investigation`'s classification is a simple, deterministic
  heuristic** over already-structured fields — it is not a sophisticated
  quality model, and is not intended to be read as one.
- **History pagination is a bound, not a cursor** — `history` returns
  up to `AGENT_RUNTIME_MAX_HISTORY_ITEMS` most-recent-relevant entries;
  a run with more checkpoints than that bound does not expose a
  "next page" mechanism in Phase 7.
- **Create and execute are two separate calls, by design** (§9) — a
  caller must call `POST /agent-runs` and then `POST .../resume` to get
  a run to actually execute; there is no automatic or background
  execution. This is the direct, intentional consequence of the
  core invariant that the caller must possess a durable `run_id`
  before any fallible graph work begins — not an oversight.
- **No automatic retry of a transient dependency failure** — `resume`
  returning `503` does not itself retry; the caller decides when (and
  whether) to call `resume` again. Phase 7 provides the durable,
  safely-resumable substrate; it does not implement a retry/backoff
  policy on top of it.

## 15. Explicit Phase 8 boundary

Phase 7 deliberately does **not** include, and nothing above should be
read as a partial implementation of:

- human approval of any kind;
- LangGraph `interrupt()` or any human-in-the-loop pause;
- `approve` / `reject` / remediation-proposal endpoints;
- restart, rollback, or scale actions against any application service;
- execution of any remediation whatsoever;
- any dynamic, LLM-directed tool-calling loop.

These are Phase 8's explicit scope. Phase 7 provides the durable
execution substrate (graph state, checkpoints, resume semantics,
dedicated least-privileged persistence) that Phase 8 will build human
approval and controlled remediation on top of — it does not pre-empt
or partially implement any of that here.
