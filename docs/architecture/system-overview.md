# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

Phase 2 (observability) is **closed** as of Phase 3A. The repository
contains foundational scaffolding, a running infrastructure dependency,
four application services with the **first real service-to-service
workflow**, an **observability infrastructure stack instrumented for
all four services, with a complete, verified distributed trace across
the whole checkout workflow — persisted in and independently
re-verified from a real trace backend, Grafana Tempo (Phase 2B.1) —
each service's existing stdout/stderr logs centrally collected and
persisted via Grafana Alloy + Grafana Loki (Phase 2B.2), three Grafana
dashboards auto-provisioned from real, individually-verified queries
against that telemetry (Phase 2B.3), and a real alerting layer —
Prometheus evaluates four alert rules and routes firing alerts to
Prometheus Alertmanager, with an empirically verified full
inactive→firing→resolved lifecycle (Phase 2B.4)**, and, as of
Phase 3A, **a durable incident data foundation**: PostgreSQL's existing
`postgres` service now also holds a dedicated `reliability` schema
(`reliability.incidents`), applied through versioned Flyway migrations
and independently verified against the real database — see
[Incident domain model](#incident-domain-model-phase-3a) below and
[docs/architecture/incident-domain-model.md](incident-domain-model.md)
for full detail. As of Phase 3B, there is also a **fifth backend
application**, a read-only FastAPI control plane
(`services/control-plane`) sitting in front of `reliability.incidents`
— see [Control plane](#control-plane-phase-3b) below and
[docs/api/control-plane.md](../api/control-plane.md) for full detail.
As of Phase 3C/3D/3E it also gained authenticated write paths, a
validated lifecycle state machine, and a durable audit trail (see the
dedicated bullets below); as of **Phase 3F**, that entire Phase 3
incident-management foundation is closed out with an audited
acceptance matrix, one narrow cross-system coverage gap closed, and a
handoff runbook — see
[End-to-end acceptance and handoff](#end-to-end-acceptance-and-handoff-phase-3f)
below. As of **Phase 4**, the repository also has an opt-in,
allowlisted failure-injection scenario runner that deliberately breaks
`payment-service` or `inventory-service` against the real Compose
stack and, for the payment-service case, proves the real
Prometheus → Alertmanager → incident → audit → recovery chain through
a second, distinct real failure path (no second Collector outage) —
see [Controlled failure injection and deterministic incident
simulation](#controlled-failure-injection-and-deterministic-incident-simulation-phase-4)
below. As of **Phase 5**, the repository also has a strictly
read-only, sixth backend service — an AI incident investigator that,
given an existing incident UUID, retrieves its real evidence
(control-plane's existing GET APIs plus bounded, allowlisted,
read-only Prometheus/Loki/Tempo queries) and produces a structured,
evidence-grounded investigation via a configurable LLM, never
mutating anything — see [Read-only AI incident
investigator](#read-only-ai-incident-investigator-phase-5) below.
Conceptually, the current demo
application shape is:

```
Client
  |
  v
checkout-service :8080  --OTLP (metrics+traces)--> otel-collector
  |                                                    ^  ^  ^
  +--> payment-service      :8081  (POST /payments/authorize — instrumented) --OTLP---+  |  |
  |                                                                                       |  |
  +--> inventory-service    :8082  (POST /inventory/reservations — instrumented) --OTLP--+  |
  |                                                                                          |
  +--> notification-service :8083  (POST /notifications — instrumented) --OTLP--------------+

otel-collector --Prometheus format (metrics)--> prometheus --> grafana
otel-collector --debug exporter (traces)--> collector logs
otel-collector --OTLP (traces)--> tempo --> grafana

(all four services) --stdout/stderr (via dockerd)--> alloy --> loki --> grafana
  (a separate path: Alloy reads container logs directly from the Docker
   API, not via otel-collector or any OTEL_* setting above)

prometheus --alert rules (rules/alerts.yml)--> alertmanager --webhook (internal, Bearer auth)--> control-plane :8000
  (Prometheus is the only rule evaluator; Alertmanager only receives,
   groups, and tracks alert state — it never evaluates a PromQL
   expression itself. As of Phase 3C, Alertmanager's one receiver is a
   REAL webhook to control-plane's internal ingestion endpoint — no
   longer a no-op local sink. Still no email/Slack/PagerDuty.)

alertmanager --POST /internal/v1/alertmanager/webhook--> control-plane --atomic upsert/resolve--> postgres (reliability.incidents)
  (Phase 3C: a real firing alert automatically creates or updates a
   persistent incident, deduplicated per-fingerprint via the real
   partial unique index Phase 3A defined
   (incidents_active_fingerprint_uniq). As of Phase 3D, a real resolved
   notification whose fingerprint matches a currently-active incident
   genuinely resolves it (occurrence-identity/stale-replay safe, never
   auto-closing) — see docs/architecture/phase-3c-alert-ingestion.md
   and docs/architecture/phase-3d-incident-lifecycle.md.)

human/operator (authenticated, distinct token) --PATCH /api/v1/incidents/{id}/status--> control-plane --atomic compare-and-swap--> postgres (reliability.incidents)
  (Phase 3D: a centralized, validated state machine governs every
   transition; expected_status is a mandatory optimistic-concurrency
   guard, enforced via a real atomic conditional UPDATE, proven
   race-free under 10 genuinely concurrent real requests — see
   docs/architecture/phase-3d-incident-lifecycle.md.)

postgres (reliability.incidents) --SQLAlchemy async / asyncpg--> control-plane :8000 --> (future) operations console
  (GET /api/v1/incidents and GET /api/v1/incidents/{id} remain
   read-only and unauthenticated, exactly as Phase 3B left them. The
   two write paths are the Alertmanager webhook and the Phase 3D
   lifecycle PATCH above — there is still no generic incident-editing
   API.)

Complete distributed trace (one real POST /checkouts, now persisted in Tempo):
                    +-> checkout payment CLIENT      -> payment SERVER
  checkout SERVER --|-> checkout inventory CLIENT    -> inventory SERVER
                    +-> checkout notification CLIENT -> notification SERVER
  (all seven spans share one Trace ID; each downstream SERVER span's
   Parent ID == its own checkout CLIENT span's Span ID; payment,
   inventory, and notification are sibling branches off the one
   checkout SERVER span — NOT a sequential chain)
```

`checkout-service` is instrumented with the OpenTelemetry Java
auto-instrumentation agent; `payment-service` with OpenTelemetry Python
zero-code auto-instrumentation (Phase 2A.3); `inventory-service` with
explicit, minimal OpenTelemetry Go SDK initialization plus `otelhttp`
(Phase 2A.4); and `notification-service` with explicit OpenTelemetry
Node SDK initialization plus `@opentelemetry/instrumentation-http` and
`@fastify/otel` (Phase 2A.5) — Go and Node have no auto-instrumentation
equivalent to the Java agent or Python's zero-code distro. All four
export real metrics and traces to the Collector, and a real
`POST /checkouts` request proves a complete distributed trace: ONE
trace contains checkout's own SERVER span as the common parent of three
independently-verified downstream branches (verified against real
Collector output, not assumed, and reconfirmed on a second, fully
torn-down-and-restarted run). As of Phase 2B.1, the Collector's traces
pipeline also exports to **Grafana Tempo 3.0.3**, a persistent,
queryable trace backend; that exact same trace has been independently
retrieved and re-verified directly from Tempo's own HTTP query API, and
confirmed to survive a graceful Tempo restart using its persistent
volume.

`checkout-service`'s `POST /checkouts` synchronously calls the other
three services, in that exact order (payment, then inventory, then
notification), stopping immediately on the first failure. Payment,
inventory, and notification never call each other or call back into
checkout-service. None of the four services talks to PostgreSQL, which
exists alongside them as a separate, currently-unused infrastructure
dependency. There is intentionally no rollback/compensation for
already-succeeded steps, no retries, and no persistence of the checkout
itself — see the `checkout-service` entry below for detail.

Full inventory:

- Repository-level documentation (`README.md`, this document, ADR records)
- Standard configuration files (`.gitignore`, `.editorconfig`, `.env.example`)
- A local environment-check script (`scripts/check-env.sh`)
- **PostgreSQL 18**, run locally via Docker Compose (`docker-compose.yml`),
  configured entirely through environment variables, with a named Docker
  volume for persistent storage and a healthcheck based on `pg_isready`.
  This is the first piece of the planned "durable state" component below
  to actually exist. As of Phase 3A, it holds a real schema
  (`reliability`, applied via versioned migrations — see below); it
  still has no application code connecting to it (no API, no agent).
- **Incident domain model** (Phase 3A, `database/migrations/V1__create_incident_schema.sql`,
  applied via a pinned `flyway/flyway:13.9.0` Compose service gated
  behind `profiles: ["tools"]` so it never runs on a normal `docker
  compose up -d`): a dedicated `reliability` schema (never `public`,
  which already held an unrelated pre-existing Phase 0 table,
  `phase_02_verification`, confirmed untouched) holding one table,
  `reliability.incidents` — `id` (UUID), `source`,
  `source_fingerprint`, `title`, `description`, `severity`
  (`critical`/`warning`/`info`), `status` (six-value vocabulary,
  default `open`), `first_seen_at`/`last_seen_at`/`resolved_at`/
  `created_at`/`updated_at` (all `TIMESTAMPTZ`). Deduplication: a
  partial unique index on `(source, source_fingerprint) WHERE status
  NOT IN ('resolved', 'closed')` — at most one active incident per
  fingerprint, with resolved/closed rows preserved as history, enforced
  by PostgreSQL itself, confirmed directly including the
  resolved-then-recurred-allowed case. Full detail:
  [docs/architecture/incident-domain-model.md](incident-domain-model.md).
  Verified by `scripts/verify-persistence.sh` (`make verify-persistence`,
  also run in CI) against the real database — not SQLite, not mocked.
  This phase built the data foundation only; Alertmanager ingestion
  (Phase 3C) and lifecycle transition validation (Phase 3D) were both
  added later, as application code against this unchanged schema.
- **Control plane** (Phase 3B, extended Phase 3C,
  `services/control-plane`): a **FastAPI** service, the fifth backend
  application in this repository (but explicitly not one of the four
  demo commerce services above, and not yet instrumented with
  OpenTelemetry). Its `GET /api/v1/incidents` (status/severity/source
  filters, pagination, deterministic `last_seen_at DESC, id DESC`
  ordering), `GET /api/v1/incidents/{id}`, `GET /health/live`, and
  `GET /health/ready` endpoints remain exactly as read-only and
  unauthenticated as Phase 3B left them. It connects via SQLAlchemy 2.x
  async + `asyncpg`, credentials from environment variables only, and
  never calls `metadata.create_all()` — Flyway remains the sole schema
  owner. Engine construction is non-blocking, so the service stays up
  and `/health/ready` correctly reports `503` if PostgreSQL or the
  `reliability` schema is temporarily unavailable (e.g. migrations not
  yet applied, or PostgreSQL mid-restart), recovering on its own once
  they become available — verified empirically against a real,
  unmigrated database and a real PostgreSQL restart, with no manual
  container restart. Runs via the existing `docker-compose.yml`
  (`control-plane` service, `127.0.0.1:8000`), does not depend on the
  `flyway` service automatically, and has no new persistent volume.
  As of **Phase 3C**, it also exposes an authenticated write path,
  `POST /internal/v1/alertmanager/webhook` (Bearer token, constant-time
  comparison, fail-closed if unconfigured), reachable only over the
  internal Compose network — Alertmanager's own real webhook delivery
  now automatically creates or updates a `reliability.incidents` row
  for a genuine firing alert, deduplicated per-fingerprint via a real
  atomic PostgreSQL upsert against the same partial unique index Phase
  3A defined. As of **Phase 3D**, a resolved Alertmanager notification
  now genuinely resolves the matching active incident (occurrence-
  identity/stale-replay safe, real `resolved_at`, never auto-closing),
  and a second authenticated write path,
  `PATCH /api/v1/incidents/{id}/status` (a distinct Bearer token from
  the webhook's), lets a human/operator drive the rest of a
  centralized, validated state machine under real optimistic
  concurrency. As of **Phase 3E**, every one of those accepted
  mutations also durably records a matching, append-only audit event
  in the SAME transaction as the mutation — see
  [Alert ingestion](#alert-ingestion-phase-3c),
  [Incident lifecycle](#incident-lifecycle-phase-3d), and
  [Incident audit trail](#incident-audit-trail-phase-3e) below. Full
  detail: [docs/api/control-plane.md](../api/control-plane.md),
  [docs/architecture/phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md),
  [docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md),
  and
  [docs/architecture/phase-3e-incident-audit.md](phase-3e-incident-audit.md).
  Verified by `scripts/verify-control-plane.sh`
  (`make verify-control-plane`), `scripts/verify-webhook-ingestion.sh`
  (`make verify-webhook-ingestion`),
  `scripts/verify-incident-lifecycle.sh`
  (`make verify-incident-lifecycle`),
  `scripts/verify-incident-audit.sh` (`make verify-incident-audit`),
  and `scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`
  (`make verify-alert-ingestion`) — all run in CI — against the real,
  running, PostgreSQL-backed service, including a genuine Prometheus
  alert delivered through Alertmanager's own real webhook, now proven
  all the way through to real resolution and a genuine, correctly-
  attributed audit trail. **Still planned:** authentication on the
  read API, and any consumption by an agent or operations console.
- **Alert ingestion** (Phase 3C, `observability/alertmanager/alertmanager.yml`
  + `scripts/init-webhook-secret.sh`): Alertmanager's single receiver
  was changed from a no-op `local-null` sink to a real webhook
  (`control-plane-webhook`), reached over Compose's internal DNS
  (`http://control-plane:8000/internal/v1/alertmanager/webhook`, never
  a published host port) and authenticated via
  `http_config.authorization.credentials_file`, pointed at a
  locally-generated, gitignored secret file — never a literal token in
  the config. `send_resolved: true` is enabled; `group_by`/
  `group_wait`/`group_interval`/`repeat_interval` are unchanged from
  Phase 2B.4. `scripts/init-webhook-secret.sh` generates one
  cryptographically random Bearer token and mirrors it into both `.env`
  (`CONTROL_PLANE_WEBHOOK_TOKEN`, read by control-plane) and that secret
  file — idempotent, never silently rotates an already-distributed
  secret, wired into `make db-up` so a normal `docker compose up -d`
  has a working webhook by default. **Empirically proven end to end**,
  not merely configured: a real, controlled `otel-collector` outage
  (the same one Phase 2B.4's `scripts/verify-alert-lifecycle.sh` was
  already using) was independently confirmed, via
  `scripts/verify-ingestion.py` (which only reads Alertmanager's and
  control-plane's own HTTP APIs — it posts nothing itself), to result
  in a real `TelemetryPipelineUnavailable` firing alert being delivered
  by Alertmanager's own webhook and persisted as a correctly-mapped,
  currently-active incident. Full detail:
  [docs/architecture/phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md).
- **Incident lifecycle** (Phase 3D,
  `src/control_plane/domain/lifecycle.py` +
  `src/control_plane/api/incidents.py`'s PATCH route +
  `src/control_plane/ingestion/service.py`'s resolution logic): a
  centralized state machine (`open -> {acknowledged, investigating,
  resolved}`, `acknowledged -> {investigating, resolved}`,
  `investigating -> {remediating, resolved}`, `remediating ->
  {investigating, resolved}`, `resolved -> {closed}`, `closed ->
  {}`) is the single source of truth for every transition — no
  transition logic duplicated in routes, SQL, or the webhook handler.
  A new authenticated `PATCH /api/v1/incidents/{id}/status` endpoint
  (a second, independently random Bearer token,
  `CONTROL_PLANE_LIFECYCLE_TOKEN`, distinct from the webhook's) lets a
  human/operator drive it, with `expected_status` as a mandatory
  optimistic-concurrency guard enforced by a real atomic conditional
  `UPDATE` — proven race-free under 10 genuinely concurrent real
  requests (exactly 1 success, 9 correctly rejected). The same
  Alertmanager webhook endpoint from Phase 3C now also genuinely
  resolves a matching active incident from a real resolved
  notification, using `(source, fingerprint, startsAt)` occurrence
  identity compared against a durable occurrence watermark
  (`occurrence_starts_at`, added by a post-review Flyway migration,
  `V2__add_occurrence_watermark.sql` — separate from the immutable
  `first_seen_at`) to safely distinguish a repeat delivery, a
  stale/delayed replay, and a genuine recurrence — real PostgreSQL
  testing against accumulated state (not a clean slate) found and
  fixed real regressions in this exact area, documented in full. This
  transition matrix is enforced at the application layer only, not a
  database `CHECK` constraint. Full detail:
  [docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md).
- **Incident audit trail** (Phase 3E,
  `database/migrations/V3__create_incident_audit.sql` +
  `src/control_plane/repositories/incident_repository.py`): a new,
  durable, append-only table, `reliability.incident_events`, records
  every accepted incident creation, accepted firing observation,
  operator status transition, and automatic Alertmanager resolution —
  in the SAME PostgreSQL transaction as the incident change itself, so
  an audit-insert failure rolls back the incident mutation too (proven
  against real PostgreSQL, not merely designed that way). A real,
  database-level trigger rejects any `UPDATE`/`DELETE` against this
  table, and its foreign key to `reliability.incidents` is `ON DELETE
  RESTRICT` — an incident with recorded audit history can never be
  deleted. A new, unauthenticated, read-only
  `GET /api/v1/incidents/{id}/events` exposes the timeline; no
  audit-creation or mutation endpoint exists anywhere. No history is
  invented for incidents that predate this phase — an empty timeline
  on a pre-existing incident is valid, expected behavior. Full detail:
  [docs/architecture/phase-3e-incident-audit.md](phase-3e-incident-audit.md).
- **End-to-end acceptance and handoff** (Phase 3F — closes Phase 3 as
  a whole; no new migration, endpoint, or verifier script): an audited
  acceptance matrix mapping every Phase 3A–3E capability to its
  already-existing real verification gate, one narrow cross-system gap
  closed in the single existing Collector-outage acceptance test
  (`scripts/verify-ingestion.py` now traces a persisted `created`
  audit event's own `metadata.source_fingerprint` back to the real
  Alertmanager fingerprint that produced it, not just the incident
  row), and a reproducible operations runbook. Full detail:
  [docs/architecture/phase-3f-acceptance-and-handoff.md](phase-3f-acceptance-and-handoff.md).
- **Controlled failure injection and deterministic incident
  simulation** (Phase 4, `scripts/simulate-failure.sh`): an opt-in
  scenario runner that deliberately stops exactly one allowlisted real
  dependency (`payment-service` or `inventory-service` — never
  PostgreSQL or any other infrastructure, and no Docker volume),
  verifies checkout-service's real safe `502` response identifies the
  correct failed dependency, restores it (a trap armed before the stop
  covers success, failure, Ctrl+C, and termination, idempotently, and
  verifies health rather than trusting `docker compose start`'s exit
  code), and confirms a fresh checkout succeeds. `payment-outage
  --full-acceptance` additionally reuses the existing, unmodified
  `CheckoutServerErrors` Prometheus rule and the existing, unmodified
  `scripts/verify-alerting.py`/`scripts/verify-ingestion.py` to prove
  the complete real chain end to end: real outage → real failing
  checkouts → genuine HTTP 5xx metrics → the rule firing → a real
  Alertmanager webhook delivery → a persisted, fingerprint-matched
  incident → restoration → real recovery → genuine automatic
  resolution → a correctly-attributed audit trail — a second, distinct
  real failure path through the same Phase 3A–3F machinery, not a
  second Collector outage. Testing this directly discovered a real gap
  (checkout-service's downstream `RestClient`s had no connect/read
  timeout, so a dependency stopped mid-connection could hang a request
  indefinitely) and fixed it narrowly with one new
  `RestClientCustomizer` bean, with no change to any of the three
  downstream client classes. Full detail:
  [docs/architecture/phase-4-failure-simulation.md](phase-4-failure-simulation.md).
- **Read-only AI incident investigator** (Phase 5,
  `services/investigator-service`): a new, sixth backend application,
  strictly read-only. Given an existing incident UUID
  (`POST /api/v1/investigations`), it retrieves that incident's real
  evidence — control-plane's existing `GET /api/v1/incidents/{id}` and
  `GET /api/v1/incidents/{id}/events` (mandatory, fully paginated) plus
  four allowlisted Prometheus range queries, one allowlisted Loki
  query, and one allowlisted Tempo tag search (each best-effort,
  scoped to the incident's own real time window, bounded in count/
  length) — assembles a normalized, attributed evidence package
  (`E1`, `E2`, ...), and passes it to a real, configurable LLM
  (OpenAI by default; a `StubProvider` for tests and for
  `scripts/verify-investigator.sh` only) to produce a structured
  investigation: direct observations and unconfirmed hypotheses are
  kept explicitly separate, every material claim must cite a real
  evidence id (fabricated citations are stripped and recorded, not
  trusted), missing/unavailable evidence is reported honestly (Tempo
  results are "candidate traces", never a confirmed causal link —
  Phase 2B.2's trace/span-ID-in-logs gap is still real), and only
  read-only diagnostic suggestions are ever produced. It holds neither
  of control-plane's write-capable Bearer tokens and no PostgreSQL
  credentials; its control-plane client has exactly two `GET` methods,
  confirmed by an AST-level test to never call a write HTTP verb. No
  Flyway migration was added. Full detail:
  [docs/architecture/phase-5-ai-investigator.md](phase-5-ai-investigator.md).
- **`checkout-service`** (`services/checkout-service`), a Java 21 / Spring
  Boot 3 Maven project — the first piece of the planned "demonstration
  target system" below to actually exist, and now its **orchestrator**.
  It runs through the same Docker Compose environment as PostgreSQL, but
  does not connect to it.

  **Implemented in this service:**
  - Application bootstrap (`CheckoutServiceApplication`)
  - `GET /health` — a small typed JSON health response
  - `GET /actuator/health` — Spring Boot Actuator health (only `health`
    is exposed)
  - `POST /checkouts` — generates a `checkout_id` (`chk_<uuid>`), then
    synchronously calls `payment-service` → `inventory-service` →
    `notification-service` (via small `RestClient`-based client classes,
    `PaymentClient`/`InventoryClient`/`NotificationClient`, each doing
    only HTTP transport). `CheckoutOrchestrationService` validates each
    response before proceeding to the next step: the required downstream
    result ID (`payment_id`/`reservation_id`/`notification_id`) is
    non-null/non-blank, the returned `checkout_id` matches the one it
    generated and sent, and the response has the expected business
    status. Stops immediately on the first failure — no later step is
    called. Returns a typed `CheckoutResponse` combining all three
    downstream results.
  - Downstream failures — non-2xx, connection failure, empty response,
    an unexpected business status, or a malformed/inconsistent
    successful (HTTP 200) response (a missing/blank required result ID
    or a mismatched `checkout_id`) — are normalized by a
    `@RestControllerAdvice` into a safe HTTP 502 with a fixed
    `{"error": "downstream_failure", "service": "...", "message": "Downstream service request failed"}`
    body — no stack traces, URLs, or downstream bodies are ever exposed.
  - Request validation (`spring-boot-starter-validation`: `@NotBlank`,
    `@Positive`, `@Pattern`) on `POST /checkouts`
  - Downstream base URLs configurable via `CHECKOUT_PAYMENT_BASE_URL` /
    `CHECKOUT_INVENTORY_BASE_URL` / `CHECKOUT_NOTIFICATION_BASE_URL`
  - Automated tests: controller contract tests, orchestration-service
    unit tests (Mockito, including call order and failure short-
    circuiting), and downstream-client serialization tests
    (`MockRestServiceServer`), plus the existing health tests
  - A multi-stage Dockerfile producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck
  - **(Phase 2A.2) OpenTelemetry instrumentation** via the pinned Java
    auto-instrumentation agent (`v2.31.1`), attached only in Docker
    Compose (`JAVA_TOOL_OPTIONS`, not baked into the image's
    `ENTRYPOINT`): exports a SERVER span + HTTP server metrics for
    `POST /checkouts`, CLIENT spans + HTTP client metrics for each of
    the three downstream `RestClient` calls, and JVM runtime metrics,
    via OTLP to the Collector. No custom business metrics or manual
    spans were added — this is auto-instrumentation only.

  **Not implemented in this service:**
  - Rollback/compensation for an already-authorized payment or
    already-reserved inventory if a later step fails
  - Retries, backoff, circuit breakers, or timeouts configuration beyond
    Spring/JDK defaults
  - Idempotency (identical requests currently produce independent
    checkouts with different IDs)
  - Persistence of checkouts (nothing is stored; PostgreSQL is untouched)
  - Application log export (`OTEL_LOGS_EXPORTER=none`, deliberately
    deferred) and a real trace backend (traces are only visible via the
    Collector's `debug` exporter logs this phase)
  - Asynchronous messaging, queues, or event-driven communication
  - Agent functionality of any kind

- **`payment-service`** (`services/payment-service`), a Python 3.13 /
  FastAPI project (`src`-layout, `pyproject.toml`) — the second piece of
  the planned "demonstration target system" below to actually exist. It
  runs through the same Docker Compose environment as PostgreSQL. It is
  now called by `checkout-service` (the first step of `POST /checkouts`);
  it does not call `checkout-service`, or any other service, itself.

  **Implemented in this service:**
  - Application bootstrap (`payment_service.main:app`)
  - `GET /health` — a small typed (Pydantic) JSON health response
  - `POST /payments/authorize` — a **simulated** payment authorization:
    validates `checkout_id`/`amount_cents`/`currency` (integer cents, no
    floats), generates a `payment_id` (UUID), and always returns
    `status: "AUTHORIZED"`. Not connected to any real payment provider.
  - Automated tests (health endpoint + authorization endpoint, including
    validation-failure cases, via FastAPI's `TestClient`)
  - A single-stage Dockerfile producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck
  - **(Phase 2A.3) OpenTelemetry instrumentation** via zero-code
    auto-instrumentation (`opentelemetry-distro`,
    `opentelemetry-instrumentation-fastapi`,
    `opentelemetry-exporter-otlp-proto-http`, all pinned), activated only
    in Docker Compose by wrapping the same Uvicorn command with
    `opentelemetry-instrument` — no source changes under
    `services/payment-service/src/payment_service/`. Exports a SERVER
    span + HTTP server metrics for `POST /payments/authorize`. A real
    checkout request proves this SERVER span continues the trace begun
    by checkout-service's own CLIENT span for the same call (shared
    Trace ID, correct parent/child Span IDs).

  **Not implemented in this service:**
  - Any real payment processing (no payment provider, e.g. Stripe)
  - Declines, failures, or artificial latency (every authorization
    currently succeeds deterministically)
  - Calling out to any other service itself (it is only ever called)
  - Inventory integration
  - Database access or payment history of any kind
  - Application log export via OTel, and a real trace backend (traces
    are only visible via the Collector's `debug` exporter logs)
  - Communication with any other service
  - Agent functionality of any kind

- **`inventory-service`** (`services/inventory-service`), a Go 1.27
  project using only the standard library — the third piece of the
  planned "demonstration target system" below to actually exist. It runs
  through the same Docker Compose environment as PostgreSQL. It is now
  called by `checkout-service` (the second step of `POST /checkouts`,
  after a successful payment authorization); it does not call
  `checkout-service`, `payment-service`, or any other service itself.

  **Implemented in this service:**
  - Application bootstrap with graceful shutdown (`SIGTERM`/`SIGINT`)
  - `GET /health` — a small typed JSON health response (other methods
    on `/health` return HTTP 405)
  - `POST /inventory/reservations` — a **simulated** inventory
    reservation: strictly validates `checkout_id`/`sku`/`quantity`
    (rejecting unknown fields and malformed JSON), generates a
    `reservation_id` (UUID v4 via `crypto/rand`, no external UUID
    dependency), and always returns `status: "RESERVED"`. Not backed by
    a database or real stock; other methods on this path return HTTP 405
    with `Allow: POST`.
  - An `http.Server` with explicit read/write/idle timeouts
  - Automated tests (`go test`, using `net/http/httptest`, covering both
    endpoints and the reservation/UUID business logic directly)
  - A multi-stage Dockerfile (`golang:1.27` builder running
    `gofmt`/`go vet`/`go test` → `distroless/static-debian12:nonroot`
    runtime) producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck (via the
    binary's own `healthcheck` subcommand, since the distroless runtime
    has no shell or curl/wget)
  - **(Phase 2A.4) OpenTelemetry instrumentation** via explicit, minimal
    Go SDK initialization (new `internal/telemetry` package: OTLP/HTTP
    trace + metric exporters, a resource built from
    `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES`, a global
    `tracecontext`+`baggage` propagator) plus `otelhttp` wrapping the
    whole `http.ServeMux` at the server boundary — zero changes to this
    service's business logic. Telemetry is only initialized in the
    normal server path, never for the `healthcheck` subcommand (which
    still exits before that code runs). Exports a SERVER span + HTTP
    server metrics for `POST /inventory/reservations`. No custom
    metrics or manual spans were added — this is otelhttp
    instrumentation only.

  **Not implemented in this service:**
  - Real stock levels, stock decrementing/restoration, or out-of-stock
    behavior (every valid reservation currently succeeds deterministically)
  - Persistence of reservations (nothing is stored; identical requests
    produce different `reservation_id`s each time)
  - Calling out to any other service itself (it is only ever called)
  - Database access of any kind
  - Application log export via OTel, and a real trace backend (traces
    are only visible via the Collector's `debug` exporter logs)
  - Agent functionality of any kind

- **`notification-service`** (`services/notification-service`), a
  Node.js 24 / TypeScript (strict) / Fastify project using npm — the
  fourth piece of the planned "demonstration target system" below to
  actually exist. It runs through the same Docker Compose environment as
  PostgreSQL. It is now called by `checkout-service` (the third and
  final step of `POST /checkouts`, after a successful inventory
  reservation); it does not call `checkout-service`, `payment-service`,
  `inventory-service`, or any other service itself.

  **Implemented in this service:**
  - A Fastify application factory (`src/app.ts`) that builds the app
    without binding a port, and a `src/server.ts` entrypoint that binds
    it and shuts it down gracefully on `SIGTERM`/`SIGINT`
  - `GET /health` — a small typed JSON health response (`POST /health`
    returns HTTP 404, not the valid response)
  - `POST /notifications` — a **simulated** notification trigger:
    validates `checkout_id`/`kind`/`recipient` using Fastify's built-in
    JSON-schema (Ajv) request validation (`kind` constrained to exactly
    `"ORDER_CONFIRMATION"`), generates a `notification_id` via
    `crypto.randomUUID()`, and always returns `status: "ACCEPTED"`. No
    real email/SMS/push provider, no persistence, no queue; other
    methods on this path are not registered, so they get Fastify's
    normal 404.
  - Automated tests (`node:test` + Fastify's `inject()`, run via `tsx`,
    covering both endpoints)
  - A multi-stage Dockerfile (`node:24` builder running `npm ci`,
    typecheck, tests, and the TypeScript build → `node:24-slim` runtime
    with only production dependencies, running as the official image's
    `node` user) producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck (Node's built-in
    `fetch` with a bounded timeout, since curl/wget were not installed
    solely for this purpose)
  - **(Phase 2A.5) OpenTelemetry instrumentation** via explicit `NodeSDK`
    initialization in a new `src/telemetry.ts` (`@opentelemetry/instrumentation-http`
    plus `@fastify/otel`'s `FastifyOtelInstrumentation`, not the
    deprecated `@opentelemetry/instrumentation-fastify`), started from a
    new dedicated bootstrap entrypoint (`src/bootstrap.ts` →
    `dist/bootstrap.js`, now the Dockerfile `CMD`) that starts telemetry
    before dynamically importing `server.js` — required ESM ordering so
    `@fastify/otel`'s module-patching takes effect before Fastify is
    ever constructed. Zero changes to `src/routes/`, `src/services/`, or
    `src/types/`; `app.ts` unchanged. Exports a SERVER span + HTTP
    server metrics for `POST /notifications`. No custom metrics or
    manual spans — auto-instrumentation only.

  **Not implemented in this service:**
  - Any actual notification delivery (email, SMS, push) or external
    provider (no SendGrid/Twilio/SES)
  - Persistence of notifications or a notification history
  - Event consumption, a message queue, or Kafka/Redpanda usage
  - Calling out to any other service itself (it is only ever called)
  - Database access of any kind
  - Application log export via OTel, and a real trace backend (traces
    are only visible via the Collector's `debug` exporter logs)
  - Agent functionality of any kind

- **Observability infrastructure** (`observability/`) — an OpenTelemetry
  Collector, Prometheus, Grafana, (Phase 2B.1) Grafana Tempo,
  (Phase 2B.2) Grafana Loki + Grafana Alloy, and (Phase 2B.4)
  Prometheus Alertmanager, all running via Docker Compose
  (`otel-collector`, `prometheus`, `grafana`, `tempo`, `loki`, `alloy`,
  `alertmanager`). As of Phase 2A.5, this is fed by **all four**
  application services; as of Phase 2B.1, traces are also persisted in
  and queryable from Tempo, not just visible in Collector logs; as of
  Phase 2B.2, each service's existing stdout/stderr logs are also
  centrally collected and persisted in Loki, via a completely separate
  path from the Collector; as of Phase 2B.3, Grafana also
  auto-provisions three dashboards built from queries independently
  verified against this real telemetry; as of Phase 2B.4, Prometheus
  evaluates real alert rules against this same telemetry and routes
  firing alerts to Alertmanager.

  **Implemented:**
  - `otel-collector` (`otel/opentelemetry-collector-contrib:0.161.0`):
    an OTLP receiver (gRPC `:4317`, HTTP `:4318`) → `batch` processor,
    fanning out to two pipelines — metrics → Prometheus exporter
    (`:8889`, with `resource_to_telemetry_conversion` enabled so OTel
    resource attributes like `service.name` become Prometheus labels),
    and traces → **two** exporters — `debug` (detailed span output to
    the Collector's own container logs; kept because the local verifier
    and `scripts/parse-checkout-trace.py` still read it) and, as of
    Phase 2B.1, `otlp_grpc/tempo` (exports to Tempo's internal OTLP
    receiver over the Compose network — the `otlp_grpc` type is used
    explicitly, not the deprecated `otlp` alias, confirmed via a real
    Collector deprecation warning hit during implementation); a
    `health_check` extension (`:13133`); and separate internal ("self")
    telemetry on `:8888`. The official Contrib image has no
    shell/wget/curl, so it has no Docker-level healthcheck; its
    liveness is proven instead by Prometheus successfully scraping it.
  - `prometheus` (`prom/prometheus:v3.15.0`): scrapes itself, the
    Collector's self-telemetry, and the Collector's telemetry-relay
    endpoint — which now carries real HTTP server metrics (and, for
    checkout-service, HTTP client + JVM metrics) from all four
    application services — on a persistent named volume
    (`prometheus_data`), with a `wget`-based healthcheck.
  - `tempo` (`grafana/tempo:3.0.3`, Phase 2B.1): a persistent, queryable
    distributed-tracing backend running in monolithic mode (`target`
    defaults to `all`), local filesystem storage under `/var/tempo` on
    a persistent named volume (`tempo_data`), single-tenant (no
    multitenancy/auth configured). Its internal OTLP receiver (gRPC
    `:4317`, HTTP `:4318`) is not published to the host — only
    otel-collector reaches it, as `tempo:4317`. Only its HTTP query API
    (`:3200`) is published, to `127.0.0.1` like every other
    observability port. No shell/curl/wget in this image either
    (`ENTRYPOINT` is the `/tempo` binary directly); its Docker
    healthcheck uses the binary's own built-in `-health` mode instead.
  - `loki` (`grafana/loki:3.7.8`, Phase 2B.2): a persistent, queryable
    log-storage backend running in single-binary mode, single-tenant,
    local filesystem storage under `/loki` on a persistent named volume
    (`loki_data`), TSDB index + schema `v13` (this image version's own
    current default, confirmed empirically), 7-day retention via the
    `compactor`. Only its HTTP API (`:3100`) is published, to
    `127.0.0.1`. No shell/curl/wget and no `-health`-style CLI flag in
    this image (unlike Tempo), so readiness is checked purely
    externally via `GET /ready`.
  - `alloy` (`grafana/alloy:v1.20.1`, Phase 2B.2): reads
    `/var/run/docker.sock` to discover containers via the Docker API,
    filters them to this Compose project's four application services
    only (via `discovery.relabel`, matched against
    `com.docker.compose.project`/`com.docker.compose.service` container
    labels — the project match uses `sys.env("COMPOSE_PROJECT_NAME")`,
    sourced from Compose's own `${COMPOSE_PROJECT_NAME}` interpolation
    variable, not a hard-coded name, so it still works under a
    differently-named checkout directory without risking a match
    against an unrelated Compose project), and ships their logs to Loki
    via `loki.write`. Has a shell but no curl/wget, so readiness is
    likewise checked externally, via its own `GET
    /api/v0/web/components` API. Its debug HTTP interface (`:12345`) is
    published to `127.0.0.1` only. Mounts the Docker socket read-only,
    which grants full Docker daemon API access — the `:ro` does not
    restrict which Docker API calls can be made through it, only
    prevents replacing the socket file itself; this is documented, not
    glossed over, including that this same mount is also active under
    CI (see the README's Phase 2B.2 entry for the full reasoning).
  - `alertmanager` (`prom/alertmanager:v0.34.1`, Phase 2B.4): receives
    alerts Prometheus fires, groups them
    (`group_by: [alertname, severity]`), and tracks their
    firing/resolved state through its own real API
    (`GET /api/v2/alerts`, `GET /api/v2/status`). Single-instance,
    persistent local storage (`alertmanager_data`). Its single receiver
    has no integration configured at all — a normal, valid "null"
    receiver, not an invented notification service — so it still
    receives/groups/tracks every alert but sends nothing anywhere. Has
    both a shell and `wget` (confirmed via direct inspection, unlike
    loki/alloy), so it has a real Docker-level healthcheck.
  - `grafana` (`grafana/grafana-oss:13.0.2`): Prometheus (default),
    Tempo (Phase 2B.1), Loki (Phase 2B.2), and Alertmanager
    (Phase 2B.4, `type: alertmanager`,
    `jsonData.implementation: prometheus`) are all auto-provisioned
    as datasources via
    `observability/grafana/provisioning/datasources/datasource.yml`
    (resolving `http://prometheus:9090`/`http://tempo:3200`/
    `http://loki:3100`/`http://alertmanager:9093` by Compose service
    name, not `localhost`) — no manual click-through setup needed after
    `docker compose up`. The Alertmanager datasource was proven
    genuinely functional (not just configured) via a real request
    through Grafana's own datasource proxy, which returned
    Alertmanager's real cluster status and version. As of
    Phase 2B.3, three dashboards are also auto-provisioned via a
    second, separate mount for
    `observability/grafana/provisioning/dashboards` (Application
    Health, Centralized Logging, Observability Infrastructure — see
    below). Datasources are referenced by name in dashboard JSON
    (`"Prometheus"`/`"Loki"`), not by UID: an explicit `uid:` in
    `datasource.yml` was tried and reverted after it broke Grafana
    startup against an already-populated `grafana_data` volume from an
    earlier phase (`Datasource provisioning error: data source not
    found`) — reproduced and confirmed empirically, not assumed.
    Persistent named volume (`grafana_data`). Anonymous auth disabled;
    admin credentials come from `.env`
    (`GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`), local-only
    placeholders, never a real credential.
  - **Dashboards** (Phase 2B.3,
    `observability/grafana/provisioning/dashboards/json/`): three
    provisioned dashboards, all built from metrics/labels/queries
    confirmed against a real running stack before being written —
    **Application Health** (Prometheus: per-service HTTP throughput,
    p50/p95 latency via `histogram_quantile` over
    `http_server_request_duration_seconds_bucket`, 4xx/5xx error rate
    via the real `http_response_status_code` label, and
    checkout-service's downstream dependency traffic/latency via
    `http_client_request_duration_seconds_*`, behind a `service`
    template variable); **Centralized Logging** (Loki: a log-line-rate
    panel using LogQL's `rate()` — not `count_over_time()`, which
    returns a raw count per window rather than a rate, and was corrected
    after review — and a raw log-stream panel, behind a `log_service`
    variable — deliberately no severity filter, since Loki's
    `detected_level` heuristic was confirmed unreliable for
    inventory-service and notification-service); **Observability
    Infrastructure** (Prometheus: scrape-target `up`, and the OTel
    Collector's own self-telemetry — `otelcol_receiver_accepted_spans`/
    `_accepted_metric_points`/`_refused_spans`/`_refused_metric_points`,
    `otelcol_exporter_sent_spans`/`_queue_size`, `otelcol_process_uptime`).
    Verified through Grafana's real API by
    `scripts/verify-grafana-dashboards.py`, which also independently
    re-executes every panel's own PromQL/LogQL (with dashboard/interval
    variables substituted for real values) directly against
    Prometheus/Loki (not just checking the dashboard JSON exists, and
    not a separately maintained query list that could drift from what
    the dashboards actually ship).
  - **Alert rules** (Phase 2B.4, `observability/prometheus/rules/alerts.yml`,
    evaluated by Prometheus, not Grafana): `TelemetryPipelineUnavailable`
    (`up{job=~"otel-collector|otel-collector-app-metrics"} == 0`,
    `for: 1m` — the deterministic rule used for the lifecycle test
    below); `CheckoutServerErrors` (real HTTP 5xx on checkout-service,
    `for: 2m`); `CheckoutHighLatency` (`histogram_quantile(0.95, ...)
    > 1` for `/checkouts`, threshold set from an observed real baseline
    of ~10-25ms, `for: 2m`); `CollectorRefusingTelemetry` (real
    `otelcol_receiver_refused_spans`/`_refused_metric_points` activity,
    `for: 1m`). Every rule carries `severity`/`component` labels (plus
    `service` or `category` where appropriate) and `summary`/
    `description` annotations. Validated with the real pinned
    Prometheus image's own `promtool check rules`.

  All host-published ports (`otel-collector`'s `4317`/`4318`/`13133`,
  `prometheus`'s `9090`, `tempo`'s `3200`, `loki`'s `3100`, `alloy`'s
  `12345`, `alertmanager`'s `9093`, `grafana`'s `3000`) are bound to
  `127.0.0.1` only, since none of them (aside from Grafana's own admin
  login) sit behind authentication — unlike the four Phase 1
  application services and PostgreSQL, which remain published on all
  interfaces.

  **Not implemented:**
  - Outbound alert notification to a human/external system (email,
    Slack, PagerDuty) — as of Phase 3C, Alertmanager's one receiver IS
    a real webhook, but its destination is this repository's own
    control plane, not an external notification channel; see
    [Alert ingestion](#alert-ingestion-phase-3c) above
  - Grafana-managed alert rules (Prometheus remains the only rule
    evaluator)
  - Automatic remediation of any kind
  - A dedicated Tempo/traces dashboard panel (not part of Phase 2B.3's
    explicit panel list)
  - Any consumption of telemetry by an agent
  - Log/trace correlation: none of the four application services'
    current log output contains a trace or span ID (investigated
    directly, not assumed), so logs and traces are not correlated yet
  - An explicit, confirmed Tempo retention override — Tempo's v3.x
    retention config schema could not be confirmed without further
    guessing against a largely undocumented internal path
    (`backend_scheduler.provider...`); the built-in default (336h/14
    days) is used instead, which is already appropriate for local
    development
  - Per-request access logging in `checkout-service` and
    `inventory-service` — both currently log only at container startup;
    `payment-service` and `notification-service` already log per
    request

  As of Phase 2A.5, a real `POST /checkouts` request produces a
  **complete** distributed trace: checkout-service's SERVER span is the
  common parent of all three downstream CLIENT spans, each of which is
  in turn the parent of its own branch's SERVER span (payment, inventory,
  notification — siblings, not a sequential chain), all sharing one
  Trace ID with correct parent/child Span IDs throughout. As of
  Phase 2B.1, that exact trace has also been independently retrieved
  from Tempo's `GET /api/v2/traces/{traceID}` API and re-verified — same
  Trace ID, same seven spans, same six parent/child relationships — and
  confirmed to remain retrievable after a graceful Tempo restart using
  the same persistent volume (proven for a trace with normal, tens-of-
  seconds-plus processing time before the restart; a trace restarted
  within milliseconds of ingestion was not specifically stress-tested).
  As of Phase 2B.2, real (non-synthetic) log entries from all four
  application services have also been retrieved directly from Loki's
  own query API, and a specific already-ingested entry has been
  confirmed to survive a graceful Loki restart using the same
  persistent volume, with Alloy stopped throughout so it could not have
  resent it. `checkout-service` and `inventory-service` currently only
  log at container startup; none of the four services' current log
  output contains a trace or span ID, so logs and traces are not
  correlated yet. As of Phase 2B.3, three Grafana dashboards are
  auto-provisioned from queries independently verified against this
  same real telemetry (see the Dashboards entry above); Grafana is no
  longer just three connected-but-unused datasources. As of Phase 2B.4,
  Prometheus evaluates four real alert rules against this same
  telemetry and routes firing alerts to Alertmanager — a genuine
  controlled failure (stopping `otel-collector`) empirically proved the
  full `inactive → pending → firing → (Alertmanager) → resolved →
  inactive` lifecycle for `TelemetryPipelineUnavailable`, and that
  telemetry resumes afterward.

There are no other application services, no message brokers, no
orchestration, no cloud infrastructure, and no AI provider integration.

## Planned Architecture

The components below describe the intended direction of the system. They
are **planned/future** — none of them exist in the repository yet, and
they will be introduced incrementally, in later phases, only as each one
becomes necessary.

### Operations console
A **Next.js** web application for human operators: viewing detected
incidents, reviewing agent investigations, and approving or rejecting
proposed remediation actions.

### Control plane
A **FastAPI** service coordinating the overall workflow: receiving
incident signals, orchestrating investigation, storing state, and exposing
APIs consumed by the operations console. As of Phase 3B, a read-only
HTTP API over `reliability.incidents` exists; as of Phase 3C, it also
**receives real incident signals**: a real, running FastAPI service
with a read-only `GET` API plus one authenticated internal write
endpoint that ingests genuine firing Alertmanager alerts. As of
**Phase 3D**, it also **manages the incident lifecycle**: a
centralized, validated state machine; an authenticated
`PATCH /api/v1/incidents/{id}/status` endpoint (optimistic concurrency
via a real atomic compare-and-swap `UPDATE`) for a human/operator; and
real, source-driven automatic resolution from the same Alertmanager
webhook. As of **Phase 3E**, it also **records a durable audit trail**:
every accepted mutation above gets a matching, append-only
`reliability.incident_events` row, in the same transaction as the
mutation, exposed read-only via
`GET /api/v1/incidents/{id}/events` — see
[Control plane](#control-plane-phase-3b),
[Alert ingestion](#alert-ingestion-phase-3c),
[Incident lifecycle](#incident-lifecycle-phase-3d), and
[Incident audit trail](#incident-audit-trail-phase-3e) above,
[docs/api/control-plane.md](../api/control-plane.md),
[docs/architecture/phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md),
[docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md),
and
[docs/architecture/phase-3e-incident-audit.md](phase-3e-incident-audit.md).
**Still planned:** orchestrating investigation, authentication on the
read API, and consumption by the operations console or an agent.

### Durable state
**PostgreSQL** for persisting incidents, investigation history, decisions,
approvals, remediation actions, and the audit trail. PostgreSQL runs
locally via Docker Compose (see Current Implementation above), and, as
of Phase 3A, has its **first real schema**: `reliability.incidents`,
applied through versioned Flyway migrations — see
[Incident domain model](#incident-domain-model-phase-3a) above and
[docs/architecture/incident-domain-model.md](incident-domain-model.md).
As of Phase 3B, a read-only FastAPI control plane
(`services/control-plane`) reads this table over a real HTTP API — see
[Control plane](#control-plane-phase-3b) above. As of Phase 3C, that
same control plane also **writes** to it: a real Alertmanager alert,
delivered through its own authenticated webhook, is atomically
upserted into `reliability.incidents` — see
[Alert ingestion](#alert-ingestion-phase-3c) above. As of **Phase 3D**,
a real incident **lifecycle** governs this table: a centralized,
validated state machine, an authenticated management endpoint with
real optimistic concurrency, and genuine automatic resolution from a
resolved Alertmanager notification (occurrence-identity/stale-replay
safe, backed by a new watermark column added via
`V2__add_occurrence_watermark.sql`) — see
[Incident lifecycle](#incident-lifecycle-phase-3d) above. As of
**Phase 3E**, a new table, `reliability.incident_events`
(`V3__create_incident_audit.sql`), durably records every accepted
mutation to this table, append-only and in the same transaction as
the mutation — see
[Incident audit trail](#incident-audit-trail-phase-3e) above. `V1` is
still unchanged; `V2` and `V3` are both purely additive. As of
**Phase 5**, a read-only AI investigator reads from this table
indirectly, exclusively through control-plane's existing GET API —
never a direct database connection, and never a write of any kind —
see [Read-only AI incident
investigator](#read-only-ai-incident-investigator-phase-5) above.
**Still planned:** any agent *writing* to this table; additional
tables for investigation history, decisions, and approvals (future
migrations, not yet written).

### Coordination / ephemeral state
**Redis** for short-lived state such as in-flight workflow coordination.

### Agent runtime
A **LangGraph**-based runtime for *iterative, tool-using* investigation
and, eventually, proposing remediation steps for human approval. As of
**Phase 5**, a narrower, single-pass, strictly read-only, human-invoked
predecessor already exists — the AI incident investigator
(`services/investigator-service`, see [Read-only AI incident
investigator](#read-only-ai-incident-investigator-phase-5) above):
given one incident, it gathers real evidence once, calls an LLM once,
and returns a report — no loop, no tool-calling, no autonomous
decision to act. This planned runtime is what would add the ability to
gather *more* evidence across multiple reasoning steps, use real tools
to do so, and act on its own initiative (always still gated by human
approval) — none of which Phase 5 implements.

### Infrastructure tool gateway
A **Go** service that exposes a controlled, auditable set of operations for
interacting with infrastructure (e.g., restarting a service, scaling a
deployment). This is the only component permitted to execute approved
remediation actions, and only after explicit human approval for anything
destructive or high-risk.

### Demonstration target system
A set of small **demo commerce microservices** that the platform monitors
and (eventually) remediates against, giving the agent a realistic
distributed system to investigate rather than a synthetic one. Four
services — `checkout-service`, `payment-service`, `inventory-service`,
and `notification-service` — now exist (see Current Implementation
above), each with one simulated business endpoint of its own.
`checkout-service` is now the orchestrator: `POST /checkouts`
synchronously calls the other three, in order, and returns their
combined result — the first real service-to-service workflow in this
repository. Payment, inventory, and notification never call each other
or call back into checkout-service.

### Observability
**CURRENT:** An OpenTelemetry Collector, Prometheus, Grafana (with
three auto-provisioned dashboards as of Phase 2B.3), (as of Phase 2B.1)
Grafana Tempo, (as of Phase 2B.2) Grafana Loki + Grafana Alloy, and (as
of Phase 2B.4) Prometheus Alertmanager all run via Docker Compose (see
Current Implementation above). All four
application services are instrumented,
each its own idiomatic way: `checkout-service` with the OpenTelemetry
Java auto-instrumentation agent (pinned `v2.31.1`); `payment-service`
with OpenTelemetry Python zero-code auto-instrumentation (pinned
`opentelemetry-distro` `0.65b0` / `opentelemetry-exporter-otlp-proto-http`
`1.44.0` family); `inventory-service` with explicit, minimal
OpenTelemetry Go SDK initialization plus `otelhttp` (pinned
`go.opentelemetry.io/otel`/`sdk` `v1.46.0`, `otelhttp` `v0.71.0`
family); and `notification-service` with explicit OpenTelemetry Node
SDK initialization plus `@opentelemetry/instrumentation-http` and
`@fastify/otel` (pinned `0.222.0` / `0.21.0` family) — Go and Node have
no auto-instrumentation equivalent to the Java agent or Python's
zero-code distro. All four export HTTP metrics and trace spans via
OTLP — verified against real Prometheus queries and real Collector
`debug`-exporter output, not assumed.

It is fair to say there is a **complete distributed trace across the
four-service checkout workflow**: a real `POST /checkouts` request
proves ONE trace where checkout-service's SERVER span is the common
parent of three independent, sibling branches — CLIENT → payment
SERVER, CLIENT → inventory SERVER, and CLIENT → notification SERVER
(explicitly **not** a sequential payment → inventory → notification
chain) — each verified via a shared Trace ID and correct parent/child
Span IDs, reconfirmed on a second, independent run. As of Phase 2B.1,
that trace is also **persisted and queryable**: the Collector exports
traces to Tempo 3.0.3 (monolithic mode, local filesystem storage)
alongside its existing `debug` exporter, and the exact same trace has
been independently retrieved from Tempo's `GET /api/v2/traces/{traceID}`
API and re-verified (same Trace ID, same seven spans, same six
parent/child relationships), including after a graceful Tempo restart
using its persistent volume. As of Phase 2B.2, each application
service's existing stdout/stderr output is also centrally collected:
Grafana Alloy discovers each service's container via the Docker API
and ships its logs to Grafana Loki, which persists them with a 7-day
retention policy; real log entries from all four services have been
retrieved directly from Loki's own query API, and a specific
already-ingested entry has been confirmed to survive a graceful Loki
restart using the same persistent volume. `checkout-service` and
`inventory-service` currently only log at container startup — neither
has per-request access logging yet. Logs and traces are **not**
correlated: no service's current log output contains a trace or span
ID. As of Phase 2B.3, Grafana auto-provisions three dashboards
(Application Health, Centralized Logging, Observability Infrastructure)
built entirely from metrics/logs/queries confirmed against real
telemetry — Tempo and Loki are no longer just connected-but-unused
datasources, though no dedicated traces panel exists yet. As of
Phase 2B.4, Prometheus evaluates four real alert rules
(`TelemetryPipelineUnavailable`, `CheckoutServerErrors`,
`CheckoutHighLatency`, `CollectorRefusingTelemetry`) against this same
telemetry and routes firing alerts to Prometheus Alertmanager, which
receives, groups, and tracks their state through its own real API. A
genuine controlled failure (stopping `otel-collector`) empirically
proved `TelemetryPipelineUnavailable`'s full `inactive → pending →
firing → (Alertmanager, active) → resolved → inactive` lifecycle, and
that application telemetry resumes afterward — not merely that the
rule and receiver are configured. At that point, Alertmanager's only
receiver was still a no-op local sink: there was no outbound
notification integration of any kind, no control plane to consume
these incident signals, and none of this telemetry was consumed by
anything. As of **Phase 3C**, that changed: Alertmanager's one receiver
is now a real, authenticated webhook to this repository's own control
plane (not an external notification channel), and the same real
Collector-outage failure was independently re-proven to result in a
persisted, correctly-mapped `reliability.incidents` row — see
[Alert ingestion](#alert-ingestion-phase-3c) above and
[docs/architecture/phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md).
This telemetry is still not consumed by any agent.

**FUTURE (not yet implemented):**
- Outbound alert notification to an external system (email, Slack,
  PagerDuty, or any webhook reaching outside this repository's own
  services)
- Automatic remediation of any kind
- A dedicated Tempo/traces dashboard panel
- Log/trace correlation (emitting trace and span IDs into application
  log output, and querying Loki/Tempo together by that shared ID)
- Per-request access logging in `checkout-service` and
  `inventory-service` (both currently log only at container startup)
- Consumption of this telemetry (metrics, traces, logs, and now
  persisted incidents) by an agent for investigation/root-cause
  analysis

### Event streaming
**Kafka or Redpanda** for propagating incident signals and telemetry
events between components.

### Deployment and infrastructure
- **Kubernetes** as the eventual runtime/orchestration target.
- **Terraform** for provisioning cloud infrastructure.
- **AWS** as the target cloud provider.

## Design principle

Logical separation of these components in this document does not imply
they will all be built, or independently deployed, from the start. See
[ADR-001](../adr/ADR-001-monorepo.md) for the reasoning behind starting
with a monorepo and introducing deployment complexity only when justified.
