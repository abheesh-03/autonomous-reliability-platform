# Incident Domain Model (Phase 3A)

This document describes the durable incident-data foundation built in
Phase 3A: the `reliability.incidents` table, its constraints, its
deduplication policy, and how migrations and persistence are verified.
It does **not** describe incident *ingestion* (turning a real
Alertmanager alert into a row here — Phase 3C) or incident *lifecycle
transitions* (Phase 3D). Those are explicitly out of scope for this
phase; see [Planned functionality](#planned-functionality-not-yet-implemented)
below.

## Where this fits

```
Prometheus + Alertmanager
          |
          | Future Phase 3C (not built yet)
          v
       Incident
          |
          v
      PostgreSQL  <-- Phase 3A (this document)
```

Phase 3A builds the **incident model and database persistence only**.
There is no API, no ingestion from Alertmanager, and no application
code reading or writing this table yet — it exists so a future FastAPI
control plane (Phase 3C+) has a durable, constrained place to persist
incidents into, verified independently of that future code.

## Database and schema

Reuses the existing `postgres` Docker Compose service (`postgres:18`,
the same persistent `postgres_data` named volume already used since
Phase 0.2) — no second database was introduced. All Phase 3A objects
live in a dedicated `reliability` schema, created by the migration
itself, never in `public`. On this project's long-running local
database, `public` also holds an unrelated pre-existing table,
`public.phase_02_verification` (a single row, `id=1,
message='persistent'`) — but this table is **not** a Phase 3A
dependency and is not expected to exist on a fresh database (e.g. a new
GitHub Actions `postgres_data` volume, or a developer's first
checkout). Phase 3A never reads, writes, migrates, creates, or deletes
anything in `public`; `scripts/verify-persistence.sh` detects whether
this fixture happens to be present, and if so, re-confirms its value is
unchanged both before its own test run and again after a PostgreSQL
restart — but proceeds normally either way if it is absent.

## The `incidents` table

`reliability.incidents`, created by
`database/migrations/V1__create_incident_schema.sql`:

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `gen_random_uuid()` | Primary key. |
| `source` | `TEXT` | NOT NULL | — | Originating monitoring system (e.g. `"alertmanager"`). Free text, not an enum, since a future phase may add other sources; only required to be non-blank. |
| `source_fingerprint` | `TEXT` | NOT NULL | — | Stable external identifier used for deduplication, scoped to `(source, source_fingerprint)` — see [Deduplication policy](#deduplication-policy) below. For an Alertmanager-originated incident this is expected to derive from the alert's own fingerprint/labels in Phase 3C; this phase only requires it be non-blank. |
| `title` | `TEXT` | NOT NULL | — | Short human-readable incident title. Must be non-blank. |
| `description` | `TEXT` | nullable | — | Optional longer description. |
| `severity` | `TEXT` | NOT NULL | — | One of `critical`, `warning`, `info`. |
| `status` | `TEXT` | NOT NULL | `'open'` | See [Status vocabulary](#status-vocabulary-and-default-initial-status) below. |
| `first_seen_at` | `TIMESTAMPTZ` | NOT NULL | — | First detection timestamp. |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL | — | Most recent occurrence timestamp. Must be `>= first_seen_at`. |
| `resolved_at` | `TIMESTAMPTZ` | nullable | — | Set if and only if `status` is `resolved` or `closed` (enforced by a CHECK constraint — see below). |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | Database row creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()`, then auto-maintained | Last modification timestamp — a `BEFORE UPDATE` trigger (`reliability.set_updated_at()`) sets this to `now()` on every update, regardless of which client performs it. |

Every timestamp column is `TIMESTAMPTZ` (not bare `TIMESTAMP`), per the
task's explicit requirement — Postgres normalizes these to UTC
internally and converts to/from the client's session timezone, so
there is no local-timezone ambiguity stored in the database.

### Status vocabulary and default initial status

Six statuses are defined and enforced by a `CHECK` constraint
(`incidents_status_check`):

- `open` — detected, not yet acknowledged by anyone/anything.
- `acknowledged` — a human or agent has acknowledged the incident.
- `investigating` — actively being investigated.
- `remediating` — remediation is in progress.
- `resolved` — the underlying condition has cleared.
- `closed` — resolved and administratively closed/archived.

**Default initial status:** omitting `status` on `INSERT` yields
`'open'` (the column's `DEFAULT`), paired with `resolved_at = NULL`.
This is a default, **not an enforced creation-time invariant** — the
database does not currently prohibit a caller from explicitly inserting
a row with a different valid status (e.g. `status = 'investigating'` on
`INSERT` succeeds today; only the status-vocabulary `CHECK` restricts
*which* values are legal at all, not which one a new row must start
with). This phase enforces only two things: that the vocabulary itself
is a closed set (the CHECK constraint), and that `resolved_at`'s
nullability always agrees with whether `status` is a resolved-type
status (`incidents_resolved_at_matches_status`, a data-integrity rule,
not a transition rule — see below). It does **not** enforce which
status transitions are legal (e.g. that `open` cannot jump directly to
`closed`, that `resolved` cannot regress to `open`, or that every
incident must in fact start life as `open`) — **that is explicitly
deferred to Phase 3D**, which will implement real lifecycle/creation
transition logic (most likely a trigger or an application-layer state
machine, to be decided then). Implementing that now would mean
designing transition rules before there is any real caller to validate
them against, which this phase's scope explicitly avoids.

### Constraints

All enforced by PostgreSQL itself, not left to a future Python layer:

- `incidents_pkey` — `PRIMARY KEY (id)`.
- `incidents_source_check` — `source` must be non-blank (`btrim(source) <> ''`).
- `incidents_source_fingerprint_check` — `source_fingerprint` must be non-blank.
- `incidents_title_check` — `title` must be non-blank.
- `incidents_severity_check` — `severity IN ('critical', 'warning', 'info')`.
- `incidents_status_check` — `status` in the six-value vocabulary above.
- `incidents_last_seen_not_before_first_seen` — `last_seen_at >= first_seen_at`.
- `incidents_resolved_at_matches_status` — `resolved_at IS NOT NULL` iff `status IN ('resolved', 'closed')`.
- `incidents_active_fingerprint_uniq` — see immediately below.

### Deduplication policy

**Identity:** an incident's deduplication identity is the pair
`(source, source_fingerprint)`.

**Uniqueness policy:** at most **one active incident** may exist per
`(source, source_fingerprint)` at any time, where "active" means
`status NOT IN ('resolved', 'closed')`. This is enforced by a real
PostgreSQL **partial unique index**:

```sql
CREATE UNIQUE INDEX incidents_active_fingerprint_uniq
    ON reliability.incidents (source, source_fingerprint)
    WHERE status NOT IN ('resolved', 'closed');
```

A second `INSERT` with the same `(source, source_fingerprint)` while
the first is still active fails with a real `unique_violation`
(SQLSTATE `23505`, reported against the `incidents_active_fingerprint_uniq`
constraint by name) at the database level — not a race-prone
check-then-insert pattern implemented in application code. The
protection this provides under real concurrent writers comes entirely
from PostgreSQL's own index enforcement, which is applied atomically to
every `INSERT` regardless of what else is happening at the same time;
this is a property of how a unique index works, not something this
phase additionally had to build. `scripts/verify-persistence.sh`'s own
test of this (see
[Persistence verification](#persistence-verification) below) is a
**sequential** check — one `INSERT`, then a second, over the same
connection — not an empirical two-session/two-connection race test; it
confirms the constraint rejects a duplicate when exercised, not that it
was stress-tested under genuine concurrent load. This directly
satisfies the motivating requirement: if a future Alertmanager
integration (Phase 3C) re-sends the same firing alert multiple times —
including, in principle, two near-simultaneous deliveries — it cannot
spawn unlimited (or even two) duplicate active incidents.

Because the index is **partial** (scoped to non-resolved/closed rows
only), once an incident's `status` moves to `resolved` or `closed`, it
drops out of the uniqueness scope and is **never deleted or
overwritten** — it remains in the table as history. A brand new
incident with the same `(source, source_fingerprint)` is then free to
be created (e.g. the same underlying condition recurring later), and
both the old (resolved/closed) and new (active) rows coexist — this
was verified directly: resolving the first incident, then inserting a
second with the identical fingerprint, succeeds and leaves exactly two
rows for that fingerprint.

Phase 3A does not implement this dedup check inside any Python code —
there is no Python application code in this phase at all. The database
constraint is the entire enforcement mechanism for now; a future
ingestion service (Phase 3C) will rely on this same constraint (e.g.
catching the unique-violation and upserting/bumping `last_seen_at`
instead) rather than re-implementing the check itself.

### Indexes

- `incidents_pkey` — primary key lookup by `id`.
- `incidents_active_fingerprint_uniq` — the partial unique index above; also serves as the lookup path for "is there already an active incident for this fingerprint?".
- `incidents_status_idx` — filtering/dashboards by `status`.
- `incidents_severity_idx` — filtering by `severity`.
- `incidents_last_seen_at_idx` (`DESC`) — listing/sorting by recency, the expected default view for a future control plane.

## Migration strategy

**Tool: Flyway OSS, pinned to `flyway/flyway:13.9.0`.** Version
selection was done empirically, not assumed: every tag from `11` up to
`13.9.0` was pulled and inspected (`--version`), confirming `13.9.0` is
the genuine current latest stable release (no `13.10.0`, no `14.x`
exists). Compatibility with the pinned `postgres:18` image was also
confirmed empirically before adoption — a real migration was run
against a live `postgres:18.6` container and Flyway's own log
confirmed `Database: jdbc:postgresql:... (PostgreSQL 18.6)` with no
compatibility warnings.

**Layout:**

```
database/
  migrations/
    V1__create_incident_schema.sql
```

Standard Flyway versioned-migration naming (`V<version>__<description>.sql`).
Future migrations will be added as `V2__...`, `V3__...`, etc. — never
editing an already-applied migration file (Flyway's checksum
validation makes that a hard failure, confirmed directly: editing
`V1__create_incident_schema.sql` after it had been applied and
re-running `migrate` produced `ERROR: Validate failed: Migrations have
failed validation — Migration checksum mismatch for migration version 1`,
a real, reproduced failure, not an assumed one).

**How migrations run:** via a dedicated `flyway` Docker Compose service
(pinned image, `FLYWAY_SCHEMAS=reliability`, mounts
`database/migrations/` read-only). It uses Compose's `profiles: [tools]`
mechanism, so it is **never started** by a normal `docker compose up
-d` — only by an explicit invocation:

```bash
make db-migrate
# equivalent to: docker compose run --rm flyway migrate
```

This means migrations do **not** run on every application
request/startup (the task's explicit constraint) — they run once, as a
deliberate deploy step, identically on macOS and Linux since it is
entirely Docker-based (no host-installed PostgreSQL client or Flyway
binary required).

**Re-running is safe:** confirmed directly — running `make db-migrate`
against an already-migrated database reports `Schema "reliability" is
up to date. No migration necessary.` and exits 0, making no changes.

**Migration history tracking / checksum validation:** Flyway's own
`reliability.flyway_schema_history` table (created automatically,
inside the `reliability` schema, never `public`) records every applied
migration's version, description, checksum, and timestamp; every
`migrate` invocation first validates already-applied migrations'
checksums against the files on disk, so an edited previously-applied
migration is always caught (see above).

**No destructive resets:** nothing in this phase's migration tooling
or verification ever runs `DROP SCHEMA`/`docker compose down -v` /
deletes `postgres_data` — `scripts/verify-persistence.sh` explicitly
never does this, and its own cleanup step deletes only the exact rows
this specific run created (see
[Persistence verification](#persistence-verification) below for the
run-scoping mechanism).

## Persistence verification

`scripts/verify-persistence.sh` (reused identically by CI) runs
against the **real** `postgres:18` and `flyway/flyway:13.9.0` images —
not SQLite, not a mocked repository, not an in-memory/simulated
database. It is safe to re-run against a nonempty local database, and
safe on a completely fresh one (e.g. CI): every test row is scoped
under a marker unique to that specific execution — `source =
'verify-persistence-test'` **and** `source_fingerprint LIKE
'verify-persistence-test-<this run's UUID>%'`, where the UUID is
generated fresh (`python3 -c 'import uuid; print(uuid.uuid4())'`) each
time the script runs — and its cleanup step deletes only rows matching
that exact run's marker, leaving any other run's test rows (e.g. a
previous invocation that was never cleaned up) and all real data
untouched. On the happy path, that cleanup is not suppressed: if it
fails, the script fails. A separate, best-effort-only cleanup also runs
from an `EXIT` trap (scoped identically to the specific run), so that
if an earlier check fails first, at least an attempt is made to remove
that run's partial data — without masking the original failure, and
without ever touching another run's rows.

What it proves, in order: PostgreSQL becomes healthy; the optional
Phase 0 fixture (`public.phase_02_verification`) is detected if present
and its value recorded, or the script proceeds normally if it is
absent; migrations apply successfully; the expected schema/table/
indexes exist; a valid incident can be inserted and read back, with a
well-formed UUID, populated timestamps, `resolved_at IS NULL`, and the
default status (`open`) when `status` is omitted on `INSERT`; an
invalid `severity` and an invalid `status` are each rejected with
exactly `SQLSTATE 23514` (`check_violation`), verified from PostgreSQL/
psql's own verbose error output, not merely "the command failed" (a
connection error, a SQL syntax error, or a missing-table error would
report a *different* SQLSTATE and correctly fail the check instead of
being mistaken for a passing constraint rejection); blank `title`/
`source`/`source_fingerprint` are each rejected the same way
(`23514`); a duplicate active `(source, source_fingerprint)` is
rejected with exactly `SQLSTATE 23505` (`unique_violation`) **and**
psql's verbose output confirmed to name the
`incidents_active_fingerprint_uniq` constraint specifically — and, the
other half of the same policy, a new active incident with the same
fingerprint succeeds once the original is resolved, with both rows
preserved; all five expected indexes exist; re-running the migration is
a safe no-op; PostgreSQL survives a graceful restart (`docker compose
restart postgres`, not `-v`) with the inserted incident(s) still
present and correct; the Phase 0 fixture, if it was present, is
re-confirmed unchanged after the restart; and finally only this run's
own test rows are deleted, with the exact row count removed checked
against the exact number this run expects to have created.

Run manually via `make verify-persistence`.

## Planned functionality (not yet implemented)

Explicitly out of scope for Phase 3A, per its own instructions:

- **Alertmanager ingestion** (turning a real firing alert into a
  database row) — Phase 3C.
- **Incident lifecycle transition validation** (which status changes
  are legal) — Phase 3D.
- Any FastAPI control-plane service, HTTP API, or endpoint reading or
  writing this table.
- Any AI/LLM agent, LangGraph, or RAG component.
- Investigation workflows, remediation actions, or human-approval
  records.
- A frontend of any kind.
- Additional tables (signal history, investigations, approval records,
  audit trails) — future phases will add these through subsequent
  versioned migrations (`V2__...`, etc.), not retrofitted into `V1`.

This document will be extended (not rewritten) as those phases land, in
the same way `V1__create_incident_schema.sql` is the first of a growing
migration history, not the last.
