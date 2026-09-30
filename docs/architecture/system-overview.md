# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

As of Phase 2B.1, the repository contains foundational scaffolding, a
running infrastructure dependency, four application services with the
**first real service-to-service workflow**, and an
**observability infrastructure stack instrumented for all four
services, with a complete, verified distributed trace across the whole
checkout workflow — now persisted in and independently re-verified from
a real trace backend, Grafana Tempo**. Conceptually, the current demo
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
  to actually exist; it currently has no schema, migrations, or
  application connecting to it.
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
  Collector, Prometheus, Grafana, and (Phase 2B.1) Grafana Tempo, all
  running via Docker Compose (`otel-collector`, `prometheus`, `grafana`,
  `tempo`). As of Phase 2A.5, this is fed by **all four** application
  services; as of Phase 2B.1, traces are also persisted in and queryable
  from Tempo, not just visible in Collector logs.

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
  - `grafana` (`grafana/grafana-oss:13.0.2`): Prometheus (default) and,
    as of Phase 2B.1, Tempo are both auto-provisioned as datasources via
    `observability/grafana/provisioning/datasources/datasource.yml`
    (resolving `http://prometheus:9090`/`http://tempo:3200` by Compose
    service name, not `localhost`) — no manual click-through setup
    needed after `docker compose up`. Persistent named volume
    (`grafana_data`). Anonymous auth disabled; admin credentials come
    from `.env` (`GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`),
    local-only placeholders, never a real credential.

  All host-published ports (`otel-collector`'s `4317`/`4318`/`13133`,
  `prometheus`'s `9090`, `tempo`'s `3200`, `grafana`'s `3000`) are bound
  to `127.0.0.1` only, since none of them (aside from Grafana's own
  admin login) sit behind authentication — unlike the four Phase 1
  application services and PostgreSQL, which remain published on all
  interfaces.

  **Not implemented:**
  - Application log export (`OTEL_LOGS_EXPORTER=none`/equivalent on all
    four instrumented services; no service emits logs via OTel)
  - Dashboards beyond the minimal datasource-connectivity path, or any
    alerting rules
  - Any consumption of telemetry by an agent
  - An explicit, confirmed Tempo retention override — Tempo's v3.x
    retention config schema could not be confirmed without further
    guessing against a largely undocumented internal path
    (`backend_scheduler.provider...`); the built-in default (336h/14
    days) is used instead, which is already appropriate for local
    development

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
APIs consumed by the operations console.

### Durable state
**PostgreSQL** for persisting incidents, investigation history, decisions,
approvals, remediation actions, and the audit trail. A bare PostgreSQL
instance now runs locally via Docker Compose (see Current Implementation
above); the schema and any application usage of it are still planned.

### Coordination / ephemeral state
**Redis** for short-lived state such as in-flight workflow coordination.

### Agent runtime
A **LangGraph**-based runtime responsible for investigation: gathering
telemetry, forming hypotheses about root cause, and proposing remediation
steps for human approval.

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
**CURRENT:** An OpenTelemetry Collector, Prometheus, Grafana, and (as of
Phase 2B.1) Grafana Tempo all run via Docker Compose (see Current
Implementation above). All four application services are instrumented,
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
using its persistent volume. There is still no application log
pipeline, and no dashboards or alerting rules exist (Tempo is a
provisioned Grafana datasource, but nothing visualizes it yet); none of
this telemetry is yet consumed by an agent.

**FUTURE (not yet implemented):**
- An application log export pipeline
- Meaningful Grafana dashboards (including trace-based ones, now that
  Tempo is available) and Prometheus alerting rules
- Consumption of this telemetry by an agent for incident detection

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
