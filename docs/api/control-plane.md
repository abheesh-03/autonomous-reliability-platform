# Control Plane API (Phase 3B, extended Phase 3C/3D)

This document describes the FastAPI control plane service
(`services/control-plane`) and its HTTP API. It is the authoritative
reference for endpoints, request/response shapes, DB configuration,
readiness behavior, and scope — summarized in
[README.md](../../README.md#control-plane-phase-3b) and
[docs/architecture/system-overview.md](../architecture/system-overview.md#control-plane-phase-3b).
Phase 3C's webhook ingestion endpoint and Phase 3D's incident lifecycle
are summarized below; full detail is in
[docs/architecture/phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md)
and
[docs/architecture/phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md)
respectively.

## Where this fits

```
HTTP client (read-only) --> FastAPI control plane (:8000) --> IncidentRepository --> PostgreSQL reliability.incidents
Alertmanager (internal Docker network, authenticated) --> POST /internal/v1/alertmanager/webhook --^
Human/operator (authenticated, distinct token) --> PATCH /api/v1/incidents/{id}/status --^
```

`reliability.incidents` is the Phase 3A schema
(`database/migrations/V1__create_incident_schema.sql` — see
[docs/architecture/incident-domain-model.md](../architecture/incident-domain-model.md)).
The control plane never creates, alters, or drops this table — Flyway
remains the only thing that owns the schema. As of Phase 3C/3D it is no
longer a *pure reader* of it: two routes write to it —
`POST /internal/v1/alertmanager/webhook` (see
[Webhook ingestion (Phase 3C)](#webhook-ingestion-phase-3c) below) and
`PATCH /api/v1/incidents/{id}/status` (see
[Incident lifecycle (Phase 3D)](#incident-lifecycle-phase-3d) below).
Every other route remains exactly as read-only as Phase 3B left it.

**Scope, explicitly:**

- **Implemented (Phase 3B):** a read-only HTTP API — list incidents
  with filtering/pagination, fetch one incident by id — plus liveness
  and readiness probes.
- **Implemented (Phase 3C):** one authenticated, internal write
  endpoint that ingests real firing Alertmanager alerts as
  `reliability.incidents` rows, deduplicated per-fingerprint via a real
  atomic PostgreSQL upsert.
- **Implemented (Phase 3D):** a centralized, validated incident status
  state machine; an authenticated `PATCH /api/v1/incidents/{id}/status`
  endpoint with optimistic concurrency; and real, source-driven
  automatic resolution from Alertmanager's resolved notifications
  (occurrence-identity/stale-replay safe, never auto-closing).
- **Not implemented, by design:** any generic incident-editing API (the
  lifecycle endpoint accepts exactly one status-transition shape, never
  arbitrary field updates); an incident audit-history table (Phase 3E);
  authentication on the `GET /api/v1/*` read API (still none — local
  development only); consumption by an operations console or agent.

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

## Webhook ingestion (Phase 3C)

### `POST /internal/v1/alertmanager/webhook`

The one authenticated write path in this service. Requires
`Authorization: Bearer <token>` (constant-time comparison against
`CONTROL_PLANE_WEBHOOK_TOKEN`; missing/incorrect token, or an
unconfigured server-side secret, → `401`, before any incident write).
Accepts Alertmanager's real webhook_configs version-4 JSON payload.

Request (abbreviated — see
[phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#payload-validation)
for the full validated field list):

```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"TelemetryPipelineUnavailable\"}",
  "status": "firing",
  "receiver": "control-plane-webhook",
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "TelemetryPipelineUnavailable", "severity": "critical"},
      "annotations": {"summary": "OTel Collector scrape target otel-collector is down"},
      "startsAt": "2026-09-30T12:00:00Z",
      "fingerprint": "8d2b83b6bbca23c7"
    }
  ]
}
```

Response (`200`):

```json
{"firing_processed": 1, "resolved_processed": 0, "incidents_created": 1, "incidents_updated": 0, "incidents_resolved": 0, "incidents_ignored": 0}
```

Firing alerts are upserted atomically, keyed on
`(source="alertmanager", source_fingerprint=<the alert's real
fingerprint>)`, using the exact same partial unique index Phase 3A
defined (`incidents_active_fingerprint_uniq`) as the database-level
deduplication mechanism — a duplicate delivery updates the existing
active incident (id/first_seen_at/status preserved, last_seen_at
advanced) rather than creating a second row or erroring; a resolved
historical row for the same fingerprint is never touched. As of Phase
3D, a resolved alert whose fingerprint matches a currently-active
incident genuinely resolves it — see
[Incident lifecycle (Phase 3D)](#incident-lifecycle-phase-3d) below for
the full occurrence-identity/stale-replay design; a resolved alert with
no matching active incident is a safe, idempotent no-op counted in
`incidents_ignored`. The whole batch is one transaction: either every
valid alert's effect is persisted, or (on any failure, including a real
database outage, which returns `503`) none are.

Full design, the Alertmanager-side configuration, secret setup, and the
real end-to-end acceptance proof:
[docs/architecture/phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md).

## Incident lifecycle (Phase 3D)

### `PATCH /api/v1/incidents/{incident_id}/status`

The one human/operator write path in this service. Requires
`Authorization: Bearer <token>` — a **separate, independently random**
token from the webhook's (`CONTROL_PLANE_LIFECYCLE_TOKEN`, distinct
from `CONTROL_PLANE_WEBHOOK_TOKEN`; neither can authenticate the
other's endpoint).

Request:

```json
{"expected_status": "open", "target_status": "acknowledged"}
```

`expected_status` is mandatory — the optimistic-concurrency guard: the
transition only applies if the incident's actual current status still
matches it at the moment of a real, atomic database compare-and-swap
`UPDATE`. Returns the full updated `Incident` representation on `200`.

| Condition | Status |
|---|---|
| Successful transition (including the same-status no-op) | `200` |
| Illegal transition (not in the matrix below) | `409` |
| Stale `expected_status` | `409` |
| Incident not found | `404` |
| Malformed UUID / invalid or unknown body field | `422` |
| Missing/incorrect lifecycle credentials | `401` |
| Real database unavailability | `503` |

Transition matrix:

| Current | May transition to |
|---|---|
| `open` | `acknowledged`, `investigating`, `resolved` |
| `acknowledged` | `investigating`, `resolved` |
| `investigating` | `remediating`, `resolved` |
| `remediating` | `investigating`, `resolved` |
| `resolved` | `closed` |
| `closed` | *(none)* |

No generic incident-editing API exists — this endpoint accepts exactly
`{expected_status, target_status}` and nothing else.

Full design — the transition matrix's rationale, timestamp invariants,
the concurrency mechanism (atomic compare-and-swap plus transaction-
scoped advisory locks for the webhook path), automatic resolution,
occurrence-identity/stale-replay handling, and the full real-PostgreSQL
verification story:
[docs/architecture/phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md).

## Error handling

| Condition | Status | Body |
|---|---|---|
| Incident not found | `404` | `{"detail": "incident not found"}` |
| Malformed UUID path param | `422` | FastAPI's standard validation error |
| Invalid `status`/`severity` filter | `422` | `{"detail": "invalid status filter: '...'"}` (or `severity`) |
| `limit`/`offset` out of range | `422` | FastAPI's standard validation error (`Query(ge=..., le=...)`) |
| Missing/incorrect webhook or lifecycle Bearer token | `401` | `{"detail": "unauthorized"}` (write endpoints only — a token valid for one never authenticates the other) |
| Malformed/unsupported webhook payload | `422` | FastAPI's standard validation error (webhook endpoint only) |
| Illegal lifecycle transition / stale `expected_status` | `409` | `{"detail": "illegal transition: ..."}` / `{"detail": "stale expected_status: ..."}` (lifecycle endpoint only) |
| PostgreSQL/schema temporarily unavailable | `503` | `{"detail": "database temporarily unavailable"}` |

The `503` case is handled by two global handlers in `main.py`:
`@app.exception_handler(SQLAlchemyError)` (the large majority of real
failures) and, as of Phase 3C, `add_exception_handler(OSError, ...)` —
added after a real integration test found that a fully-stopped
PostgreSQL can surface as a raw `socket.gaierror` that SQLAlchemy's
asyncpg dialect never wraps into a `SQLAlchemyError` at all (see
[phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#real-bug-found-and-fixed-during-implementation)
for the full story); safe because PostgreSQL is this service's only
external I/O dependency. Every route gets identical, consistent
behavior rather than duplicated try/except blocks. In every case, the
HTTP response **never** contains a password, connection string, raw
SQL, a stack trace, or (for the webhook's own 401s) the configured or
supplied Bearer token — those are logged server-side only
(`make control-plane-logs`). An unexpected programming error (anything
not a `SQLAlchemyError`/`OSError`) is not silently converted into a
misleading `404` or `200` — it propagates as FastAPI's normal
unhandled-exception `500`.

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
- **Webhook ingestion (Phase 3C)** is split the same way: route
  (`api/webhook.py`, thin), authentication dependency
  (`api/auth.py`), request/response schemas
  (`domain/alertmanager_webhook.py`), alert-to-incident field
  derivation (`ingestion/mapping.py`, a pure function), and the actual
  atomic upsert SQL (`repositories/incident_repository.py`'s
  `upsert_firing_incident`) — see
  [docs/architecture/phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#application-design).
- **Incident lifecycle (Phase 3D)**: the state machine itself lives in
  one module (`domain/lifecycle.py`, pure functions, no I/O); the PATCH
  route (`api/incidents.py`) and the webhook's resolution path
  (`ingestion/service.py`) both call into it rather than re-encoding
  any transition rule. Authentication reuses the same
  `api/auth.py` factory as the webhook token, built via a shared
  `_require_token(*, state_attr, env_var_name)` closure so both tokens'
  constant-time comparison logic cannot drift apart. See
  [docs/architecture/phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md#the-state-transition-matrix).

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
- As of Phase 3C, also receives `CONTROL_PLANE_WEBHOOK_TOKEN` (default
  empty string) — see
  [phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#secret-initialization).
- As of Phase 3D, also receives `CONTROL_PLANE_LIFECYCLE_TOKEN`
  (default empty string, `.env`-only, no file mirror needed) — see
  [phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md#secret-initialization).

## Testing

**Unit tests** (`services/control-plane/tests/`, `make
control-plane-test`, 162 tests): dependency-injected fakes — an
in-memory `FakeIncidentRepository` (installed via
`app.dependency_overrides[get_incident_repository]`) for the incidents,
webhook, and lifecycle endpoints, and fake engine/connection doubles
for the health endpoints. No real database involved. Covers: valid
serialization, empty collection, pagination, status/severity/source
filtering, deterministic ordering, UUID lookup, 404, malformed UUID
(422), out-of-range pagination (422 × 3), invalid status/severity
filters (422 × 2), two explicit 503-with-no-leaked-secret tests;
(Phase 3C, `test_webhook.py`) valid authenticated firing payload,
missing/incorrect Bearer token, an unconfigured server secret
(fail-closed), malformed payload, missing required label, unsupported
severity, invalid fingerprint, invalid timestamp, empty batch,
multi-alert batch, duplicate firing preserves identity, a forced
database error not reported as success, a simulated DNS-resolution
failure also returning 503, and no secret value in any error response;
and (Phase 3D, `test_lifecycle.py` plus further `test_webhook.py`
additions) every permitted/forbidden transition, the same-status
no-op, stale `expected_status`, missing incident, invalid UUID/status,
missing/incorrect/cross-endpoint lifecycle credentials, `resolved_at`
set/preserved correctly, timestamps unchanged on rejection, a real
database error returning 503, a commit-after-transition regression
suite, genuine Alertmanager resolution, idempotent duplicate
resolution, and stale-replay/recurrence safety for both firing and
resolved alerts.

**Mocked tests are not sufficient for acceptance on their own** — see
below. In particular, the mocked `FakeIncidentRepository`'s
`upsert_firing_incident` approximates the real atomic-upsert dedup
behavior in Python for route-level testing only; it is explicitly not
proof of PostgreSQL's own real partial-unique-index upsert semantics.

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

**Phase 3C** adds two further real-integration layers, both detailed in
[phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#verification):
`scripts/verify-webhook-ingestion.sh` (`make verify-webhook-ingestion`)
— a focused, fast acceptance test POSTing directly to this webhook
endpoint (auth, payload validation, the real atomic upsert/dedup
behavior, transaction boundaries, and a real PostgreSQL outage) — and
`scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`
(`make verify-alert-ingestion`) — the genuine end-to-end proof that a
real Prometheus alert, delivered through Alertmanager's own real
webhook (never a synthetic POST), becomes a persisted, correctly-mapped
incident.

**Phase 3D** adds `scripts/verify-incident-lifecycle.sh`
(`make verify-incident-lifecycle`) — a focused, real-PostgreSQL
acceptance test covering every transition, concurrency (10 genuinely
concurrent `PATCH` requests), authentication (including cross-token
rejection), restart persistence, and a real occurrence-identity
scenario driven through the actual webhook endpoint — and extends
`scripts/verify-alert-lifecycle.sh`'s same real Collector-outage test
with a read-only confirmation that the real Alertmanager resolved
webhook genuinely resolved the matching incident(s); full detail in
[phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md#verification).

All sections passed on real runs against the live stack.

## Security limitations (local development only)

- **The read-only `GET /api/v1/*` API has no authentication or
  authorization at all** — anyone who can reach `127.0.0.1:8000` on the
  host can read every incident. Acceptable for local development only;
  a prerequisite for any non-local deployment.
- **Both write paths are authenticated** — `POST
  /internal/v1/alertmanager/webhook` (see
  [Webhook ingestion](#webhook-ingestion-phase-3c) above) and `PATCH
  /api/v1/incidents/{id}/status` (see
  [Incident lifecycle](#incident-lifecycle-phase-3d) above) — each with
  its own Bearer token, fail-closed, constant-time comparison, and
  neither token able to authenticate the other's endpoint. This is
  explicitly **local-development security, not a production
  authentication framework**: shared secrets (a plaintext file for the
  webhook token, `.env` only for the lifecycle token), no token
  rotation automation, no per-client credentials, no external secrets
  service. See
  [phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#secret-initialization)
  and
  [phase-3d-incident-lifecycle.md](../architecture/phase-3d-incident-lifecycle.md#secret-initialization)
  for the full reasoning.
- **The incident status transition matrix is enforced at the
  application layer only** — not a database `CHECK` constraint. A
  privileged SQL client connecting directly to PostgreSQL can set
  `status` to any value the database's own vocabulary `CHECK`
  constraint permits, bypassing this transition matrix the same way it
  could bypass any other application-level rule.
- Read-only-at-the-API-level is not a database-level restriction — the
  `POSTGRES_USER` credential used has whatever privileges the existing
  local PostgreSQL setup grants it.
- No rate limiting, no TLS (plain HTTP). The webhook does enforce a
  real, aggregate request-body size limit (1 MiB, via ASGI middleware —
  see
  [phase-3c-alert-ingestion.md](../architecture/phase-3c-alert-ingestion.md#request-body-size-limit)),
  on top of Pydantic's own structural batch/label limits; the read API
  has no size limit beyond FastAPI/Pydantic's own defaults. The read
  API is loopback-only; the webhook is reachable only over the internal
  Docker network, never published on a host port.

## Planned (Phase 3E+, not yet implemented)

- An incident audit-history table recording every transition (who,
  when, from what, to what).
- Agent-generated remediation decisions, human approval workflows, and
  automated remediation of any kind.
- Authentication on the read API, an operations console, and any agent
  consumption of this API all remain future work.
