# Phase 3D: Incident Lifecycle / State Machine

This document describes the real incident lifecycle built on top of
the existing `reliability.incidents` table (Phase 3A) and Alertmanager
webhook ingestion (Phase 3C): the centralized state-transition matrix,
the authenticated human/operator management API, optimistic
concurrency, source-driven automatic resolution, occurrence-identity
and stale-replay handling, the transaction/locking strategy, and how
all of it is verified against real infrastructure.

It does **not** describe the `reliability.incidents` schema itself
(Phase 3A — see [incident-domain-model.md](incident-domain-model.md))
or the basic webhook ingestion mechanics (Phase 3C — see
[phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md)), both
reused here unchanged except where explicitly noted.

## The state-transition matrix

Centralized in one module,
`services/control-plane/src/control_plane/domain/lifecycle.py` — no
other module (not the PATCH endpoint, not the webhook ingestion path,
not any SQL) re-encodes any part of this table itself:

| Current status | May transition to |
|---|---|
| `open` | `acknowledged`, `investigating`, `resolved` |
| `acknowledged` | `investigating`, `resolved` |
| `investigating` | `remediating`, `resolved` |
| `remediating` | `investigating`, `resolved` |
| `resolved` | `closed` |
| `closed` | *(none)* |

Rationale:

- Some incidents recover before anyone acknowledges them, and
  investigation may begin without a separate acknowledgement step —
  hence `open` reaches `resolved` or `investigating` directly.
- Remediation can fail, requiring investigation to resume — hence
  `remediating -> investigating` is legal, not a dead end.
- A resolved incident is never reopened in place; a recurring
  condition produces a brand-new incident (Phase 3A's per-fingerprint,
  status-scoped partial unique index already makes this possible)
  while the previous resolved incident is preserved as history.
- Closing is an explicit administrative action a human takes on an
  already-resolved incident — Alertmanager never performs it
  automatically, and there is no path back out of `closed`.

A request whose `target_status` equals its own `expected_status` is
**not** represented in this table at all (no status lists itself as a
legal transition target) — it is handled as a separate, explicit
no-op case by the API layer (below), never as an entry in the matrix.

**Enforcement boundary, stated accurately:** this table is enforced by
the **application** (`api/incidents.py` for human/operator transitions,
`ingestion/service.py` for Alertmanager-driven resolution) via the
authenticated HTTP API and the webhook's own ingestion logic. It is
**not** a database-level constraint — a privileged SQL client
connecting directly to PostgreSQL can set `status` to any value the
existing `CHECK` constraint (Phase 3A's six-value vocabulary) permits,
bypassing this transition table entirely. The database's own
constraints continue to guarantee the data-integrity invariants from
Phase 3A (valid vocabulary; `resolved_at` set if and only if status is
`resolved`/`closed`) — they do not and cannot know which status
*validly follows* which. This is a deliberate, documented scope
boundary, not an oversight: there is no reasonable way to encode an
ordered state machine with 401/409 semantics for an authenticated HTTP
API inside a `CHECK` constraint.

## Timestamp invariants

All existing Phase 3A `CHECK` constraints are unchanged and continue
to be the authoritative data-integrity rules; Phase 3D adds behavior
on top of them, never around them:

- **Entering `resolved`:** `resolved_at` is set to a timezone-aware
  timestamp (the operator PATCH captures `datetime.now(UTC)` in the
  service layer, matching the ingestion timestamp convention already
  established in Phase 3C; the webhook path uses the alert's own real
  `endsAt`, see below). `first_seen_at` is always preserved. `last_seen_at`
  is never touched by a PATCH transition — only a genuine new firing
  observation (the webhook's firing path) updates it; no observation
  is ever manufactured merely because status changed.
- **`resolved -> closed`:** `resolved_at` is read but never written —
  the UPDATE's `SET` clause simply omits the column, so PostgreSQL
  leaves the existing value completely untouched. The ORIGINAL
  resolution time is never overwritten with the closure time.
- **Active statuses:** `resolved_at` stays `NULL` for every status
  other than `resolved`/`closed`, exactly as Phase 3A's own `CHECK
  (incidents_resolved_at_matches_status)` already requires — Phase 3D
  never attempts to set it for a non-resolving transition.
- **Rejected transitions:** both the "illegal transition" case (checked
  before any database access at all) and the "stale `expected_status`"
  case (the atomic `UPDATE`'s `WHERE` clause matches zero rows) leave
  the entire row — every column, including `updated_at` — completely
  unchanged. Verified directly: `scripts/verify-incident-lifecycle.sh`
  captures `updated_at` before and after a batch of rejected
  transition attempts and asserts byte-for-byte equality.

## Human/operator management API

### `PATCH /api/v1/incidents/{incident_id}/status`

```json
{"expected_status": "open", "target_status": "acknowledged"}
```

Returns the complete updated `Incident` representation (the same
shape `GET /api/v1/incidents/{id}` returns) on success.

`expected_status` is **mandatory**, not optional — it is this
endpoint's optimistic-concurrency guard: the transition is only
applied if the incident's actual current status still matches it at
the exact moment of the atomic `UPDATE`, never a separate
read-then-write (see [Concurrency](#concurrency) below).

| Condition | Status |
|---|---|
| Successful transition (including the same-status no-op) | `200` |
| Illegal transition (not in the matrix above) | `409` |
| Stale `expected_status` (incident exists, but its actual status differs) | `409` |
| Incident UUID does not exist | `404` |
| Malformed UUID, or an invalid/missing field in the request body | `422` |
| Missing/invalid lifecycle credentials | `401` |
| Real database unavailability | `503` |

Both `409` cases share one status code with different `detail`
messages — this keeps the API small (one "conflict with current
state" family) while remaining distinguishable programmatically by
message text if a caller needs to.

**The same-status no-op**, precisely: when `expected_status ==
target_status`, the handler fetches the incident and compares its
actual status to the declared one. If they match, it returns `200`
with the **unmodified** row — no `UPDATE` statement is even issued, so
`updated_at` cannot change. If they don't match, it returns `409` with
the same "stale expected_status" message a real transition attempt
would produce — the no-op path is not exempt from the concurrency
guarantee, it just happens to require zero writes when it succeeds.

**No generic incident-editing API exists or is planned for this
endpoint** — it accepts exactly `{expected_status, target_status}` and
nothing else (`extra="forbid"` on the request model rejects any other
field with `422`).

## Authentication boundaries

Two separate, non-interchangeable Bearer tokens protect this
service's two trusted write paths:

| Token | Protects | Who holds it |
|---|---|---|
| `CONTROL_PLANE_WEBHOOK_TOKEN` (Phase 3C) | `POST /internal/v1/alertmanager/webhook` | Alertmanager only |
| `CONTROL_PLANE_LIFECYCLE_TOKEN` (Phase 3D) | `PATCH /api/v1/incidents/{id}/status` | A human/operator only |

They are checked by `api/auth.py`'s two dependencies
(`require_webhook_token`, `require_lifecycle_token`), both built from
the exact same constant-time comparison helper
(`hmac.compare_digest`) so the guarantee is identical and cannot drift
between them — but they read **different** `app.state` attributes,
set from **different** environment variables, generated as
**independently random** values (never derived from one another).
Alertmanager is only ever given the webhook token (via
`observability/alertmanager/secrets/webhook-token`); it has no way to
learn the lifecycle token, so it cannot invoke the lifecycle endpoint
— by construction, not by convention. Verified directly, both as a
unit test and in `scripts/verify-incident-lifecycle.sh`: presenting the
webhook token to the lifecycle endpoint (and vice versa, in unit
tests) returns `401`.

Both fail closed if their respective environment variable was never
configured — `app.state.webhook_token`/`lifecycle_token` is `None`,
and no supplied value can ever equal `None` via `hmac.compare_digest`.
Neither ever appears in a log line or an HTTP response body, success
or error.

**Post-review correction: identical tokens must also fail closed.**
The whole point of two separate credentials is defeated if they are
ever configured to the SAME value — a single leaked/observed token
would then authorize both write paths. Two independent layers guard
against this:

- `scripts/init-webhook-secret.sh` compares the two final values
  (whether freshly generated or already present in `.env`) and refuses
  to proceed (`exit 1`, secret-free error message) if they are
  identical, rather than silently rotating either one to fix it —
  this script does not know which value (if either) the operator
  actually intended to be correct.
- `core/config.py`'s `resolve_write_tokens(webhook_token,
  lifecycle_token)` is called once at startup (`main.py`'s `lifespan`)
  and catches the case where the initializer above was bypassed
  entirely — an operator hand-editing `.env`, or any other deployment
  mechanism setting both environment variables directly. If both are
  configured and equal, **both** are treated as unconfigured (`None`)
  — every request to either write endpoint then fails closed with
  `401`, exactly as if neither token had ever been set. This does not
  crash the process: the read-only API is completely unaffected, and
  the misconfiguration is logged as an error server-side (never the
  values themselves). Exactly one token being unconfigured continues
  to fail closed only for its own endpoint, unaffected by this check.

Verified directly: a unit test (`tests/test_config.py`) starts a real
`TestClient` with both environment variables set to the identical
value and confirms both the webhook and lifecycle endpoints return
`401` while `GET /api/v1/incidents` still returns `200`; a second,
pure-function test suite exercises `resolve_write_tokens` directly for
every combination (distinct, identical, one/both unconfigured). The
initializer's own refusal was verified manually against a scratch
`.env` with two identical lines.

The read-only `GET /api/v1/*` endpoints remain exactly as
unauthenticated as Phase 3B left them — this phase adds no
authentication to them.

### Secret initialization

`scripts/init-webhook-secret.sh` (extended, not replaced — see
[phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md#secret-initialization)
for the webhook token's own distribution story, unchanged here) now
also manages `CONTROL_PLANE_LIFECYCLE_TOKEN`:

- Generated the same way (`secrets.token_hex(32)`, 256 bits,
  independently from the webhook token).
- Written **only** to `.env` — there is nothing to mirror into a
  second file, since nothing other than this control-plane process
  itself ever needs to read it (no container-user-permission problem
  to solve, unlike the webhook token's Alertmanager-readability story;
  no preflight needed either).
- Same idempotent, `.env`-is-authoritative, never-silently-rotated
  behavior as the webhook token.
- `docker-compose.yml` defaults it to an empty string
  (`${CONTROL_PLANE_LIFECYCLE_TOKEN:-}`) for the same
  config-resolves-before-secret-exists reason as the webhook token.

`make db-up`, `make webhook-secret-init`,
`scripts/verify-webhook-ingestion.sh`, and
`scripts/verify-incident-lifecycle.sh` all invoke this one script —
no second, narrowly-scoped initializer was introduced, per the task's
explicit preference to extend carefully rather than add a parallel
mechanism.

## Concurrency

**A transition must be atomic**, and it is — via a single conditional
`UPDATE`, not an application-level `SELECT` then `UPDATE`:

```sql
UPDATE reliability.incidents
   SET status = :target, resolved_at = :resolved_at  -- resolved_at omitted entirely unless entering resolved
 WHERE id = :id AND status = :expected
RETURNING *;
```

This is PostgreSQL's standard, race-free compare-and-swap pattern.
Two concurrent requests racing from the same `expected_status` cannot
both succeed: PostgreSQL takes a row-level lock on the first `UPDATE`,
blocking the second until the first commits; once unblocked, the
second's `WHERE` clause is **re-evaluated** against the now-current
row and no longer matches (status has already changed) — it affects
zero rows rather than silently overwriting the first transition. No
advisory lock or explicit transaction isolation tuning is needed for
this specific guarantee; it falls out of ordinary row-level locking
under PostgreSQL's default `READ COMMITTED` isolation.

Zero rows returned is deliberately ambiguous (the id might not exist
at all, or might exist with a different actual status) — the route
resolves that ambiguity with exactly one follow-up `get_by_id()` read,
choosing `404` or `409` accordingly.

**Verified directly, not just designed**: `scripts/verify-incident-lifecycle.sh`
fires 10 concurrent `PATCH` requests at the same incident, all
declaring the same `expected_status`. A real run confirmed: exactly 1
of 10 succeeded (`200`), exactly 9 were correctly rejected as stale
(`409`), and the final persisted status was consistent — never
corrupted, never double-applied.

The Alertmanager-driven resolution path
(`resolve_active_incident_for_fingerprint`) uses the identical
single-`UPDATE` pattern, keyed by incident id and
`status NOT IN ('resolved', 'closed')` instead of a specific
`expected_status` (since any active status legitimately resolves) —
independently race-safe against a concurrent operator `PATCH` on the
exact same row for the same underlying reason.

### Coordinating webhook operations: advisory locks

The PATCH endpoint's single-`UPDATE` pattern is sufficient on its own
because a compare-and-swap needs no additional coordination. The
webhook's **firing** path is different: deciding whether an incoming
firing alert represents a repeat of the active occurrence, a stale
replay, or a genuinely new occurrence requires a `SELECT` (or two)
followed by a conditional write — a sequence a single SQL statement
cannot express, and which a second concurrent delivery for the *same*
fingerprint could otherwise race against.

`repositories/incident_repository.py`'s `acquire_fingerprint_lock` uses
PostgreSQL's `pg_advisory_xact_lock`, keyed by
`hashtextextended(source || ':' || fingerprint, 0)` — transaction-scoped,
automatically released at `COMMIT`/`ROLLBACK`, no manual unlock. Every
distinct fingerprint a webhook batch touches (across both its firing
**and** resolved alerts) is locked **up front, in a stable sorted
order**, before any of them are processed — this is what the task
calls out explicitly: acquiring multiple per-fingerprint locks inside
one transaction in a non-deterministic order is exactly how two
concurrent batches touching an overlapping fingerprint set could
deadlock each other. Sorting first eliminates that risk entirely.

This does not replace or weaken Phase 3A's real database
deduplication (`incidents_active_fingerprint_uniq`) with a race-prone
in-memory dictionary — the advisory lock only serializes the
*decision* logic; the actual writes
(`upsert_firing_incident`/`resolve_active_incident_for_fingerprint`)
remain real, atomic, parameter-bound SQL statements, independently
correct even without the lock (the lock exists to protect the
*SELECT-then-decide* sequence specifically, not the final write).

## Source-driven automatic resolution

Phase 3C validated and acknowledged resolved alerts but never acted on
them. Phase 3D now does, through the same existing authenticated
`POST /internal/v1/alertmanager/webhook` endpoint — no new route.

For each alert whose status is `"resolved"`:

1. `domain/alertmanager_webhook.py` requires a genuine, timezone-aware
   `endsAt` not before `startsAt` (rejecting the Go zero-value
   sentinel `"0001-01-01T00:00:00Z"` a still-firing alert carries,
   since year 1 is always before `startsAt`) — `422` otherwise.
2. The matching **active** incident for `(source="alertmanager",
   source_fingerprint)` is looked up.
3. If none is active, the notification is acknowledged and safely,
   idempotently ignored — already resolved by an earlier delivery or a
   concurrent operator `PATCH`, or this fingerprint was never ingested
   at all.
4. If one is active, its occurrence identity is checked (below) before
   resolving it. On success, `resolved_at` is set from the alert's own
   real `endsAt` — the genuine resolution time Alertmanager itself
   reported, not the time this webhook happened to be processed.
5. The incident is **never automatically closed** — `closed` remains
   an explicit administrative action a human takes on an
   already-resolved incident, exactly per the state machine above.

Per-alert status drives this, never the group-level status — a single
delivery's `alerts` array can and does mix firing and resolved
entries.

## Recurrence identity and stale-event handling

This is the most safety-critical part of this phase, and the part
independent review found a real regression in after the first version
shipped — see
[Post-review correction: the occurrence watermark](#post-review-correction-the-occurrence-watermark)
below for the full story. The design described here is the corrected
one; `occurrence_starts_at` (the "watermark") is a real, persistent
column (`database/migrations/V2__add_occurrence_watermark.sql`), not
the original design's `first_seen_at`.

Alertmanager gives each alert a `fingerprint` (stable for the lifetime
of one occurrence) and a `startsAt` (fixed at when that occurrence
began firing). This service treats `(source, fingerprint, startsAt)`
as an occurrence's identity, comparing an incoming alert's `startsAt`
against the matching incident's `occurrence_starts_at` watermark — a
second, independent timestamp that records the LATEST firing `startsAt`
this row has ever accepted, separately from `first_seen_at` (which
keeps meaning exactly what it always meant: when THIS row was first
created, and is never written again after that):

| Incoming alert | Active incident state | Behavior |
|---|---|---|
| Firing, `startsAt == occurrence_starts_at` | Active exists | **Update** it (repeat delivery of the same occurrence); watermark unchanged (already correct) |
| Firing, `startsAt > occurrence_starts_at` | Active exists | **Update** it, and **advance the watermark** to this `startsAt` |
| Firing, `startsAt < occurrence_starts_at` | Active exists | **Ignore** — stale/delayed replay of an occurrence this row has since moved past |
| Firing, `startsAt <= most recent historical row's occurrence_starts_at` | None active | **Ignore** — stale replay of an occurrence that row already accepted (as its latest) before resolving |
| Firing, `startsAt` strictly newer than any known row's watermark (or none exists) | None active | **Create** a new incident; prior history untouched |
| Resolved, `startsAt == occurrence_starts_at` | Active exists | **Resolve** it — the only case that resolves |
| Resolved, `startsAt != occurrence_starts_at` (older OR newer) | Active exists | **Ignore** — see below |
| Resolved (any `startsAt`) | None active | **Ignore** — safe, idempotent no-op |

The resolved-alert comparison is **exact equality**, not "equal or
newer" — deliberately, for two distinct reasons that an ordering
comparison conflates:

- `startsAt` strictly **older** than the watermark: a delayed resolved
  notification for an occurrence this row has already moved past
  (e.g. occurrence A's resolved notification arriving after a newer
  firing B already updated this same row and advanced the watermark).
  Must never resolve the incident using stale evidence for the
  occurrence it superseded.
- `startsAt` strictly **newer** than the watermark: a resolved
  notification for an occurrence that was never observed firing at
  all. This service has no positive evidence that this notification
  pertains to the row's current occurrence rather than some future one
  it simply hasn't seen fire yet — rather than *blindly* resolving an
  incident on a guess, it conservatively ignores the notification. See
  [Documented limitation](#documented-limitation-of-the-alertmanager-webhook-event-model)
  below.

### Post-review correction: the occurrence watermark

**The regression, reproduced exactly.** The first version of this
phase compared an incoming alert's `startsAt` against the matching
incident's `first_seen_at` — which seemed sufficient at the time (see
the account below of the *first* real bug this uncovered), but
independent review identified a deeper problem with using an immutable
column as the comparison basis at all. Concretely:

1. Occurrence A fires (`startsAt=10:00`) → creates incident X,
   `first_seen_at=10:00`.
2. Occurrence B fires (`startsAt=11:00`) while X is still active (A was
   never resolved) → **updates** X in place (the "firing newer than
   the active incident" branch) — but `first_seen_at` is deliberately
   never advanced by design, so it stays `10:00` even though X now
   genuinely represents B, not A.
3. B resolves (`startsAt=11:00`) → X transitions to `resolved`.
4. A **delayed, duplicate firing replay of B** (`startsAt=11:00`)
   arrives after step 3. Comparing against X's own `first_seen_at`
   (`10:00`, still A's value) makes `11:00` look like a **genuinely
   new** occurrence (`startsAt` newer than the only historical row's
   `first_seen_at`) — so a **second, spurious incident** is
   incorrectly created for what is actually just a stale replay of the
   occurrence X already handled.

A symmetric defect existed on the resolution side: if step 3 had
instead been "a delayed resolved notification for the *original*
occurrence A (`startsAt=10:00`) arrives while X is still active and
already representing B" — comparing against the unchanged
`first_seen_at` (`10:00`) makes A's resolved notification look like an
exact match, incorrectly resolving X even though X no longer
represents A.

**The fix.** A second, narrowly-scoped, durable column,
`occurrence_starts_at` (`database/migrations/V2__add_occurrence_watermark.sql`),
records the latest accepted firing `startsAt` separately from
`first_seen_at`:

- On a genuine new `INSERT`, it equals `first_seen_at` (the same
  alert's `startsAt`).
- On every accepted firing update to an already-active incident
  (`repositories/incident_repository.py`'s `upsert_firing_incident`),
  it advances via `GREATEST(existing, new)` — the same
  tolerance-of-out-of-order-delivery idiom `last_seen_at` already
  uses. `first_seen_at` itself is still never touched after creation.
- It is backfilled for every pre-existing row from that row's own
  `first_seen_at` (the correct, safe default: no row could possibly
  have accepted a "latest firing" more recent than its own
  `first_seen_at` before this column — and the logic that advances it
  — existed at all).
- A `CHECK (occurrence_starts_at >= first_seen_at)` constraint
  (mirroring the existing `incidents_last_seen_not_before_first_seen`
  convention) keeps the invariant enforced at the database level, not
  just in application code.

Replaying the exact regression above against the fixed code: step 2
now advances X's watermark to `11:00` (not `first_seen_at`, which stays
`10:00`). Step 4's delayed duplicate replay of B (`startsAt=11:00`) is
now compared against the **watermark** (`11:00`, since X is resolved
by then, this uses `get_most_recent_incident`'s watermark-ordered
lookup) — `11:00 <= 11:00` is true, so it is correctly recognized as a
stale replay and ignored; no second incident is created. The symmetric
resolution-side case is fixed the same way: a delayed resolved
notification for A (`startsAt=10:00`) compared against X's watermark
(`11:00`, since B already updated it) is `10:00 != 11:00` — ignored,
never resolving X on stale evidence for the occurrence it superseded.

**No audit-history table was introduced** to fix this (that remains
explicitly Phase 3E); the watermark is the single, narrowly-scoped
piece of new persistent state the fix actually requires. The existing
partial unique index, atomic upsert, and deterministic advisory-lock
ordering are all unchanged — only the column each comparison reads
from changed.

**Re-verified, not just reasoned through.** `scripts/verify-incident-lifecycle.sh`
(sections 8-10) reproduces this exact timeline against the real
database — a newer firing into a still-active incident, a real
PostgreSQL restart proving the watermark itself is durable, a delayed
resolved notification for the superseded occurrence correctly rejected,
B resolving via its own `startsAt`, a delayed duplicate firing replay
after resolution correctly rejected, and a genuinely new later
occurrence still creating a new incident. New unit tests
(`test_delayed_resolved_for_superseded_occurrence_does_not_resolve_active_incident`,
`test_delayed_duplicate_firing_after_occurrence_resolved_does_not_create_incident`,
`test_resolved_notification_matching_watermark_resolves_incident`,
`test_resolved_notification_for_unobserved_newer_occurrence_does_not_resolve_active_incident`,
`test_genuine_subsequent_occurrence_after_watermark_advance_creates_new_incident`)
cover the same scenarios at the mock level, with `conftest.py`'s fake
repository updated to model real watermark semantics (advancing via
`max()`, ordering `get_most_recent_incident` by it) rather than
approximating the old, incorrect behavior.

### An earlier real bug this phase's own testing found (pre-review)

Before the watermark fix above, a separate real-infrastructure test
run had already found and fixed a related, narrower gap: the very
first implementation required **exact equality** between an incoming
firing alert's `startsAt` and the active incident's `first_seen_at`,
treating any mismatch as "ignore." A real incident that had never been
resolved (from an earlier test session) stayed permanently stuck,
since every subsequent real firing carried a newer `startsAt` that
never exactly matched. That fix — switching the *firing-side*
comparison from equality to "ordering against `first_seen_at`" — was
necessary but, as the regression above shows, not sufficient on its
own: it fixed the "accept a newer firing" case while leaving
`first_seen_at` as the thing everything else was still compared
against, which is exactly what let the new regression through. The
watermark column is what actually closes the gap for good, by giving
every comparison a value that advances *with* the incident rather than
staying fixed at creation.

### Documented limitation of the Alertmanager webhook event model

Alertmanager's webhook payload does not include any explicit sequence
number or "occurrence generation" marker beyond `fingerprint` +
`startsAt` — this service's occurrence-identity logic is built
entirely on the ordering of those two fields against the watermark.
Two specific, accepted gaps follow directly from that:

- In the out-of-order scenario where a **genuinely new, later**
  occurrence's firing notification arrives *before* the *old*
  occurrence's resolved notification (both for the same fingerprint,
  with no properly-resolved gap in between), this service cannot
  create a separate row for the new occurrence — the partial unique
  index would reject a second active row, and by design there is only
  ever at most one active row per fingerprint. It instead updates the
  existing active row in place and advances its watermark, which is
  the correct, safe choice given the real constraint, but means the
  incident's `first_seen_at` continues to reflect whenever the row was
  first created, not necessarily the true start of whichever
  occurrence is "really" active at that exact moment.
- A resolved notification for an occurrence that was never observed
  firing (`startsAt` strictly newer than the current watermark) is
  always ignored rather than resolved — see the equality-comparison
  rationale above. If Alertmanager ever delivers a resolved
  notification without this service having first seen the
  corresponding firing notification at all (not merely delayed, but
  genuinely never delivered), that occurrence's incident will not be
  automatically resolved by this mechanism; it would still be
  resolvable manually via the `PATCH` endpoint.

Both are judged acceptable: the alternative to the first (deleting
history, or allowing more than one active row per fingerprint) was
explicitly out of scope, and real Alertmanager delivery in practice
resolves an occurrence before firing a new one in the vast majority of
cases; the alternative to the second (resolving on "equal or newer")
is exactly the unsafe behavior independent review flagged and this
correction removes.

## Single-transaction webhook batches

Unchanged from Phase 3C's design, extended: the full payload is
validated before any incident write begins; every alert in a batch —
firing and resolved alike — is processed within the **one** implicit
transaction the request's `AsyncSession` opens, committed exactly
once at the end. If anything raises mid-batch, commit is never
reached, and the session's rollback-on-close means **none** of that
batch's writes persist — never a partial write. A real database
failure surfaces as `503` (via the existing global `SQLAlchemyError`/
`OSError` handlers, unchanged) so Alertmanager's own retry behavior can
redeliver later.

`WebhookAckResponse` now distinguishes `firing_processed`,
`resolved_processed` (counts of each alert type in the batch),
`incidents_created`, `incidents_updated`, `incidents_resolved`, and
`incidents_ignored` (stale/mismatched firing or resolved events safely
skipped, for any of the reasons in the table above) — replacing Phase
3C's `resolved_ignored` field, which specifically encoded "resolved
alerts are always ignored" semantics that are no longer accurate.
Existing Phase 3C tests that depended on the old field name/semantics
were updated, not silently weakened — every original assertion's
*intent* (authentication, deduplication, transaction atomicity) is
still fully covered, just expressed against the new, more precise
response shape.

## Error handling

| Condition | Status | Notes |
|---|---|---|
| Illegal transition | `409` | Checked before any database access; row guaranteed unchanged |
| Stale `expected_status` | `409` | Same message shape as illegal transition, different cause |
| Incident not found | `404` | |
| Malformed UUID / invalid request body | `422` | `extra="forbid"` rejects unknown fields too |
| Missing/incorrect lifecycle credentials | `401` | Including presenting the *webhook* token here |
| Real database unavailability | `503` | Reuses the existing global handlers unchanged |

No credential ever appears in a response body or log line, in any of
these cases — verified by a dedicated unit test asserting the
configured lifecycle token string never appears in any `401`/`503`
response text.

## Schema / migration

The state machine and concurrency-control mechanisms (the PATCH
endpoint's compare-and-swap `UPDATE`, the webhook's advisory locks) are
pure application code against the unmodified Phase 3A schema — no
migration needed for those.

**The occurrence-identity logic is different: it required one new,
narrowly-scoped column.** Independent review found that comparing
against the immutable `first_seen_at` was unsafe once an incident could
accept more than one firing observation while still active (see
[Post-review correction: the occurrence watermark](#post-review-correction-the-occurrence-watermark)
above). `database/migrations/V2__add_occurrence_watermark.sql` adds
`occurrence_starts_at` (`TIMESTAMPTZ NOT NULL`, backfilled from each
existing row's own `first_seen_at`, with a
`CHECK (occurrence_starts_at >= first_seen_at)` constraint) —
genuinely new persistent state, not a workaround. `database/migrations/V1__create_incident_schema.sql`
was never edited; `V2` is purely additive. No audit-history table
(explicitly Phase 3E) was added prematurely, and no new index was
added — per-fingerprint row counts stay low by design (the existing
partial unique index and `incidents_status_idx` already scope every
lookup), so ordering a handful of candidate rows needs no dedicated
index, exactly as `first_seen_at DESC` never needed one either.

**Verified against both a fresh database and the existing, real
development database** (which already held two real historical
incidents from earlier Phase 3C/3D sessions): `V2` applies cleanly in
both cases, backfills `occurrence_starts_at = first_seen_at` for the
pre-existing rows exactly, and the `CHECK` constraint correctly rejects
an out-of-order insert. Re-running `flyway migrate` against an
already-migrated database remains a safe no-op (`Schema "reliability"
is up to date`), unchanged from Phase 3A's own guarantee.

**A new `NOT NULL` column with no default affects every direct SQL
`INSERT` into this table, not just application code.** Running the
*existing* Phase 3A/3B verifiers after adding this column surfaced
exactly that: `scripts/verify-persistence.sh` and
`scripts/verify-control-plane.sh` both insert test rows directly via
`psql` (there being no incident-creation HTTP API for either of those
phases to use), and every one of those `INSERT` statements needed
`occurrence_starts_at` added — otherwise they failed with an unrelated
`NOT NULL violation` (SQLSTATE `23502`) instead of exercising whatever
constraint each test actually means to check. This is a real,
necessary consequence of the migration, not optional cleanup: both
scripts were fixed and re-run end to end, confirmed passing with no
other change in behavior.

## Verification

### Unit tests

`services/control-plane/tests/test_lifecycle.py` (new): every
permitted transition (parametrized over the full matrix), every
forbidden transition (including same-status pairs, confirmed rejected
by the pure state-machine function directly), the same-status no-op
(both the clean-match and stale-actual-status cases), missing
incident, invalid UUID, invalid target/expected status, an unknown
extra field, missing/incorrect lifecycle credentials, the lifecycle
token rejected by the webhook endpoint and vice versa, an unconfigured
token failing closed, `resolved_at` set on resolution and preserved on
closure (and staying `NULL` for every non-resolving transition),
timestamps completely unchanged on a rejected transition, resolved/
closed never regressing, a real database error returning `503`, and —
a regression test for a bug this exact development process found — a
successful transition actually calling `commit()` (a route that
returns `200` without it looks correct against the mocked repository,
which has no real transaction to roll back, but silently discards the
write against the real database once the session closes).
`test_webhook.py` gained the Alertmanager-side counterpart: genuine
resolution of a matching active incident, idempotent duplicate
resolution, a stale resolved notification unable to resolve a newer
recurrence, a stale firing unable to recreate a resolved incident, a
genuine recurrence creating a new incident while preserving history,
the "firing newer than the active incident's watermark still updates
it (and advances the watermark)" case, and the full post-review
regression suite: a delayed resolved notification for a superseded
occurrence rejected, a resolved notification matching the watermark
exactly resolving the incident, a resolved notification for an
unobserved newer occurrence rejected, a delayed duplicate firing replay
after resolution rejected, and a genuinely new occurrence after a
watermark advance still creating a new incident. A new
`tests/test_config.py` covers the identical-webhook/lifecycle-token
guard: the pure `resolve_write_tokens` function for every input
combination, plus an end-to-end `TestClient` test confirming both
write endpoints fail closed (and the read API stays unaffected) when
both tokens are configured identically. `make control-plane-test`:
**171 tests, all passing.**

### Real PostgreSQL integration (`scripts/verify-incident-lifecycle.sh`, `make verify-incident-lifecycle`)

Against the real running service and real PostgreSQL, 14 sections:
creates a run-scoped incident, confirms its initial `open` status via
HTTP matches the database (1); walks every permitted transition along
two separate real paths, confirming the database matches the HTTP
response at each step — `resolved_at` is captured immediately after
entering `resolved` (a post-review fix: the original version captured
it only after the subsequent `resolved -> closed` transition had
already run, so the "preserved across closure" assertion was
comparing the already-closed row's value to itself and could never
have caught a real regression), then `resolved -> closed` is driven as
its own explicit step, and `resolved_at` is re-read and compared (2,
3); rejects three different illegal transitions and a stale
`expected_status`, confirming the row (including `updated_at`) is
completely unchanged in every case (4, 5); confirms the lifecycle
endpoint rejects no-auth, wrong-token, and (critically) the *webhook*
token (6); confirms a malformed UUID, a nonexistent UUID, and an
invalid `target_status` each get the correct status code (7); drives
the occurrence-watermark regression scenario up through the
still-active "B updates X in place, watermark advances" step (8);
confirms status, `resolved_at`, **and the occurrence watermark itself**
all survive a real `docker compose restart postgres` — reusing this
same restart rather than performing a second one (9); continues the
watermark scenario — a delayed resolved notification for the
superseded occurrence A is correctly rejected, B resolves via its own
`startsAt`, a delayed duplicate firing replay of B after resolution is
correctly rejected, and a genuinely new occurrence C still creates a
new incident, preserving history (10); drives the original
(pre-review) occurrence-identity scenario through the actual webhook
endpoint — resolve occurrence A, recur as a distinct incident B,
confirm a delayed firing/resolved notification for A touches neither B
nor creates anything new (11); fires 10 genuinely concurrent `PATCH`
requests from the same `expected_status` and confirms exactly one wins
(12); confirms all 9 rows this run created are still present and
accounted for (13); and performs a final, count-verified, run-scoped
cleanup (14). **All 14 sections passed** on a real run, with the EXIT
trap tested directly (see
[phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md) for the
analogous pattern this script reuses) to confirm a mid-run failure
still restores PostgreSQL and reports the original failure's exit
code, not whatever the trap's own cleanup commands returned.

### Real Collector-outage acceptance (`scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`, `make verify-alert-ingestion`)

Reuses the exact same real, controlled `otel-collector` outage Phase
2B.4/3C already use — no second Collector failure anywhere in this
repository. After the existing recovery confirmation (Prometheus back
to `inactive`, Alertmanager reporting no active alert for the rule),
a new step polls `scripts/verify-ingestion.py confirm-resolved` against
the exact incident ids the earlier ingestion step confirmed
(`--ids-out`/`--ids-file`), proving — read-only, never a synthetic
POST — that Alertmanager's own real resolved webhook delivery
genuinely transitioned them to `status="resolved"` with a populated
`resolved_at`. **A real run confirmed the complete chain end to end**:
`TelemetryPipelineUnavailable` went inactive → firing (real outage,
`active_series=2`) → both instances confirmed as real, correctly-mapped
incidents → Collector restarted → Prometheus/Alertmanager recovered →
both incidents confirmed genuinely resolved with `resolved_at`
populated → fresh checkout telemetry confirmed resumed. An earlier run
of this same test (before the occurrence-watermark correction) is what
originally surfaced the pre-review `first_seen_at`-equality bug
described above — the two incidents it resolved had been stuck `open`
since an even earlier session, and the fixed code resolved them for
real at the time, not via any workaround. This phase's final
re-verification (after the watermark correction) re-ran the identical
real Collector-outage cycle once more end to end — ingestion and
resolution both still passed — rather than assuming the earlier result
still held.

## Post-review corrections summary

Independent review of the first version of this phase found three
real problems, all fixed and re-verified against the real stack:

1. **Occurrence watermark** (the most significant) — comparing against
   the immutable `first_seen_at` instead of a durable watermark could
   let a delayed resolved notification for a superseded occurrence
   incorrectly resolve an incident, and let a delayed duplicate firing
   replay after resolution incorrectly spawn a second incident. Fixed
   with a new `occurrence_starts_at` column
   (`database/migrations/V2__add_occurrence_watermark.sql`) and
   corrected comparison logic throughout `ingestion/service.py` — see
   [Post-review correction: the occurrence watermark](#post-review-correction-the-occurrence-watermark)
   above.
2. **`scripts/verify-incident-lifecycle.sh`'s `resolved_at`-preservation
   assertion was vacuous** — it captured `resolved_at` only after the
   `resolved -> closed` transition had already run, so it was
   comparing the already-closed row's value to itself. Fixed by
   capturing it immediately after entering `resolved`, then driving
   the closure as its own explicit step before re-reading and
   comparing.
3. **Identical webhook/lifecycle tokens were never explicitly
   rejected** — an operator could configure both to the same value
   (defeating the reason they are two separate credentials) without
   any error. Fixed with two independent guards:
   `scripts/init-webhook-secret.sh` now refuses to proceed if the two
   final values are identical, and `core/config.py`'s
   `resolve_write_tokens` is a second, application-level guard that
   catches the same misconfiguration even if the initializer is
   bypassed entirely — see
   [Post-review correction: identical tokens must also fail closed](#authentication-boundaries)
   above.

All three were reproduced (where applicable) and then re-verified
fixed against the real stack: `make control-plane-test` (171 passed),
`make verify-incident-lifecycle` (all 14 sections passed, including
the exact watermark regression timeline and the corrected
`resolved_at` ordering), `make verify-webhook-ingestion` (all sections
still passed — no Phase 3C regression), and one final
`make verify-alert-ingestion` run using the single existing real
Collector-outage cycle (ingestion and resolution both passed).

## Features reserved for Phase 3F

Implemented since this document was first written, by Phase 3E,
without changing anything described above: a durable, append-only
incident audit-history table recording every accepted creation,
observation, operator transition, and automatic resolution — see
[docs/architecture/phase-3e-incident-audit.md](phase-3e-incident-audit.md).

Still reserved for Phase 3F:

- Incident simulation, agent-generated remediation decisions, root-
  cause analysis, RAG, LangGraph.
- Human approval workflows for remediation.
- Automated infrastructure remediation of any kind.
- A frontend / operations console consuming any of this.
- An external identity provider — the two Bearer tokens remain local-
  development security, not a production identity platform.
- Generic arbitrary incident-editing endpoints — the only write shapes
  that exist are the one status-transition PATCH and the one
  Alertmanager webhook; neither is a general-purpose incident editor.
