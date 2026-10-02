# Phase 3E: Incident Audit Trail

This document describes the durable, append-only incident audit trail
built on top of the existing `reliability.incidents` table (Phase 3A),
Alertmanager webhook ingestion (Phase 3C), and the incident lifecycle
state machine (Phase 3D): the `reliability.incident_events` schema and
its invariants, exactly which accepted mutations are recorded and how
they are attributed, the transactional guarantee tying every audit
record to its incident change, concurrency and ordering, the read-only
timeline API, and how all of it is verified against real
infrastructure.

It does **not** describe the `reliability.incidents` schema itself
(Phase 3A — see [incident-domain-model.md](incident-domain-model.md)),
basic webhook ingestion (Phase 3C — see
[phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md)), or the
lifecycle state machine and its management API (Phase 3D — see
[phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md)), all
reused here unchanged.

## The schema

`database/migrations/V3__create_incident_audit.sql` adds exactly one
new table, `reliability.incident_events`, purely additive — `V1` and
`V2` are never touched. A post-review correction,
`database/migrations/V4__harden_incident_audit.sql`, closes a real gap
in `V3`'s append-only enforcement and corrects `occurred_at`'s
semantics — see
[Post-review correction: hardening (V4)](#post-review-correction-hardening-v4)
below. `V3` itself was never edited to make these fixes: it had
already been applied to the non-empty local development database, and
editing an already-applied migration file invalidates Flyway's
recorded checksum for it (a real, reproducible failure — see
[docs/architecture/incident-domain-model.md](incident-domain-model.md)).
Both `V4` fixes are expressed as new, additive DDL instead
(`CREATE OR REPLACE FUNCTION` on the existing trigger function, a new
trigger, and an `ALTER COLUMN ... SET DEFAULT`).

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | NOT NULL (PK) | A plain, monotonically increasing identity column. Not a UUID: its only job is a deterministic ordering tie-breaker (see [Ordering](#concurrency-and-ordering) below) — never a public identifier anything is expected to construct. |
| `incident_id` | `UUID` | NOT NULL | References `reliability.incidents(id)`, `ON DELETE RESTRICT`. |
| `event_type` | `TEXT` | NOT NULL | One of `created`, `observed`, `status_transition` (CHECK). |
| `actor_type` | `TEXT` | NOT NULL | One of `alertmanager`, `operator` (CHECK). |
| `previous_status` | `TEXT` | nullable | `NULL` only for `created`; otherwise one of the six incident statuses (CHECK). |
| `new_status` | `TEXT` | NOT NULL | One of the six incident statuses (CHECK). |
| `occurred_at` | `TIMESTAMPTZ` | NOT NULL, `DEFAULT clock_timestamp()` (post-review correction; `V3` originally shipped `now()` — see [occurred_at semantics](#occurred_at-semantics-genuine-insertion-time-not-transaction-start-time) below) | When this event was genuinely inserted. |
| `metadata` | `JSONB` | NOT NULL, `DEFAULT '{}'::jsonb` | A minimal, allowlisted, structured object (CHECK `jsonb_typeof(metadata) = 'object'`) — see [Metadata](#metadata-minimal-structured-allowlisted) below. |

### Event/status shape consistency

Three named `CHECK` constraints enforce, per `event_type`, exactly
which `previous_status`/`new_status`/`actor_type` combinations are
legal — not left to application discipline alone:

- `incident_events_created_shape`: `created` requires
  `previous_status IS NULL`, `new_status = 'open'`, and
  `actor_type = 'alertmanager'`.
- `incident_events_observed_shape`: `observed` requires
  `previous_status IS NOT NULL`, `previous_status = new_status`
  (status never actually changes for an observation), and
  `actor_type = 'alertmanager'`.
- `incident_events_status_transition_shape`: `status_transition`
  requires `previous_status IS NOT NULL` and
  `previous_status <> new_status` (a transition, by definition,
  actually changes status). Either `actor_type` is valid here — an
  operator PATCH or Alertmanager's automatic resolution.

### The index

```sql
CREATE INDEX incident_events_incident_id_occurred_at_idx
    ON reliability.incident_events (incident_id, occurred_at ASC, id ASC);
```

Exactly the query `GET /api/v1/incidents/{id}/events` runs — a single
incident's timeline, oldest first, with `id` as the tie-breaker for
events that share an `occurred_at` (entirely plausible: two events for
the same incident within the same transaction, or simply a fast enough
pair of requests, can share a timestamp).

### `ON DELETE RESTRICT`, not `CASCADE`

An incident with any recorded audit history can never be deleted at
all — the parent `DELETE` itself is rejected, not silently cascaded
into deleting its history too. This is a real, enforced constraint,
not just documentation: no code path in this service has ever deleted
a row from `reliability.incidents` (there is no delete endpoint), so
this is additionally a defense against a future mistake, not something
today's application code currently has to work around. It does have a
real, non-obvious consequence for test tooling — see
[Testing against real PostgreSQL](#testing-against-real-postgresql)
below.

### Append-only enforcement

```sql
CREATE TRIGGER incident_events_no_update   BEFORE UPDATE   ON reliability.incident_events FOR EACH ROW ...
CREATE TRIGGER incident_events_no_delete   BEFORE DELETE   ON reliability.incident_events FOR EACH ROW ...
CREATE TRIGGER incident_events_no_truncate BEFORE TRUNCATE ON reliability.incident_events FOR EACH STATEMENT ...  -- V4
```

All three triggers call the same function
(`reliability.incident_events_block_mutation`), which unconditionally
`RAISE EXCEPTION`s. This is a database-level guard, not merely an
application convention of "we just never UPDATE/DELETE/TRUNCATE this
table" — the only reliable way to make a *direct SQL client*, not just
this application's own code, fail loudly if it ever attempts any of
the three.

**Stated honestly, and corrected by post-review review:** this is an
append-only *application* record, not a claim of tamper-proof storage.
The original version of this document described the bypass case as
"a PostgreSQL superuser" specifically — that understated the real
boundary. **Any role with sufficient privilege over this table** — its
owner, or a role granted the right to `ALTER`/`DROP` it or its
triggers — can disable or drop these triggers, or `TRUNCATE`/`DROP` the
table outright regardless of trigger state, not only a superuser. This
is a guard against this application's own normal connection role (and
any other similarly-unprivileged client) ever mutating or erasing
history — not a cryptographic or storage-level tamper-proofing
mechanism, and not a claim about what a sufficiently privileged table
owner could do.

### Post-review correction: hardening (V4)

Independent review of the first version of this phase found two real
gaps, both fixed in `database/migrations/V4__harden_incident_audit.sql`
without touching `V3` (which had already been applied to the non-empty
local development database — editing it would invalidate Flyway's
recorded checksum):

1. **`TRUNCATE` bypassed both existing triggers entirely.** `V3`'s two
   triggers are `BEFORE UPDATE`/`DELETE`, `FOR EACH ROW` — but
   `TRUNCATE` is a distinct statement in PostgreSQL's trigger model
   that never fires row-level triggers at all (that is exactly why it
   is so much faster than a row-by-row `DELETE`), so it needs its own,
   separate `BEFORE TRUNCATE`, `FOR EACH STATEMENT` trigger. `V4` adds
   one, via `CREATE OR REPLACE FUNCTION` on the SAME function `V3`
   created (so the two existing triggers automatically pick up the new
   body with no changes of their own) plus one new `CREATE TRIGGER`.
   The one real subtlety: a statement-level trigger has no row-level
   `OLD`/`NEW` record at all, so the shared function branches on
   `TG_OP` *before* ever referencing `OLD.id` — the row-level
   UPDATE/DELETE branch's `OLD.id` reference is never evaluated during
   a `TRUNCATE` invocation, avoiding Postgres's own "record \"old\" is
   not assigned yet" error in favor of this function's own intentional
   message. Verified directly against real PostgreSQL: a `TRUNCATE`
   attempt now fails with `reliability.incident_events is append-only:
   TRUNCATE is not permitted`, and every pre-existing row (44 real rows
   from earlier development/testing, at the time this was verified)
   survived intact.
2. **The "superuser" framing understated the real bypass boundary** —
   corrected above, in the main append-only section (not just here),
   since it is the accurate, current statement of this limitation, not
   a historical note.

**Safety property of the verification itself, not just the fix:**
`scripts/verify-incident-audit.sh`'s `TRUNCATE` test wraps the attempt
in `BEGIN; TRUNCATE ...; ROLLBACK;` — an explicit transaction that is
never committed. This means that even if the guard trigger were
somehow missing or broken (i.e. even if `TRUNCATE` actually succeeded
inside that transaction), the `ROLLBACK` immediately after would still
undo it before anything could persist. The test script itself must
never be capable of destroying real `incident_events` history,
regardless of whether the fix it is testing for actually works.

### Honest historical-coverage limitation

**Audit coverage begins with Phase 3E.** This table is populated going
forward, starting with this migration — it is **not** backfilled with
invented historical events for incidents (or incident mutations) that
predate it. There is no reliable source to reconstruct that history
from, and fabricating it would defeat the entire purpose of an audit
trail. A pre-existing incident, or one that has only ever been read
and never mutated after creation, may legitimately have an empty audit
timeline — `GET /api/v1/incidents/{id}/events` returns `200` with
`"items": []`, never a `404` and never fabricated history. See
[Testing against real PostgreSQL](#testing-against-real-postgresql)
for the real proof of this.

## Audit event semantics

Four cases, matched exactly to the task's own lettering:

| Case | `event_type` | `actor_type` | `previous_status` | `new_status` |
|---|---|---|---|---|
| A. Incident creation | `created` | `alertmanager` | `NULL` | `open` |
| B. Accepted firing observation into an active incident | `observed` | `alertmanager` | actual current status | same (unchanged) |
| C. Successful operator PATCH transition | `status_transition` | `operator` | actual previous status | committed target status |
| D. Successful Alertmanager automatic resolution | `status_transition` | `alertmanager` | actual previous status | `resolved` |

**The existing lifecycle state machine
(`domain/lifecycle.py`) remains the sole authority for which
transitions are legal** — this phase adds no new transition logic
anywhere; it only records what the existing, unchanged logic already
decided to accept.

### Metadata: minimal, structured, allowlisted

Every event's `metadata` is one of exactly these shapes, never
anything else:

- `created`/`observed`: `{"source_fingerprint": "...", "observed_starts_at": "<ISO-8601>"}` — the alert's own fingerprint and the `startsAt` this delivery carried. A genuinely useful summary of "what was observed" without being verbose.
- `status_transition` (operator): `{}` — nothing useful to add beyond what the event's own typed columns already carry.
- `status_transition` (Alertmanager resolution): `{"resolution_source": "alertmanager_webhook"}`.

**Never stored, by construction — not merely by policy:**

- A Bearer token or any credential.
- A raw `Authorization` header.
- An entire unfiltered webhook payload.
- Arbitrary client-provided metadata — there is no code path through
  which a caller's own data reaches this column at all; every value
  written here is assembled by the repository itself from a fixed,
  small set of fields it already validated.

### `actor_type='operator'` never fabricates an identity

The operator lifecycle endpoint (Phase 3D) authenticates with a
**shared** Bearer token — it does not, and cannot, identify an
individual human (see
[phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md#authentication-boundaries)).
Accordingly, `actor_type='operator'` records only that an authenticated
operator request caused this event — never a user id, a name, or any
other individual-identity claim. There is no `user_id` column, and
none is planned; adding one without a real per-user credential system
behind it would be a fabrication, not an audit record.

## Transaction boundaries

**Every audit record is written as a direct, internal consequence of
the mutation method that accepted it — using the exact same
`AsyncSession`, and therefore the exact same transaction, as that
mutation.** There is no separate commit, no second connection, no
background task, and no public write path for audit events at all —
see [Security/API design](#the-get-timeline-api) below.

Concretely, in `repositories/incident_repository.py`:

- `upsert_firing_incident` (the webhook firing path) issues one
  `INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING id, status,
  (xmax = 0) AS created`, then — in the SAME method call, same
  session — records a `created` or `observed` event using `status`
  straight from that `RETURNING` clause. This is safe without any
  extra read or lock: the statement's own `SET` clause never touches
  `status` at all, so the value `RETURNING` reports is simultaneously
  correct as both "previous" and "new" status — there is no window in
  which it could be stale.
- `transition_incident_status` (the operator PATCH path) issues its
  existing atomic compare-and-swap `UPDATE ... WHERE id = :id AND
  status = :expected_status ... RETURNING *`; if (and only if) a row
  comes back, it records the `status_transition` event using
  `expected_status` — already guaranteed to be the row's real previous
  status, because the `UPDATE`'s own `WHERE` clause is what proves it
  (zero rows would have come back otherwise).
- `resolve_active_incident_for_fingerprint` (Alertmanager's automatic
  resolution) is the one case that needed real additional work — see
  [Capturing the actual previous status](#capturing-the-actual-previous-status-safely)
  below.

**Caller code (`ingestion/service.py`, `api/incidents.py`) is
unchanged.** Every audit-writing call lives entirely inside the
repository method that already performs the matching mutation — the
callers that sequence these methods, decide what's legal, and
eventually call `commit()` once, needed no new code at all to get
atomicity for free.

If any audit `INSERT` raises for any reason (a constraint violation,
or — more realistically in production — a real database failure), it
propagates exactly like any other exception from this repository: the
route or ingestion batch never reaches its own `commit()` call, and
the session's implicit rollback-on-close discards **everything** in
that transaction — the incident mutation included. This is the exact
same "single transaction, one commit at the end" architecture Phase 3C
already established for webhook batches and Phase 3D already
established for the PATCH endpoint; this phase adds a second statement
inside the existing transaction, not a new transaction boundary.

### Capturing the actual previous status safely

Unlike `transition_incident_status`, the caller of
`resolve_active_incident_for_fingerprint`
(`ingestion/service.py`'s `_process_resolved_alert`) does **not**
already know which specific active status
(`open`/`acknowledged`/`investigating`/`remediating`) the incident
currently holds — only that `get_active_incident` found *some* active
row, moments earlier. Reading that earlier snapshot's status at audit-
recording time would risk recording a **stale** previous status if a
concurrent operator PATCH changed it in the meantime (e.g.
`open -> acknowledged`) between that read and this resolution —
exactly the staleness this phase must avoid.

The fix is two statements, not one, both inside this same method call
(same session, same transaction):

```sql
SELECT status FROM reliability.incidents
 WHERE id = :id AND status NOT IN ('resolved', 'closed')
 FOR UPDATE;
-- (same transaction, no other statement in between)
UPDATE reliability.incidents
   SET status = 'resolved', resolved_at = :resolved_at
 WHERE id = :id AND status = :locked_status
RETURNING *;
```

`SELECT ... FOR UPDATE` takes a real row lock and reads the status as
of *that* moment; the subsequent `UPDATE` is then guaranteed to match
(no other writer could have changed the row in between, since the
lock is held), and the method records the event using that just-
locked, genuinely current value. The existing transaction-scoped
advisory fingerprint lock (`acquire_fingerprint_lock`) already
serializes concurrent *webhook* deliveries for this fingerprint before
any of this runs, but it does nothing against a concurrent *operator*
PATCH racing on the same row by `id` — this row-level `FOR UPDATE`
lock is what closes that specific gap. Verified directly against real
PostgreSQL in `scripts/verify-incident-audit.sh` (see below).

## Concurrency and ordering

**Concurrent operator PATCH attempts produce exactly one event, never
one per loser.** This falls directly out of Phase 3D's existing
compare-and-swap guarantee, extended by one statement: of 10 genuinely
concurrent `PATCH` requests from the same `expected_status`, exactly
one `UPDATE` affects a row (and therefore records an event); the other
nine affect zero rows, `transition_incident_status` returns `None` for
each of them, and the audit-recording call is never reached. Verified
directly: `scripts/verify-incident-audit.sh` fires 10 real concurrent
requests and confirms exactly 1 success and exactly 1 recorded event.

**Ordering** is `occurred_at ASC, id ASC` — see
[The index](#the-index) above for why `id` (not `occurred_at` alone)
is the correct tie-breaker.

### `occurred_at` semantics: genuine insertion time, not transaction-start time

**Post-review correction.** `V3` declared `occurred_at TIMESTAMPTZ NOT
NULL DEFAULT now()`. In PostgreSQL, `now()` (and its exact
equivalents, `CURRENT_TIMESTAMP`/`transaction_timestamp()`) returns the
time the *current transaction began* — one fixed value for the whole
transaction, no matter how long it runs or how many statements it
contains. Independent review identified a real consequence under
concurrent writes: transaction A can start first (fixing its own
`now()` value earlier than transaction B's), then block waiting for a
row lock B is holding; B commits first, and only then does A proceed
to insert its own audit event — using the *earlier* `now()` value A's
transaction captured when it began, not the genuinely later wall-clock
moment its `INSERT` actually ran. Since the timeline orders by
`occurred_at ASC, id ASC`, this could place A's event *before* B's,
even though A's mutation genuinely happened after B's — a misleading
incident history.

`V4` (`database/migrations/V4__harden_incident_audit.sql`) changes the
column default to `clock_timestamp()`, which returns the actual
current wall-clock time at the moment the expression is evaluated —
changing on every call, even within a single transaction or statement,
rather than being fixed once per transaction. This is exactly "when
was this specific row actually inserted," which is what an append-only
audit log's own timestamp should mean.

`ALTER COLUMN ... SET DEFAULT` changes the default applied to *future*
`INSERT`s only — it is not a backfill and does not rewrite any
existing row; every event already recorded under `V3` keeps its
original timestamp untouched. The application itself
(`repositories/incident_repository.py`'s `_record_event`) never
specifies `occurred_at` explicitly in its `INSERT` — it has always
relied on the column default — so this schema-only change took effect
for every future event with **zero application code changes**. The
`id ASC` tie-breaker is unaffected either way: `id` remains
monotonically increasing by insertion order regardless of which clock
function supplies `occurred_at`. Verified directly:
`scripts/verify-incident-audit.sh` asserts the live column default is
exactly `clock_timestamp()` via `information_schema.columns`.

## Retry/idempotency behavior

No new retry logic exists or is needed. A duplicate/stale webhook
delivery that Phase 3C/3D's own ingestion logic already decides to
*ignore* (a stale firing replay, a resolved notification for an
occurrence that was never observed firing, a duplicate resolved
delivery after a real resolution already succeeded) never reaches
`upsert_firing_incident` or `resolve_active_incident_for_fingerprint`
at all — the decision to ignore happens *before* either method is
called, so no mutation and no audit event occurs, with zero special-
casing needed in this phase. The one case genuinely new to this phase
— Alertmanager's retried webhook delivery racing a concurrent operator
PATCH, or two Alertmanager deliveries racing each other — is exactly
what the row lock in
[Capturing the actual previous status](#capturing-the-actual-previous-status-safely)
and the existing advisory fingerprint lock, respectively, already
serialize.

## Security/privacy limitations

- **Never a claim of tamper-proof storage.** As stated above: any
  role with sufficient privilege over this table — its owner, or a
  role granted the right to `ALTER`/`DROP` it or its triggers, not
  only a PostgreSQL superuser — can disable or drop the append-only
  triggers (now covering `UPDATE`, `DELETE`, and, as of the post-review
  `V4` migration, `TRUNCATE`). This is a guard against this
  application's own connection role and any other ordinary client, not
  a cryptographic audit log.
- **No individual-identity tracking for operator actions.** The
  lifecycle token is shared; `actor_type='operator'` is the most this
  service can honestly claim. See
  [actor_type='operator' never fabricates an identity](#actor_typeoperator-never-fabricates-an-identity)
  above.
- **No backfilled history.** See
  [Honest historical-coverage limitation](#honest-historical-coverage-limitation)
  above — a real, permanent limitation of this design, not a
  temporary gap.
- **The read timeline API has no authentication**, following the
  exact same local-development policy as every other `GET` route in
  this service (see
  [docs/api/control-plane.md](../api/control-plane.md)'s security-
  limitations section) — this is local-development-only, not a
  production posture.

## The GET timeline API

### `GET /api/v1/incidents/{incident_id}/events`

Read-only; same authentication policy (none) as every other `GET`
route in this service. Not a generic incident-editing API, and no
audit-creation/mutation/deletion endpoint exists anywhere — events are
only ever written as a side effect of the three mutation methods
above.

```json
{
  "items": [
    {
      "id": 1,
      "incident_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "event_type": "created",
      "actor_type": "alertmanager",
      "previous_status": null,
      "new_status": "open",
      "occurred_at": "2026-04-01T10:00:00.123456+00:00",
      "metadata": {"source_fingerprint": "8d2b83b6bbca23c7", "observed_starts_at": "2026-04-01T10:00:00+00:00"}
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

| Parameter | Default | Constraint |
|---|---|---|
| `limit` | `20` | `1`–`100` inclusive (else `422`) |
| `offset` | `0` | `>= 0` (else `422`) |

| Condition | Status |
|---|---|
| Incident exists (including an empty timeline) | `200` |
| Incident does not exist | `404` |
| Malformed UUID, or invalid `limit`/`offset` | `422` |
| Real database unavailability | `503` |

The route first calls `get_by_id` to distinguish "incident doesn't
exist" (`404`) from "incident exists but has no recorded history"
(`200`, empty `items`) — the same two-read pattern
`PATCH .../status`'s own ambiguity resolution already established in
Phase 3D, applied here for the same reason: a single query result
(zero rows) is ambiguous between two genuinely different, both-valid
outcomes.

## Testing

### Unit tests

`services/control-plane/tests/test_incident_audit.py` (new, 25 tests):
creation events, observation events (including that creation and
observation are distinct event types across two deliveries for the
same fingerprint), operator transitions (including that `actor_type`
never carries a user-id-shaped field), automatic resolution, ordered
timeline + pagination, the default `limit=20`, invalid
`limit`/`offset` (`422`), an incident with no history (empty timeline,
`200`, not `404`), missing incident (`404`), invalid UUID (`422`),
zero events for every rejected/ignored/no-op case explicitly listed in
this phase's own requirements (illegal transition, stale
`expected_status`, same-status no-op, missing incident, missing
webhook/lifecycle credentials, a stale firing replay, an ignored
resolved notification, a duplicate resolved delivery after success), a
unit-level proxy for "only the winning concurrent transition records
an event" (sequential winner-then-loser, since a real race needs a
real database), a unit-level proxy for "an audit-insertion failure
never commits" (the same `commit_count`-based proxy Phase 3D's own
commit-bug regression tests use — see below for why this is the
correct level for this specific proof), and a direct assertion that no
event's metadata ever contains the webhook token, the word
"Authorization", or the word "Bearer". `conftest.py`'s
`FakeIncidentRepository` was extended to model these semantics
accurately (recording events from the same three mutation methods the
real repository writes them from), not merely enough to pass each
test in isolation — existing tests were not weakened to accommodate
this. `make control-plane-test`: **196 tests, all passing** (171 from
Phase 3D plus 25 new).

**Why "audit-insertion failure never commits" is a unit-level proxy,
not a unit-level proof of real rollback:** the mocked repository has
no real database transaction to roll back — only a real PostgreSQL
transaction can demonstrate that an incident mutation and a failing
audit insert, in the same transaction, are discarded *together*. That
real proof is below.

### Real PostgreSQL integration (`scripts/verify-incident-audit.sh`, `make verify-incident-audit`)

Against the real running service and real PostgreSQL, 13 sections, all
passing on a real run:

1. **V3/V4 schema**: the table, its index, and the `ON DELETE RESTRICT`
   foreign key all exist; a direct `UPDATE`, a direct `DELETE`, **and
   a direct `TRUNCATE`** (post-review addition) against
   `reliability.incident_events` are all rejected by the append-only
   triggers — the `TRUNCATE` attempt is wrapped in an explicit
   `BEGIN; TRUNCATE ...; ROLLBACK;` that is never committed, so even a
   missing/broken guard could not have actually destroyed data, and
   the table's *total* row count (not just this run's rows) is
   confirmed unchanged across the attempt; `occurred_at`'s column
   default is confirmed to be exactly `clock_timestamp()` (post-review
   addition); deleting an incident that has recorded audit history is
   rejected by the foreign key; a non-object `metadata` value and a
   shape-violating event are both rejected by their respective `CHECK`
   constraints.
2. **Creation**: a real firing webhook produces exactly one `created`
   event, correctly attributed, and the incident's real status
   matches it.
3. **Observation**: a second, newer firing into the same active
   incident produces exactly one additional `observed` event,
   correctly ordered after the creation event.
4. **Operator transition**: a real `PATCH` produces exactly one
   `status_transition` event, `actor_type='operator'`, with the
   correct previous/new status.
5. **Automatic resolution**: a real resolved webhook produces exactly
   one `status_transition` event ending in `resolved`,
   `actor_type='alertmanager'`, and the incident's real final status
   matches it.
6. **Rejected/ignored/no-op operations add nothing**: an illegal
   transition, a stale `expected_status`, a same-status no-op, a
   stale/ignored firing replay, a resolved notification with no
   matching active incident, and a duplicate resolved delivery after
   success all record zero additional events.
7. **Real transaction rollback**: a deliberately invalid audit insert
   (violating `incident_events_created_shape`) issued in the *same*
   real transaction as a real incident `UPDATE` — via one
   multi-statement `psql` invocation under `ON_ERROR_STOP=1` — is
   rejected, and the preceding `UPDATE` is confirmed **not** to have
   persisted either. This is the one check in this phase that cannot
   be approximated at the unit level; it is proven here against a
   real PostgreSQL transaction, not merely asserted to be designed
   that way.
8. **Concurrency**: 10 genuinely concurrent real `PATCH` requests from
   the same `expected_status` produce exactly 1 success and exactly 1
   recorded audit event — never one per loser.
9. **Restart durability**: a real `docker compose restart postgres`
   leaves an incident's full audit timeline byte-for-byte unchanged.
10. **Pre-V3-style incident**: an incident inserted directly (never
    touched by the application) has a genuinely empty timeline —
    `200`, not `404`, and not fabricated.
11. **API validation**: missing incident (`404`), malformed UUID
    (`422`), invalid `limit`/`offset` (`422`).
12. **Pagination beyond the first page** (post-review addition): an
    incident driven through 1 creation + 20 accepted firing
    observations + 1 resolution (22 events total) confirms the
    *default* first page (`limit=20`) genuinely does **not** contain
    the resolving event — reproducing, against the real API, the exact
    gap independent review found in `scripts/verify-ingestion.py`'s
    `verify_audit_trail` — and that fetching all pages (page size 10,
    smaller than the default, to force several real page boundaries)
    yields exactly 22 distinct event ids with no duplicates, the
    resolving event present and correctly attributed.
13. **Historical rows and audit trails remain intact; nothing
    deleted, scoped EXACTLY to this run** (post-review correction — see
    [Testing against real PostgreSQL](#testing-against-real-postgresql)
    below): exactly 10 incidents and exactly 31 audit events, both
    independently hand-traced through every section above and asserted
    as exact counts, not a loose lower bound.

### Testing against real PostgreSQL

**The append-only/`ON DELETE RESTRICT` design has a real, necessary
consequence for every verification script that drives mutations
through the real application:** any incident that is ever created,
observed, PATCHed, or resolved through the real HTTP API now
accumulates real audit history, and — by design — can never be
deleted afterward. Running the *existing* Phase 3C/3D verifiers
(`scripts/verify-webhook-ingestion.sh`,
`scripts/verify-incident-lifecycle.sh`) after this migration landed
confirmed exactly that: both scripts' final cleanup step previously
issued a `DELETE` against their own run-scoped test rows, and both
began failing with a real `foreign key constraint ... violates
RESTRICT` error, because every one of their test incidents is PATCHed
or webhook-ingested at least once.

Both scripts (and this phase's own new `scripts/verify-incident-audit.sh`)
were updated to **retain their test rows permanently** instead of
deleting them — scoped by a UUID unique to each execution so a future
run's rows are never confused with a prior one's, and with an exact
expected audit-event count asserted (not merely "some events exist")
before being left in place. This is the same "genuine state is kept,
never deleted" precedent this repository already established for the
real Collector-outage test's own ingested incidents
(`scripts/verify-alert-lifecycle.sh`) — Phase 3E simply makes this the
*only* option for anything that goes through the real write paths, by
design, rather than merely the status quo for one specific test.
`scripts/verify-persistence.sh` and `scripts/verify-control-plane.sh`
are unaffected: neither ever calls the webhook or the lifecycle
endpoint, so none of their test rows ever accumulate audit history.

**Post-review correction: the original final-count scoping was too
broad.** The first version of `scripts/verify-incident-audit.sh`
scoped its final presence check with `source_fingerprint LIKE
'verify-incident-audit-%'` — which matches not just this run's own
Alertmanager-sourced rows, but *every prior run's* retained rows too
(since, by design, nothing this script creates is ever deleted). That
made an exact-count assertion impossible (only a loose `>= 9` lower
bound was checked) and silently conflated this run's results with
accumulated history from earlier runs. Fixed by scoping to the exact,
unique `TEST_SOURCE` plus the exact Alertmanager fingerprints *this
run itself* generated (`AM_FP`, `stale_fp`, `dup_resolve_fp`, and the
pagination test's own fingerprint) — never a `LIKE` pattern. With that
precise scoping, the script now asserts **exactly 10 incidents and
exactly 31 audit events**, independently re-traced by hand through
every section of the script (direct-insert incidents contribute 0
events unless actually mutated afterward; ignored/rejected operations
contribute 0; `resolved_no_active_fp`, which never creates an incident
at all, is correctly excluded from the scoping).

**V3 and V4 were both verified against a fresh database and the
existing, non-empty development database** (which already held real
historical incidents from earlier Phase 3C/3D/3E sessions, with empty
audit timelines, exactly as expected for pre-Phase-3E rows): both
migrations apply cleanly in both cases, `V1`–`V3`'s own Flyway
checksums are confirmed byte-for-byte unchanged after `V4` applies, and
the append-only/`RESTRICT` enforcement (now including `TRUNCATE`), the
`CHECK` constraints, the index, and the `clock_timestamp()` default all
exist identically in both.

### Real Collector-outage acceptance (`scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`, `make verify-alert-ingestion`)

Extends the exact same real, controlled `otel-collector` outage Phase
2B.4/3C/3D already use — no second Collector failure anywhere in this
repository. `scripts/verify-ingestion.py`'s existing `confirm-resolved`
subcommand (already polled after Collector recovery to confirm real
resolution) now also calls a new `verify_audit_trail` check for each
confirmed incident id: a genuine `created` event and a resolving
`status_transition` event both exist, both are attributed to
`actor_type='alertmanager'` (never `operator` — no human touches an
incident in this fully automated test), and are correctly ordered.

**Post-review correction: `verify_audit_trail` originally read only
the unpaginated first page.** `GET /api/v1/incidents/{id}/events`
defaults to `limit=20`; a long-lived incident that accumulated more
than 20 accepted firing observations before resolving could have its
resolving event lie entirely beyond that first page, in which case the
original check would never see it — a false negative waiting to
happen, not yet triggered only because this particular real outage
test's incidents happen to have very few observations. Fixed with a
new `fetch_all_events` helper that fully paginates (`limit<=100` per
page, looping on `offset`), cross-checking that the API's own reported
`total` stays consistent across pages and that no event id is ever
returned twice, before `verify_audit_trail` inspects the complete
timeline. The real, stress-testing proof that this actually matters —
an incident with more than 20 events, with its resolution genuinely
beyond the default first page — is in
`scripts/verify-incident-audit.sh` (see
[section 12](#real-postgresql-integration-scriptsverify-incident-auditsh-make-verify-incident-audit)
above), not in this Collector-outage script, which was deliberately
left otherwise unchanged (no second outage, no new mechanics).

**A real run confirmed the complete chain end to end**, for the real
incident(s) this outage produced: creation and resolution both
correctly attributed to Alertmanager, with no fabricated operator
intervention, found via the now-paginated fetch, and the whole existing
Collector-outage/recovery/telemetry-resumption proof unchanged.

## Features reserved for Phase 3F

- Incident simulation.
- AI/LLM agents, LangGraph, RAG.
- Automated or human-approved remediation workflows.
- A frontend / operations console consuming any of this.
- Anything beyond the read-only audit timeline API — no generic
  incident-editing API, no audit-creation/mutation/deletion endpoint,
  and (unchanged from Phase 3D) no external identity provider for
  operator actions.
