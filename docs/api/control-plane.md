# Control Plane API (Phase 3B)

This document describes the FastAPI control plane service
(`services/control-plane`) and its HTTP API. It is the authoritative
reference for endpoints, request/response shapes, DB configuration,
readiness behavior, and scope — summarized in
[README.md](../../README.md#control-plane-phase-3b) and
[docs/architecture/system-overview.md](../architecture/system-overview.md#control-plane-phase-3b).

## Where this fits

```
HTTP client --> FastAPI control plane (:8000) --> IncidentRepository --> PostgreSQL reliability.incidents
```

`reliability.incidents` is the Phase 3A schema
(`database/migrations/V1__create_incident_schema.sql` — see
[docs/architecture/incident-domain-model.md](../architecture/incident-domain-model.md)).
The control plane is a **pure reader** of that table: it never creates,
alters, or writes to it. Flyway remains the only thing that owns the
schema.

**Scope, explicitly:**

- **Implemented (Phase 3B):** a read-only HTTP API — list incidents
  with filtering/pagination, fetch one incident by id — plus liveness
  and readiness probes.
- **Not implemented, by design:** any endpoint that creates, updates,
  or deletes an incident (no `POST`/`PATCH`/`DELETE` exists anywhere in
  this API); ingestion of real alerts from Alertmanager (Phase 3C);
  incident lifecycle transition rules (Phase 3D); authentication of any
  kind; consumption by an operations console or agent.

## Running it

The service is a normal Compose service, started the same way as the
rest of the stack:

```bash
cp .env.example .env   # if you haven't already
make db-up              # docker compose up -d — starts PostgreSQL *and* control-plane
make db-migrate          # apply Phase 3A migrations (control-plane will serve 503 until this runs)
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/api/v1/incidents
```

`control-plane` does **not** depend on the `flyway` service (which
stays gated behind `profiles: ["tools"]`, per the existing Phase 3A
convention — it is never started by a plain `docker compose up -d`).
This is intentional: see
["Startup and migration ordering"](#startup-and-migration-ordering)
below.

```bash
make control-plane-build   # docker compose build control-plane
make control-plane-test    # unit tests (mocked repository/engine), Python 3.13 via Docker
make control-plane-logs    # docker compose logs --tail=100 control-plane
make verify-control-plane  # real integration test against the running, PostgreSQL-backed service
```

## Database configuration

Connection settings are read from individual environment variables
(`services/control-plane/src/control_plane/core/config.py`) — never a
single pre-built connection string, and never a source-code constant.
SQLAlchemy's `URL.create()` assembles the final URL from these
components, so a password containing `@`, `/`, or `#` cannot corrupt
it the way manual string concatenation would.

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_HOST` | `postgres` | Compose service DNS name |
| `POSTGRES_INTERNAL_PORT` | `5432` | Always 5432 inside the Compose network — deliberately *not* `POSTGRES_PORT`, which is the host-side port mapping used for external access |
| `POSTGRES_USER` | *(required)* | |
| `POSTGRES_PASSWORD` | *(required)* | |
| `POSTGRES_DB` | *(required)* | |
| `CONTROL_PLANE_DB_POOL_SIZE` | `5` | SQLAlchemy async connection pool size |
| `CONTROL_PLANE_DB_POOL_TIMEOUT_SECONDS` | `5` | Bounded wait for a pooled connection |
| `CONTROL_PLANE_DB_CONNECT_TIMEOUT_SECONDS` | `5` | asyncpg connect timeout |
| `CONTROL_PLANE_DB_COMMAND_TIMEOUT_SECONDS` | `10` | asyncpg per-command timeout |

The three required variables are missing-fails-fast (`RuntimeError` at
startup) if unset; in `docker-compose.yml` they're populated from the
same `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` `.env` values
PostgreSQL itself uses. `pool_pre_ping` is always on — a connection
that's gone stale (e.g. because PostgreSQL restarted) is detected and
replaced before being handed to a request, rather than surfacing as a
confusing mid-request failure.

No credential ever appears in a log line or an HTTP response — see
[Error handling](#error-handling) below.

## Startup and migration ordering

This is the one piece of behavior this phase explicitly had to get
right and separately verify, because of how the rest of this repo's
Compose setup works: the `flyway` service is gated behind
`profiles: ["tools"]`, so a plain `docker compose up -d` never applies
Phase 3A's migration automatically — `reliability.incidents` may not
exist yet when `control-plane` starts.

- `create_async_engine()` (`db/engine.py`) does **not** open a
  connection at construction time — it only prepares the engine and
  its pool. Building the engine during FastAPI's `lifespan` startup
  therefore cannot fail just because PostgreSQL isn't reachable yet or
  the schema hasn't been migrated.
- `GET /health/live` never touches the database, so the container's
  Docker healthcheck (and `docker compose up -d`'s own health wait)
  report `healthy` immediately, independent of migration state.
- `GET /health/ready` is the only thing that reflects real DB/schema
  availability: it runs `SELECT 1 FROM reliability.incidents LIMIT 1`
  and returns `503` for any failure (table missing, PostgreSQL
  unreachable, PostgreSQL mid-restart), `200` once it succeeds.
- No automatic "run Flyway on every control-plane startup" exists —
  migrations remain an explicit, separate step (`make db-migrate`),
  exactly as Phase 3A established.

**Verified empirically, not just by inspection**, using a disposable
Compose project (`COMPOSE_PROJECT_NAME=cp-ordering-test`, its own
fresh, unmigrated PostgreSQL volume, torn down afterward with
`docker compose down -v` — the real project's `postgres_data` volume
was never touched):

1. Brought up a brand-new, unmigrated `postgres` + `control-plane`
   pair. `GET /health/live` returned `200` immediately; the Docker
   healthcheck reported `healthy`; `GET /health/ready` correctly
   returned `503`.
2. Ran `docker compose run --rm flyway migrate` in that same project,
   **without restarting `control-plane`**. `GET /health/ready`
   transitioned to `200` on its own; the container's uptime remained
   continuous throughout, proving recovery doesn't require a manual
   restart.
3. Inserted a row directly via `psql` and confirmed it round-tripped
   correctly through `GET /api/v1/incidents`.
4. Ran `docker compose restart postgres` in that same project.
   `GET /health/ready` transiently returned `503`, then recovered to
   `200` once PostgreSQL came back — again with `control-plane` never
   restarted — followed by a real, successful
   `GET /api/v1/incidents/{id}` proving the connection pool itself
   (not just the readiness probe) had recovered.

The same restart-recovery proof (step 4) is also exercised against the
real, non-throwaway stack by `scripts/verify-control-plane.sh` (section
13) on every run — see
[Integration verification](#integration-verification) below.

## Endpoints

### `GET /health/live`

Liveness only — no database round-trip. Always `200` once the process
is running:

```json
{"status": "UP"}
```

### `GET /health/ready`

```json
{"status": "ready"}
```
`200` if a real query against `reliability.incidents` succeeds, `503`
(`{"status": "unavailable"}`) for any failure. The underlying exception
is logged server-side only and never appears in the response.

### `GET /api/v1/incidents`

Query parameters (all optional unless noted):

| Parameter | Type | Default | Constraint |
|---|---|---|---|
| `status` | string | — | must be one of `open`, `acknowledged`, `investigating`, `remediating`, `resolved`, `closed` (else `422`) |
| `severity` | string | — | must be one of `critical`, `warning`, `info` (else `422`) |
| `source` | string | — | exact match, no validation beyond that (any originating system name is accepted) |
| `limit` | int | `20` | `1`–`100` inclusive (else `422`) |
| `offset` | int | `0` | `>= 0` (else `422`) |

Filters combine with AND. Ordering is always deterministic:
`last_seen_at DESC, id DESC` — the `id` tiebreaker makes pagination
stable even when multiple incidents share a `last_seen_at`. `total` is
the count of matching rows **before** `limit`/`offset` are applied, not
`len(items)`.

Response:

```json
{
  "items": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "source": "alertmanager",
      "source_fingerprint": "TelemetryPipelineUnavailable:...",
      "title": "Telemetry pipeline unavailable",
      "description": null,
      "severity": "critical",
      "status": "open",
      "first_seen_at": "2026-09-30T12:00:00+00:00",
      "last_seen_at": "2026-09-30T12:05:00+00:00",
      "resolved_at": null,
      "created_at": "2026-09-30T12:00:00.123456+00:00",
      "updated_at": "2026-09-30T12:05:00.123456+00:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

An empty result is a genuine `200` with `"items": []` and `"total": 0`
— never fabricated data.

### `GET /api/v1/incidents/{incident_id}`

`incident_id` is path-validated as a UUID by FastAPI itself (a
malformed value returns `422` with no extra code needed). Returns the
same incident object shown above on `200`, or `404`
(`{"detail": "incident not found"}`) if no row matches.

## Error handling

| Condition | Status | Body |
|---|---|---|
| Incident not found | `404` | `{"detail": "incident not found"}` |
| Malformed UUID path param | `422` | FastAPI's standard validation error |
| Invalid `status`/`severity` filter | `422` | `{"detail": "invalid status filter: '...'"}` (or `severity`) |
| `limit`/`offset` out of range | `422` | FastAPI's standard validation error (`Query(ge=..., le=...)`) |
| PostgreSQL/schema temporarily unavailable | `503` | `{"detail": "database temporarily unavailable"}` |

The `503` case is handled by a single global
`@app.exception_handler(SQLAlchemyError)` in `main.py`, so every route
gets identical, consistent behavior rather than duplicated try/except
blocks. In every case, the HTTP response **never** contains a
password, connection string, raw SQL, or a stack trace — those are
logged server-side only (`make control-plane-logs`). An unexpected
programming error (anything not a `SQLAlchemyError`) is not silently
converted into a misleading `404` or `200` — it propagates as FastAPI's
normal unhandled-exception `500`.

## Architecture notes

- **Domain/response models**
  (`src/control_plane/domain/incident.py`): a Pydantic v2 `Incident`
  model whose 12 fields and `Severity`/`Status` `Literal` vocabularies
  match `V1__create_incident_schema.sql` exactly, maintained by hand
  (no ORM reflection) since that migration is Flyway-owned and never
  modified from here.
- **Repository** (`src/control_plane/repositories/incident_repository.py`):
  a dedicated `IncidentRepository` built on a bare, metadata-free
  `sa.table()`/`sa.column()` Core table expression — deliberately not
  an ORM-mapped declarative model, since that would carry schema-write
  capability (`Table.create()`, `metadata.create_all()`) the control
  plane must never have. All filtering uses real bound parameters
  (`.where(...)` comparisons), not string interpolation.
- **Dependency injection** (`src/control_plane/api/dependencies.py`):
  routes depend on `get_incident_repository`, not directly on a
  SQLAlchemy session — this is the seam unit tests override with an
  in-memory fake repository, so unit tests never need to fake
  SQLAlchemy internals.
- **No large SQL in route handlers** (`src/control_plane/api/incidents.py`):
  handlers validate query params and delegate entirely to the
  repository.

## Docker / Compose

`docker-compose.yml`'s `control-plane` service:

- Builds from `services/control-plane/Dockerfile` (Python 3.13-slim,
  non-root `app` user, no observability extra — this service's own
  OpenTelemetry instrumentation is explicitly out of scope for Phase
  3B).
- `depends_on: postgres: condition: service_healthy` — but **not**
  `flyway`, matching the "don't require migrations to have run"
  requirement above.
- Published on `127.0.0.1:8000:8000` only (not on all interfaces).
- Docker healthcheck calls `GET /health/live` (not `/health/ready`) —
  the schema may legitimately not exist yet, and liveness is what a
  container orchestration healthcheck should reflect.
- No new persistent volume; no `profiles:` restriction (unlike
  `flyway`, it **does** start on a plain `docker compose up -d`).

## Testing

**Unit tests** (`services/control-plane/tests/`, `make
control-plane-test`, 20 tests): dependency-injected fakes — an
in-memory `FakeIncidentRepository` (installed via
`app.dependency_overrides[get_incident_repository]`) for the incidents
endpoints, and fake engine/connection doubles for the health endpoints.
No real database involved. Covers: valid serialization, empty
collection, pagination, status/severity/source filtering, deterministic
ordering, UUID lookup, 404, malformed UUID (422), out-of-range
pagination (422 × 3), invalid status/severity filters (422 × 2), and
two explicit 503-with-no-leaked-secret tests.

**Mocked tests are not sufficient for acceptance on their own** — see
below.

## Integration verification

`scripts/verify-control-plane.sh` (`make verify-control-plane`, also
run in CI immediately after the Phase 3A persistence verifier) is the
real acceptance test: it runs against the actual Compose stack, the
actual PostgreSQL database, and the actual running FastAPI process —
nothing mocked. It does **not** use an incident-creation HTTP API
(none exists); test incidents are inserted directly via `psql`, scoped
to a run-unique `source` value (`verify-control-plane-test-<uuid>`) so
cleanup only ever removes rows this exact run created.

Summary of what it proves, end to end, against the real stack:

1. PostgreSQL is healthy and Phase 3A migrations are applied
   (`docker compose run --rm flyway migrate`).
2. `control-plane` is healthy; `/health/live` and `/health/ready` both
   return `200`.
3. Four real incidents are inserted directly via `psql` (varied
   status/severity, one pre-resolved).
4. Each field, including ISO-8601 timestamp parseability, round-trips
   correctly through `GET /api/v1/incidents/{id}`.
5. `status`, `severity`, and `source` filters each return the correct
   subset.
6. Pagination (`limit`/`offset`) and ordering are deterministic and
   match the expected page boundaries.
7. An empty-result filter returns `{"items": [], "total": 0, ...}`,
   never fabricated data.
8. Detail lookup works for a resolved incident.
9. `404` for a random UUID, `422` for a malformed UUID and five
   different invalid-query-parameter cases.
10. Plain `GET` traffic never modifies a record (`updated_at` is
    compared byte-for-byte before and after a batch of reads).
11. A real `docker compose restart postgres` is followed by a bounded
    retry of `/health/ready` until `200`, then a real data fetch,
    proving actual pool recovery — with the control-plane container's
    own uptime printed as evidence it was never restarted.
12. Cleanup deletes exactly this run's 4 rows (count-verified), with a
    separate best-effort `EXIT` trap for cleanup on an earlier failure
    that never masks the original failure.

All 14 sections passed on the first real run against the live stack.

## Security limitations (local development only)

- **No authentication or authorization** of any kind — anyone who can
  reach `127.0.0.1:8000` on the host can read every incident.
  Acceptable for local development only; a prerequisite for any
  non-local deployment.
- Read-only today, but this is an API-level restriction (no
  `POST`/`PATCH`/`DELETE` routes exist), not a database-level one — the
  `POSTGRES_USER` credential used has whatever privileges the existing
  local PostgreSQL setup grants it.
- No rate limiting, no request size limits beyond FastAPI/Pydantic's
  own defaults, no TLS (plain HTTP, loopback-only).

## Planned (Phase 3C / 3D, not yet implemented)

- **Phase 3C:** ingesting real Alertmanager alerts into
  `reliability.incidents` (the write path this phase deliberately does
  not build).
- **Phase 3D:** lifecycle transition endpoints
  (acknowledge/investigate/remediate/resolve/close) with real
  transition-validity rules, superseding the data-integrity-only
  `resolved_at`/`status` constraint Phase 3A already enforces.
- Authentication, an operations console, and any agent consumption of
  this API all remain future work.
