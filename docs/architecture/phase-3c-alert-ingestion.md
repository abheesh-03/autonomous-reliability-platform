# Phase 3C: Real Alertmanager Incident Ingestion

This document describes how a real, genuine Prometheus alert becomes a
persistent `reliability.incidents` row: the Alertmanager webhook
receiver, the authenticated FastAPI ingestion endpoint, payload
validation, alert-to-incident field mapping, the atomic
create-or-update (upsert) deduplication behavior, and how all of this
is verified against real infrastructure — never a simulated
demonstration. It does **not** describe the `reliability.incidents`
schema itself (Phase 3A — see
[incident-domain-model.md](incident-domain-model.md)) or the read-only
`GET /api/v1/incidents` API (Phase 3B — see
[docs/api/control-plane.md](../api/control-plane.md)), both unchanged
by this phase except as noted below. It also does **not** describe
incident lifecycle transitions or automatic resolution from a resolved
Alertmanager notification — those were a deliberate, temporary scope
boundary when this document was first written (see
[Phase 3C resolved-alert limitations](#phase-3c-resolved-alert-limitations)
below) and are now implemented in
[Phase 3D](phase-3d-incident-lifecycle.md), without changing anything
described here about firing-alert ingestion itself.

## Where this fits

```
Prometheus (evaluates alert rules)
    |
    v
Alertmanager (receives, groups, tracks state)
    |
    | POST http://control-plane:8000/internal/v1/alertmanager/webhook
    | Authorization: Bearer <token>   (internal Docker network only)
    v
FastAPI control plane: POST /internal/v1/alertmanager/webhook
    |
    | 1. Bearer-token auth (api/auth.py)
    | 2. Pydantic payload validation (domain/alertmanager_webhook.py)
    | 3. Alert -> incident field mapping (ingestion/mapping.py)
    | 4. Atomic upsert, one transaction (repositories/incident_repository.py)
    v
PostgreSQL reliability.incidents
    |
    v
Existing, unchanged GET /api/v1/incidents / GET /api/v1/incidents/{id}
```

Before this phase, Alertmanager's only receiver was a no-op `local-null`
sink (Phase 2B.4) — it received and tracked alert state through its own
API, but sent nothing anywhere. `reliability.incidents` existed (Phase
3A) with nothing reading or writing it until Phase 3B's read-only API.
Phase 3C is the first time a real Prometheus alert automatically
becomes a persistent incident, with no human or test helper in the
loop.

## Alertmanager configuration

`observability/alertmanager/alertmanager.yml`'s single receiver was
changed from `local-null` to `control-plane-webhook`:

```yaml
route:
  receiver: control-plane-webhook
  group_by: ["alertname", "severity"]
  group_wait: 10s
  group_interval: 30s
  repeat_interval: 1h

receivers:
  - name: control-plane-webhook
    webhook_configs:
      - url: http://control-plane:8000/internal/v1/alertmanager/webhook
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/webhook-token
```

- **`url`** uses Compose's internal service DNS (`control-plane`), not
  `127.0.0.1:8000` (the loopback-only host-published port) — this
  request never leaves the Compose network.
- **`send_resolved: true`** — Alertmanager also delivers resolved
  notifications. Phase 3C's endpoint accepts and acknowledges them but
  does not act on them; see
  [Resolved-alert limitations](#phase-3c-resolved-alert-limitations)
  below.
- **`group_by`/`group_wait`/`group_interval`/`repeat_interval`** are
  **unchanged** from Phase 2B.4 — no evidence from the real end-to-end
  test (below) justified adjusting them.
- **`http_config.authorization.credentials_file`** points at a file
  mounted read-only from the host
  (`observability/alertmanager/secrets/webhook-token`, gitignored),
  never a literal token value in this config file. Alertmanager
  re-reads this file on every delivery attempt (confirmed in its own
  HTTP client library), so a future rotation would not require
  restarting Alertmanager — not exercised today, since
  `scripts/init-webhook-secret.sh` deliberately never rotates an
  existing secret (see below), but the mechanism supports it.

## Secret initialization

`scripts/init-webhook-secret.sh` generates one cryptographically random
Bearer token (`secrets.token_hex(32)`, 256 bits) and writes it to the
two places it needs to reach:

1. **`.env`** (`CONTROL_PLANE_WEBHOOK_TOKEN=...`) — read by
   `docker-compose.yml`'s `control-plane` service environment block.
   This is the **authoritative** copy.
2. **`observability/alertmanager/secrets/webhook-token`** — bind-mounted
   read-only, as a single **file** (not its parent directory — see
   below), into the `alertmanager` container.

### Permissions — chosen to work for a real non-root container user

The pinned `prom/alertmanager:v0.34.1` image runs as a real, non-root
user: `nobody`, uid/gid `65534` (confirmed via `docker inspect
prom/alertmanager:v0.34.1 --format '{{.Config.User}}'`). The host
process running this script is neither that uid nor root, and does not
attempt to `chown` the file to `65534` (which would require privileges
this script shouldn't need). The permission model this resolves to:

- **`observability/alertmanager/secrets/` stays owner-only (`0700`).**
  No other host user can list or traverse into it.
- **`docker-compose.yml` bind-mounts the single `webhook-token` FILE**
  (`./observability/alertmanager/secrets/webhook-token:/etc/alertmanager/secrets/webhook-token:ro`),
  not its parent directory. Bind-mounting the whole directory would
  make the *container* inherit that same `0700`-owned-by-a-different-uid
  barrier and be unable to even traverse into it to reach the file —
  regardless of the file's own permissions.
- **The file itself is `0644`** (owner read/write, everyone else
  read-only) — the minimum permission that reliably lets an arbitrary
  non-root container uid read its content without this script needing
  to know or match that uid in advance. This does not widen real
  exposure: reaching the file by path still requires traversing the
  `0700` directory first, which only the file's owner can do.
- **`.env` stays `0600`.**

The init script's final step is a **real preflight**, not a trust
exercise: it runs the actual pinned `prom/alertmanager:v0.34.1` image
(which has a shell — confirmed empirically) as its actual default user
and checks `test -r /check/webhook-token && test -s ...` against the
freshly-written file, mounted read-only at a throwaway path. It never
prints the file's contents — only whether it was readable. This same
check runs on every invocation, locally and in CI (the CI step that
calls this script IS this preflight — no separate CI-only check was
needed).

### Synchronization — `.env` is authoritative

- **Idempotent, and `.env`'s value always wins.** If
  `CONTROL_PLANE_WEBHOOK_TOKEN` already has a non-empty value in
  `.env`, it is **never regenerated** — this avoids silently rotating
  the secret out from under already-running containers (control-plane
  reads it once, at its own process startup).
- **The Alertmanager-side copy is actively verified, not assumed, on
  every run.** The script reads the current content of
  `observability/alertmanager/secrets/webhook-token` and compares it to
  `.env`'s value. If they already match, nothing is written. If they
  differ — a stale copy, a missing file, or a corrupted one — the file
  is **repaired in place** (truncate-and-rewrite the same inode, never
  delete-and-recreate it, so an already-running Alertmanager container
  with this file already bind-mounted sees the correction without a
  restart) from the authoritative `.env` value. `.env` itself is never
  touched by a repair.
- **Fresh-checkout-safe.** Creates `.env` from `.env.example` and the
  `observability/alertmanager/secrets/` directory if either is
  missing — both are true on a brand-new GitHub Actions runner.
  Verified directly: running the script against a checkout with
  neither `.env` nor the `secrets/` directory present creates both,
  generates a token, and passes the readability preflight — with
  `0700`/`0644`/`0600` permissions all correct.
- **Never touches unrelated `.env` variables.** Only ever adds, reads,
  or replaces its own `CONTROL_PLANE_WEBHOOK_TOKEN=` line.
- **Never prints the secret.**
- **No external secrets service.** This is local-development security
  — a single shared Bearer token in a plaintext file, generated and
  distributed by a shell script. Not a production secrets framework.

Wired into `make db-up` (so a normal `docker compose up -d` via Make
always has a working webhook out of the box) and as its own target,
`make webhook-secret-init`; also invoked at the start of
`scripts/verify-webhook-ingestion.sh` and (when
`VERIFY_INGESTION=true`) `scripts/verify-alert-lifecycle.sh`, and as an
explicit CI step before Docker Compose config validation.
`docker-compose.yml` defaults `CONTROL_PLANE_WEBHOOK_TOKEN` to an empty
string (`${CONTROL_PLANE_WEBHOOK_TOKEN:-}`) so `docker compose config`
and a clean startup both still succeed even before this script has ever
run — an unset token simply means every webhook request fails closed
(401); it has no effect on the read-only API.

## Webhook endpoint

**`POST /internal/v1/alertmanager/webhook`**
(`services/control-plane/src/control_plane/api/webhook.py`) — the one
authenticated write path in this service. Every other route
(`GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`,
`GET /health/live`, `GET /health/ready`) remains exactly as Phase 3B
left it: read-only, unauthenticated, local-dev-only.

### Authentication

`api/auth.py`'s `require_webhook_token` (as of Phase 3D, built from a
shared `_require_token` factory it now shares with
`require_lifecycle_token` — see
[phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md)) is a
router-level
FastAPI dependency (`APIRouter(..., dependencies=[Depends(require_webhook_token)])`),
so it runs — and can reject the request — before the handler body, and
therefore before any incident write, regardless of payload content:

- Requires `Authorization: Bearer <token>`.
- Compares the supplied token to the server's configured token with
  `hmac.compare_digest` (constant-time, avoiding a timing side
  channel).
- **Fails closed**: if `CONTROL_PLANE_WEBHOOK_TOKEN` was never
  configured (`app.state.webhook_token` is `None`), authentication can
  never succeed — not that it is bypassed.
- Missing or incorrect token → `401`, with no incident writes and no
  secret value in the response body, ever.

### Payload validation

`domain/alertmanager_webhook.py` models Alertmanager's real
webhook_configs version-4 JSON payload with Pydantic v2
(`extra="ignore"` throughout, so fields this service doesn't need —
`generatorURL`, `truncatedAlerts`, `groupLabels`, `externalURL`, ... —
are tolerated, not rejected). Validated per alert:

| Field | Requirement |
|---|---|
| `status` | `"firing"` or `"resolved"` |
| `labels.alertname` | required, non-blank, for every alert regardless of status |
| `labels.severity` | required, must be `critical`/`warning`/`info` — **only for a firing alert** (a resolved-only alert is never mapped onto an incident's severity column, so it may legitimately lack or carry a stale value) |
| `annotations` | free-form map, bounded (see below) |
| `startsAt` | must parse as an ISO-8601 datetime **with timezone information** |
| `fingerprint` | required, non-blank |

Critically, **per-alert `status` drives ingestion, never the
group-level `status`** — a single delivery's `alerts` array can and
does contain a mix of firing and resolved entries (e.g. one alert
instance recovers while a sibling in the same group is still firing);
only the envelope (`version`, `groupKey`, top-level `status`,
`receiver`) is validated at the group level.

Reasonable, generous bounds (not a production rate-limiter, since every
request here is already Bearer-authenticated): up to 100 alerts per
batch, up to 50 labels/annotations per alert, up to 2000 characters per
label/annotation value. Any violation, or any malformed/unsupported
payload shape, returns `422` — and, per the transaction design below,
writes nothing at all, even if other alerts in the same batch would
have been valid.

### Request body size limit

Pydantic's bounds above cap a theoretical worst case, but that worst
case is still tens of megabytes. `api/webhook_limits.py` adds a direct,
aggregate raw-byte ceiling on the whole request body:
**`MAX_WEBHOOK_BODY_BYTES = 1 MiB`** — modest, and generous headroom
above what any real Alertmanager batch (bounded by the Pydantic limits
above) realistically produces. Oversized requests get `413`.

This is implemented as **ASGI middleware**
(`WebhookBodySizeLimitMiddleware`, registered in `main.py`,
internally scoped to only `POST /internal/v1/alertmanager/webhook`),
not a FastAPI route dependency — deliberately. Reading FastAPI's own
`get_request_handler` source confirmed that FastAPI reads and fully
buffers a route's entire request body via `await request.body()`
*before any dependency runs*, including an authentication dependency.
A `Depends()`-based size guard was tried first and found to be
ineffective for exactly this reason (confirmed empirically — it never
triggered, because by the time it ran the oversized body had already
been buffered and had already failed elsewhere). ASGI middleware wraps
the raw `receive()` callable at the transport boundary instead, so it
sees bytes as they actually arrive and can reject *before*
Starlette/FastAPI ever buffers them — genuinely enforced even when
`Content-Length` is missing or dishonest, since the real byte count is
what's checked, not the header. If the limit is exceeded, a `413`
response is sent directly and the wrapped application is never invoked
for that request at all; otherwise the already-drained bytes are
replayed to it unchanged, so normal requests are unaffected. Runs
independent of (and before) authentication — an oversized body from
even an unauthenticated sender is rejected immediately, which is more
protective for a resource-exhaustion concern, not less. Never inspects
or logs the `Authorization` header or any body content, only its
aggregate length.

## Alert-to-incident field mapping

Only firing alerts reach `ingestion/mapping.py`'s
`map_firing_alert_to_incident_fields`:

| `reliability.incidents` column | Source |
|---|---|
| `source` | literal `"alertmanager"` |
| `source_fingerprint` | the alert's own real `fingerprint` (never Alertmanager's `groupKey`, which would incorrectly collapse every alert in one notification group into a single fingerprint) |
| `title` | `annotations.summary`, stripped; if blank or absent, falls back to `labels.alertname` (already validated non-blank), so title is always guaranteed non-blank — satisfying `incidents`' own `CHECK (btrim(title) <> '')` |
| `description` | `annotations.description` if present, else `NULL` |
| `severity` | the validated `labels.severity` |
| `status` | `"open"` (only on first creation — see below) |
| `first_seen_at` | the alert's own `startsAt` (always timezone-aware) |
| `last_seen_at` | the time this webhook delivery was accepted (`datetime.now(UTC)`, captured once per batch, not per alert) |
| `resolved_at` | `NULL` (only on first creation) |

No fabricated column is ever stored — there is no "Alertmanager event
ID" field anywhere in the schema or this mapping, by design (Phase 3A's
schema has none, and this phase does not add one).

## Atomic deduplication / upsert

This is the core correctness requirement of this phase.
`repositories/incident_repository.py`'s `upsert_firing_incident` uses a
single, real PostgreSQL `INSERT ... ON CONFLICT ... DO UPDATE`
statement (via SQLAlchemy's `postgresql.insert().on_conflict_do_update()`),
with the conflict target built to exactly match Phase 3A's existing
partial unique index:

```sql
-- V1__create_incident_schema.sql (Phase 3A, unmodified):
CREATE UNIQUE INDEX incidents_active_fingerprint_uniq
    ON reliability.incidents (source, source_fingerprint)
    WHERE status NOT IN ('resolved', 'closed');
```

```python
upsert_stmt = insert_stmt.on_conflict_do_update(
    index_elements=[incidents_table.c.source, incidents_table.c.source_fingerprint],
    index_where=sa.text("status NOT IN ('resolved', 'closed')"),
    set_={
        "title": insert_stmt.excluded.title,
        "description": insert_stmt.excluded.description,
        "severity": insert_stmt.excluded.severity,
        "last_seen_at": sa.func.greatest(incidents_table.c.last_seen_at, insert_stmt.excluded.last_seen_at),
    },
).returning(incidents_table.c.id, sa.literal_column("(xmax = 0)").label("created"))
```

The `index_where` predicate is expressed as literal SQL text
(`sa.text(...)`), not a bound parameter comparison — PostgreSQL only
accepts an `ON CONFLICT ... WHERE <predicate>` clause as a valid
inference target if it textually matches an existing partial index's
own predicate; this was confirmed empirically (see
[Real PostgreSQL integration results](#verification) below), not
merely assumed.

Behavior, proven against the real database:

- **A duplicate firing delivery** (same `source`/`source_fingerprint`,
  an active row already exists) updates that row: `id` and
  `first_seen_at` are never touched; `status` is never reset to
  `"open"` (a human or future agent's `acknowledged`/`investigating`/
  `remediating` state survives a re-delivery); `title`/`description`/
  `severity` are refreshed to the new delivery's values (Alertmanager's
  own annotation text can change between deliveries of the same firing
  alert — e.g. a `$value` template interpolation); `last_seen_at` only
  ever advances (`GREATEST`), tolerant of any out-of-order delivery.
  `updated_at` is maintained by Phase 3A's existing
  `incidents_set_updated_at` trigger, not set here.
- **A resolved/closed historical row** for the same fingerprint is
  *invisible* to this conflict target (it fails the partial index's own
  `WHERE` clause) — a brand-new active row is inserted instead,
  automatically, by the exact same statement. History is preserved,
  never overwritten.
- **Real atomicity, not an application-level race.** This is a single
  database statement; two concurrent deliveries for the same
  fingerprint cannot both "win" an INSERT and violate the unique index
  the way a SELECT-then-INSERT pattern could.
- Whether a given delivery created a brand-new row or updated an
  existing one is determined via PostgreSQL's own `xmax = 0`
  tuple-visibility idiom (true only for a row's own inserting
  transaction) — not an application-level flag that could drift from
  reality.

### Duplicate fingerprints within one batch

If Alertmanager (or a retried delivery) ever includes the same
fingerprint twice in a single webhook batch, each occurrence is simply
processed as another sequential upsert against the same row, within the
batch's one transaction — the last occurrence in the `alerts` array
wins for `title`/`description`/`severity`/`last_seen_at`, identical to
how two separate webhook deliveries would behave. No separate
in-memory deduplication pass exists or is needed.

## Transaction boundaries and retries

`ingestion/service.py`'s `ingest_alertmanager_webhook` processes every
firing alert in a batch sequentially, within the one implicit
transaction SQLAlchemy's `AsyncSession` opens on first use, and commits
**once**, after the loop:

- If any upsert in the loop raises, the function never reaches
  `commit()`; the session's implicit rollback-on-close means **none**
  of that batch's upserts are persisted — never a partial write. This
  was verified directly: a batch containing one valid alert and one
  invalid alert returns `422` (payload validation, before any database
  work begins at all) with the valid alert's fingerprint confirmed
  absent from the database afterward.
- A raised `SQLAlchemyError` — or, as a real integration run
  discovered (see below), a raw `OSError` from a lower-level connection
  failure — propagates to `main.py`'s existing global exception
  handler(s), which return `503` so Alertmanager's own built-in retry
  behavior (`group_interval`/`repeat_interval`) can redeliver later.
  Confirmed against a real, fully-stopped PostgreSQL container: the
  webhook call returns `503`, zero rows are written, and normal
  ingestion resumes automatically once PostgreSQL is healthy again —
  with no manual control-plane restart.
- The response is a small acknowledgement — `firing_processed`,
  `resolved_processed`, `incidents_created`, `incidents_updated`,
  `incidents_resolved`, `incidents_ignored` (the last two added by
  Phase 3D's resolution logic — see
  [phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md)) —
  never an incident's full representation.

### Real bug found and fixed during implementation

A real integration test (`scripts/verify-webhook-ingestion.sh`,
section 9) fully stopped PostgreSQL (`docker compose stop`, not
`restart`) and found that the `postgres` hostname itself stopped
resolving inside the Compose network — asyncpg's connection attempt
raised a raw `socket.gaierror`, which SQLAlchemy's asyncpg dialect (per
its own real traceback, inspected directly) re-raises unchanged rather
than wrapping into a `SQLAlchemyError`. The existing
`@app.exception_handler(SQLAlchemyError)` therefore never caught it,
and the webhook returned an unhandled `500` instead of `503`. Fixed by
registering a second handler, `app.add_exception_handler(OSError, ...)`
— safe and correct because PostgreSQL is this service's only external
I/O dependency, so any `OSError` reaching this level genuinely does
mean "the database is temporarily unavailable." Re-verified: the exact
same real-outage test now returns `503` as required. A matching unit
test (`test_dns_resolution_failure_also_produces_503`) reproduces this
at the mock level so a regression would be caught by `make control-plane-test`
alone, without needing a real outage.

## Firing vs. resolved notification behavior

**As originally built in Phase 3C** (resolved alerts were validated
and acknowledged but never acted on — see
[Phase 3C resolved-alert limitations](#phase-3c-resolved-alert-limitations)
below for why, and [Phase 3D](phase-3d-incident-lifecycle.md) for how
this changed):

| | Firing | Resolved (Phase 3C) | Resolved (as of Phase 3D) |
|---|---|---|---|
| Envelope validated | yes | yes | yes |
| Counted in response | `firing_processed` | `resolved_processed` | `resolved_processed` |
| Incident created | yes, if none active for this fingerprint | never | never |
| Existing incident updated | yes (see upsert behavior above) | never | — |
| Incident `status` changed | no (preserved, except `"open"` on first creation) | no | **yes — the matching active incident resolves, if occurrence identity matches** |
| `resolved_at` set | no (only `NULL` on first creation) | no | **yes, from the alert's real `endsAt`** |
| Incident deleted | never | never | never |
| A historical incident auto-reopened | never | never | never |
| Incident auto-closed | — | — | **never — `closed` remains an explicit human action** |

## Phase 3C resolved-alert limitations

This was a deliberate, temporary scope boundary when this phase was
first built, not an oversight: Alertmanager delivers real resolved
notifications (`send_resolved: true`), and this service validated and
acknowledged them — but did nothing else with them, since designing
real transition/resolution rules was explicitly deferred to a later
phase responsible for the incident lifecycle state machine as a whole.

**As of Phase 3D, this limitation no longer holds.** A resolved alert
whose fingerprint matches a currently-active incident now genuinely
resolves it (real `resolved_at`, occurrence-identity and stale-replay
safe, never auto-closing) — see
[docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md)
for the full design, including the real bug this exact transition
found and fixed (an initial equality check that could permanently
strand an active-but-never-resolved incident).

## Application design

```
services/control-plane/src/control_plane/
├── api/
│   ├── webhook.py          # route — thin, wires the pieces below together
│   ├── auth.py              # Bearer-token auth (webhook + Phase 3D lifecycle tokens)
│   ├── webhook_limits.py    # ASGI request-body size guard (registered in main.py)
│   ├── incidents.py         # Phase 3B reads; Phase 3D adds the PATCH status route
│   └── health.py            # unchanged (Phase 3B)
├── domain/
│   ├── alertmanager_webhook.py  # Pydantic request/response schemas
│   └── incident.py          # unchanged (Phase 3B) — VALID_SEVERITIES reused for validation
├── ingestion/
│   ├── mapping.py           # alert -> incident field derivation (pure function)
│   └── service.py           # orchestrates: filter firing/resolved, map, upsert, commit once
└── repositories/
    └── incident_repository.py  # extended with upsert_firing_incident() + commit()
```

Route handlers stay thin — no SQL, no engine/session construction, same
convention Phase 3B established. No second ORM, database engine,
migration framework, queue, or event broker was introduced; Flyway
remains the sole schema-owning mechanism, and `V1__create_incident_schema.sql`
was never modified.

## Verification

### Unit tests

`services/control-plane/tests/test_webhook.py` (23 tests, mocked
repository via the same `app.dependency_overrides` seam Phase 3B
established — no real database): valid authenticated firing payload;
missing/incorrect Bearer token; a server with no configured token
(fail-closed); malformed payload; missing required label; unsupported
severity; invalid fingerprint; invalid timestamp; empty batch;
multi-alert batch; mixed firing/resolved batch; resolved-only (no
incident); summary/description mapping; safe title fallback; duplicate
firing preserves identity; a forced database error returning 503, not
a false success; a simulated DNS-resolution failure also returning
503; an oversized body (and one with a dishonest, understated
`Content-Length` header) returning `413` with zero writes; a
body exactly at the size limit not being rejected for size; no secret
value in any error response. Combined with Phase 3B's existing 20
tests, `make control-plane-test` runs 43 tests total. Mocked tests are
explicitly **not** represented as proof of real PostgreSQL atomic
deduplication — that proof is below.

### Real PostgreSQL integration (`scripts/verify-webhook-ingestion.sh`, `make verify-webhook-ingestion`)

POSTs real Alertmanager-shaped payloads directly to control-plane's own
webhook endpoint (not through Alertmanager — this isolates and proves
the ingestion endpoint's own correctness; the full real chain is proven
separately below) against the real running service and real
PostgreSQL. All 10 sections passed on a real run: authentication (401,
zero writes); payload validation (422, zero writes, including an
invalid batch's otherwise-valid sibling alert); a first firing webhook
creates an incident; a repeated firing webhook updates the same
incident (id/first_seen_at/status preserved, last_seen_at advanced,
exactly one active row); a resolved historical incident is preserved
while a new active incident with the same fingerprint is created;
multiple distinct fingerprints produce distinct rows; a mixed firing/
resolved batch only writes the firing alert; a resolved-only
notification writes nothing; the existing `GET /api/v1/incidents/{id}`
exposes the ingested result; a real PostgreSQL outage returns 503 with
zero writes and ingestion resumes automatically on recovery; and
run-scoped cleanup removes only this execution's rows (fingerprint-
prefix scoped, since `source` is always the fixed literal
`"alertmanager"` — the same pattern `scripts/verify-persistence.sh`
already established for the analogous reason).

**Outage-test cleanup safety.** Section 9 deliberately stops
PostgreSQL to prove a real outage returns `503`. The script's `EXIT`
trap tracks (`POSTGRES_STOPPED_BY_THIS_SCRIPT`) whether it, specifically,
is responsible for PostgreSQL currently being stopped; if any assertion
fails after the stop but before section 9's own restart, the trap
restores PostgreSQL itself (bounded wait for `healthy`) *before*
attempting its best-effort cleanup DELETE — which could never reach a
stopped database anyway — and explicitly preserves the original
failure's exit status (captured as the trap's very first statement,
re-asserted via an explicit `exit` at the end), so this recovery logic
can never mask or change what the script reports as its own result.
Verified directly with a standalone harness that stops PostgreSQL,
forces a failure while it's still stopped, and confirms both that
PostgreSQL ends up healthy again and that the script's own exit code is
still the original `1`, not whatever the trap's internal commands
happened to return.

### Genuine end-to-end acceptance (`scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`, `make verify-alert-ingestion`)

The most important acceptance gate for this phase, and the one that
cannot be approximated: reuses the existing Phase 2B.4 real
Collector-outage lifecycle test (no second, separate outage test is
ever run) and, using that SAME real, controlled failure, additionally
proves the full genuine chain — Prometheus firing, Alertmanager's own
real webhook delivery (never a synthetic POST from a test script),
correct field mapping, and a persisted, currently-active
`reliability.incidents` row visible through the unmodified
`GET /api/v1/incidents` API (`scripts/verify-ingestion.py`, which only
reads Prometheus's, Alertmanager's, and control-plane's real HTTP
APIs — it never writes anything itself).

**The gate does not pass on partial delivery.** The expected set of
firing instances is derived from TWO independent sources and
cross-checked, not read from Alertmanager alone: Prometheus's own
`GET /api/v1/rules` (the real, currently-firing label sets for the
named rule — the ultimate source of truth for "what is actually firing
right now") is matched, by exact label-set equality, against
Alertmanager's own active alerts. Every Prometheus-reported firing
instance **must** have a matching active Alertmanager alert — if
Prometheus reports two firing instances and Alertmanager has only
activated one of them so far, the check fails closed and the bounded
poll simply retries, rather than passing on the lesser evidence. This
also means the expected instance count is never hard-coded to "2" or
any other fixed number — it is whatever Prometheus's rule actually
produced, which generalizes correctly to any alert rule, not just
`TelemetryPipelineUnavailable`. `GET /api/v1/incidents` is paginated
fully via the API's own `limit`/`offset` contract (not just its first
page), and only the currently **active** row per fingerprint is
considered — a resolved historical row sharing a fingerprint (an
expected, legitimate artifact of the dedup design) is never mistaken
for current state, and the verifier defensively fails closed if it
ever finds more than one active row for the same fingerprint (which
the database's own partial unique index should make impossible).

The incident(s) this real test creates are **not** deleted afterward —
they are genuine state from a genuine event, and future runs of this
same test are specifically designed to tolerate finding them already
there (as a pre-existing or freshly re-updated incident, via the
`--since` freshness check in `scripts/verify-ingestion.py`) rather than
requiring a clean slate.

**A real run exercised every one of these corrections' edge cases, not
just the happy path.** `TelemetryPipelineUnavailable` went inactive →
firing, with Prometheus reporting **2** real firing instances
(`active_series=2`, both scrape-target jobs). The gate's strengthened
cross-check correctly refused to pass on partial delivery: for several
poll attempts it failed closed with "Prometheus reports 2 firing
instance(s), but 1 of them have no matching ACTIVE alert in
Alertmanager yet" while Alertmanager had activated only one of the two.
It also encountered a genuinely **pre-existing** incident, left over
from an earlier real session's outage (same fingerprint, `status=open`,
`last_seen_at` from the previous day) — and correctly rejected it as
stale proof ("predates this test run's own outage... not genuinely
(re)ingested just now"), continuing to poll rather than passing. Once
Alertmanager's `group_interval` (30s) delivered a fresh update for the
whole group — both alerts share one notification group
(`group_by: [alertname, severity]`) — that pre-existing incident's
`last_seen_at` genuinely advanced past the freshness threshold at the
same moment the second instance's incident was freshly created, and
the gate correctly confirmed **both** as distinct, currently-active,
correctly-mapped incidents (`311e21e8-...` for
`otel-collector-app-metrics`, `82be66a8-...` for `otel-collector`) —
never collapsed into one. Recovery, Collector restart, and resumed
checkout telemetry all followed normally; `make verify-alert-ingestion`
exited `0`.

## Features implemented in Phase 3D (reserved at the time this document was written)

- Any incident-lifecycle transition (acknowledge, investigate,
  remediate, resolve, close) and the transition-validity rules
  governing which status may follow which — see
  [docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md).
- Making a resolved Alertmanager notification actually resolve the
  matching incident.
- An authenticated `PATCH /api/v1/incidents/{id}/status` endpoint for
  direct human/operator use.

## Still reserved for Phase 3E+

- An incident audit-history table.
- Agent-generated remediation, human approval workflows, automated
  remediation.
- Authentication for the read-only `GET /api/v1/*` API (still none —
  local development only).
