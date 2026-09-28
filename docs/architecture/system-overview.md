# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

As of Phase 2A.2, the repository contains foundational scaffolding, a
running infrastructure dependency, four application services with the
**first real service-to-service workflow**, and an
**observability infrastructure stack now instrumented for one of those
four services**. Conceptually, the current demo application shape is:

```
Client
  |
  v
checkout-service :8080  --OTLP (metrics+traces)--> otel-collector
  |                                                    |
  +--> payment-service       :8081  (POST /payments/authorize — simulated, NOT instrumented)
  |
  +--> inventory-service     :8082  (POST /inventory/reservations — simulated, NOT instrumented)
  |
  +--> notification-service  :8083  (POST /notifications — simulated, NOT instrumented)

otel-collector --Prometheus format (metrics)--> prometheus --> grafana
otel-collector --debug exporter (traces)--> collector logs (no trace backend yet)
```

`checkout-service` is instrumented with the OpenTelemetry Java
auto-instrumentation agent and exports real metrics and traces to the
Collector. `payment-service`, `inventory-service`, and
`notification-service` remain **not instrumented** — they send no
telemetry and were not modified.

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

  **Not implemented in this service:**
  - Any real payment processing (no payment provider, e.g. Stripe)
  - Declines, failures, or artificial latency (every authorization
    currently succeeds deterministically)
  - Calling out to any other service itself (it is only ever called)
  - Inventory integration
  - Database access or payment history of any kind
  - Telemetry / observability
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

  **Not implemented in this service:**
  - Real stock levels, stock decrementing/restoration, or out-of-stock
    behavior (every valid reservation currently succeeds deterministically)
  - Persistence of reservations (nothing is stored; identical requests
    produce different `reservation_id`s each time)
  - Calling out to any other service itself (it is only ever called)
  - Database access of any kind
  - Telemetry / observability
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

  **Not implemented in this service:**
  - Any actual notification delivery (email, SMS, push) or external
    provider (no SendGrid/Twilio/SES)
  - Persistence of notifications or a notification history
  - Event consumption, a message queue, or Kafka/Redpanda usage
  - Calling out to any other service itself (it is only ever called)
  - Database access of any kind
  - Telemetry / observability
  - Agent functionality of any kind

- **Observability infrastructure** (`observability/`) — an OpenTelemetry
  Collector, Prometheus, and Grafana, all running via Docker Compose
  (`otel-collector`, `prometheus`, `grafana`). As of Phase 2A.2, this is
  fed by `checkout-service` only; `payment-service`, `inventory-service`,
  and `notification-service` were not modified and send no telemetry.

  **Implemented:**
  - `otel-collector` (`otel/opentelemetry-collector-contrib:0.161.0`):
    an OTLP receiver (gRPC `:4317`, HTTP `:4318`) → `batch` processor,
    fanning out to two pipelines — metrics → Prometheus exporter
    (`:8889`, with `resource_to_telemetry_conversion` enabled so OTel
    resource attributes like `service.name` become Prometheus labels),
    and traces → `debug` exporter (detailed span output to the
    Collector's own container logs; no trace backend yet); a
    `health_check` extension (`:13133`); and separate internal
    ("self") telemetry on `:8888`. The official Contrib image has no
    shell/wget/curl, so it has no Docker-level healthcheck; its
    liveness is proven instead by Prometheus successfully scraping it.
  - `prometheus` (`prom/prometheus:v3.15.0`): scrapes itself, the
    Collector's self-telemetry, and the Collector's telemetry-relay
    endpoint — which now carries real `checkout-service` HTTP
    server/client and JVM metrics — on a persistent named volume
    (`prometheus_data`), with a `wget`-based healthcheck.
  - `grafana` (`grafana/grafana-oss:13.0.2`): Prometheus auto-provisioned
    as its default datasource via
    `observability/grafana/provisioning/datasources/datasource.yml`
    (resolving `http://prometheus:9090` by Compose service name, not
    `localhost`) — no manual click-through setup needed after
    `docker compose up`. Persistent named volume (`grafana_data`).
    Anonymous auth disabled; admin credentials come from `.env`
    (`GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`), local-only
    placeholders, never a real credential.

  All three services' host-published ports (`otel-collector`'s
  `4317`/`4318`/`13133`, `prometheus`'s `9090`, `grafana`'s `3000`) are
  bound to `127.0.0.1` only, since none of them (aside from Grafana's
  own admin login) sit behind authentication — unlike the four Phase 1
  application services and PostgreSQL, which remain published on all
  interfaces.

  **Not implemented:**
  - `payment-service`, `inventory-service`, or `notification-service`
    sending OTLP telemetry or exposing a metrics endpoint (none has an
    OpenTelemetry SDK; none was modified)
  - A real trace backend (Tempo, Jaeger, etc.) — traces are only
    visible via the Collector's `debug` exporter logs this phase
  - Application log export (`OTEL_LOGS_EXPORTER=none` on
    `checkout-service`, and no other service emits logs via OTel either)
  - Distributed trace correlation across the checkout → payment →
    inventory → notification call chain (checkout-service's own SERVER
    span and 3 downstream CLIENT spans are correlated; the downstream
    services themselves do not continue or emit any trace context)
  - Dashboards beyond the minimal datasource-connectivity path, or any
    alerting rules
  - Any consumption of telemetry by an agent

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
**CURRENT:** An OpenTelemetry Collector, Prometheus, and Grafana all run
via Docker Compose (see Current Implementation above). `checkout-service`
is instrumented with the OpenTelemetry Java auto-instrumentation agent
(pinned `v2.31.1`) and exports HTTP server/client metrics, JVM runtime
metrics, and trace spans via OTLP — verified against real Prometheus
queries and real Collector `debug`-exporter output, not assumed.
`payment-service`, `inventory-service`, and `notification-service`
remain uninstrumented. Traces have no backend yet (Collector `debug`
exporter logs only); there is no application log pipeline, and no
dashboards or alerting rules exist.

**FUTURE (not yet implemented):**
- Instrumenting `payment-service`, `inventory-service`, and
  `notification-service` so telemetry, distributed trace correlation
  across the checkout → payment → inventory → notification call chain
  becomes possible end-to-end
- A real trace backend (e.g. Tempo/Jaeger) to replace the temporary
  `debug` exporter
- An application log export pipeline
- Meaningful Grafana dashboards and Prometheus alerting rules
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
