# Autonomous Production Reliability Platform

## What this is

An Agentic SRE / Infrastructure Engineering platform. The long-term goal is a
system that can monitor a realistic distributed application, detect
operational incidents, gather real telemetry, investigate failures using
structured tools, form hypotheses, recommend remediation, require human
approval for anything dangerous, execute approved remediation, verify
recovery, maintain an audit trail, and support regression evaluation over
time.

This is not a tutorial project, a chatbot, a toy RAG demo, or a simple
LangGraph example. It is being built incrementally toward a
production-style system.

## Status

**Actively under early development.** The project is currently in
**Phase 2A.5 — notification-service OpenTelemetry Instrumentation +
Complete Distributed Checkout Trace**. An OpenTelemetry Collector,
Prometheus, and Grafana run via Docker Compose (Phase 2A.1). All four
application services are now instrumented, each its own idiomatic way:
`checkout-service` with the OpenTelemetry Java auto-instrumentation
agent (Phase 2A.2); `payment-service` with OpenTelemetry Python
zero-code auto-instrumentation (Phase 2A.3); `inventory-service` with
manual OpenTelemetry Go SDK initialization plus `otelhttp` (Phase 2A.4);
and `notification-service` with manual OpenTelemetry Node SDK
initialization plus `@opentelemetry/instrumentation-http` and
`@fastify/otel` (Phase 2A.5). A real `POST /checkouts` request now
proves a **complete distributed trace across the whole four-service
checkout workflow**: checkout-service's own SERVER span is the common
parent of three independent, correctly-parented downstream branches —
CLIENT → payment SERVER, CLIENT → inventory SERVER, and CLIENT →
notification SERVER — all siblings, **not** a sequential
payment → inventory → notification chain. Same Trace ID and correct
parent/child Span IDs on all three branches, verified against real
Collector output, not assumed, and independently reconfirmed on a
second, fully torn-down-and-restarted run. `checkout-service` still
synchronously orchestrates all three downstream services via
`POST /checkouts` (Phase 1B.4), with no change to any business logic;
none of the four application services connect to PostgreSQL. There is
still no real trace backend (Collector `debug` exporter logs only), no
application log pipeline, no dashboards/alerts, and no AI functionality.

## Problem this project will eventually solve

Production incidents today typically require a human on-call engineer to:
notice an alert, gather logs/metrics/traces from multiple systems, form a
hypothesis about root cause, decide on a remediation, and execute it —
often under time pressure. This project aims to build an agentic system
that can perform the investigative and (with human approval) remediation
steps of that workflow against a realistic target application, with a full
audit trail of what it observed, what it concluded, and what it did.

## Planned high-level architecture

The following components are **planned** and do not exist yet:

- A Next.js operations console for human oversight and approvals
- A FastAPI control plane coordinating investigation and remediation workflows
- PostgreSQL for durable state (incidents, decisions, audit trail)
- Redis for ephemeral/coordination state
- A LangGraph-based agent runtime for investigation and hypothesis formation
- A Go infrastructure tool gateway for safely executing remediation actions
- Demo commerce microservices as a realistic monitored target
- Application-level observability: a real trace backend, application
  log pipeline, dashboards, and alerts (the OTel Collector / Prometheus /
  Grafana infrastructure exists, all four application services now
  export metrics and traces to it, and one real `POST /checkouts`
  request produces a complete, verified distributed trace across
  checkout-service and all three of its downstream branches — payment,
  inventory, notification, as siblings, not a sequential chain — see
  [Observability Infrastructure](#observability-infrastructure) below —
  but traces are only visible via the Collector's `debug` exporter logs,
  there is no centralized trace backend or application log pipeline,
  and no dashboards or alerts exist yet)
- Kafka or Redpanda for event streaming
- Kubernetes as the deployment target, provisioned via Terraform on AWS

See [docs/architecture/system-overview.md](docs/architecture/system-overview.md)
for the current-vs-planned breakdown.

## Development philosophy

- **Incremental delivery.** The system is built in small, well-defined
  phases rather than all at once.
- **Every stage must be runnable.** Each phase leaves the repository in a
  working state, not a partially-wired one.
- **Functionality must be verified before being marked complete.** Claims
  of "done" are backed by an actual command that was run and checked.
- **No fake production claims.** Documentation distinguishes what is
  implemented from what is planned. Nothing is described as working until
  it has been verified.
- **Complexity is introduced only when justified.** Tools, frameworks, and
  infrastructure are added when a concrete requirement needs them, not
  speculatively.

## Current implementation status

Repository-level scaffolding exists (baseline documentation, an
environment-check script, and standard configuration files), a local
PostgreSQL database run via Docker Compose, and four application
services: `checkout-service` (Java / Spring Boot), `payment-service`
(Python / FastAPI), `inventory-service` (Go / standard library), and
`notification-service` (Node.js / TypeScript / Fastify). `payment-service`,
`inventory-service`, and `notification-service` each expose one
simulated business endpoint of their own (`POST /payments/authorize`,
`POST /inventory/reservations`, `POST /notifications` respectively —
none connected to a real payment provider, stock system, or message
provider) and never call each other. `checkout-service` has
`POST /checkouts`, which synchronously calls all three of them in
sequence — the first real service-to-service workflow in this
repository — and returns a combined result. None of the four
application services connect to PostgreSQL yet.

An observability stack — an OpenTelemetry Collector, Prometheus, and
Grafana — also runs via Docker Compose (see
[Observability Infrastructure](#observability-infrastructure) below).
`checkout-service` is instrumented with the OpenTelemetry Java
auto-instrumentation agent (pinned `v2.31.1`) and exports HTTP server
metrics for `POST /checkouts`, HTTP client metrics for its three
downstream calls, JVM runtime metrics, and trace spans (SERVER +
3 CLIENT spans sharing one trace) via OTLP to the Collector.
`payment-service` is instrumented (Phase 2A.3) using OpenTelemetry
Python zero-code auto-instrumentation, `inventory-service` (Phase 2A.4)
using manual OpenTelemetry Go SDK initialization plus `otelhttp`, and
`notification-service` (Phase 2A.5) using manual OpenTelemetry Node SDK
initialization plus `@opentelemetry/instrumentation-http` and
`@fastify/otel`; all four export HTTP server metrics and a SERVER span
for their respective endpoints. A real `POST /checkouts` request now
proves a **complete distributed trace across all four services**:
checkout-service's own SERVER span is the common parent of three
independently-verified downstream branches — CLIENT → payment SERVER,
CLIENT → inventory SERVER, and CLIENT → notification SERVER — all
siblings, not a sequential chain. Same Trace ID throughout, and each
downstream SERVER span's Parent Span ID equals its own checkout CLIENT
span's Span ID — verified against real Collector output, not assumed,
and independently reconfirmed on a second, fully torn-down-and-restarted
run. Traces currently have no backend (the Collector's `debug` exporter
prints them to its own logs; a real trace backend is a future phase).
No AI integration has been added yet.

## Local PostgreSQL

PostgreSQL is the first running infrastructure component. It is defined
in `docker-compose.yml` and configured entirely through environment
variables — no credentials are committed to the repository.

**1. Create your local `.env`:**

```bash
cp .env.example .env
```

Edit `.env` if you want different local values. `.env` is gitignored and
must never be committed.

**2. Start PostgreSQL:**

```bash
docker compose up -d
```

**3. Check status (wait for `healthy`):**

```bash
docker compose ps
```

**4. Stop PostgreSQL (keeps data in the named volume):**

```bash
docker compose down
```

Use `docker compose down -v` only if you intentionally want to delete the
local database volume.

## Developer Commands

The commands above are also available as `make` targets, for convenience:

```bash
make help            # list available targets
make check           # verify local prerequisites (scripts/check-env.sh)
make compose-config  # validate docker-compose.yml
make db-up           # start PostgreSQL
make db-status       # check PostgreSQL status (wait for "healthy")
make db-logs         # show recent PostgreSQL logs
make db-down         # stop PostgreSQL — preserves the data volume
```

`make db-down` never deletes the PostgreSQL named volume.

## Checkout Service

`services/checkout-service` is the first application service: a Java 21 /
Spring Boot 3 project built with Maven. It is now the **orchestrator**:
`POST /checkouts` synchronously calls `payment-service`,
`inventory-service`, and `notification-service`, in that exact order,
and returns a combined result. This is the first real
service-to-service workflow in this repository. It still does not
connect to PostgreSQL.

Endpoints:

- `GET /health` — a small typed JSON response: `{"status": "UP", "service": "checkout-service"}`
- `GET /actuator/health` — Spring Boot Actuator's own health endpoint (only `health` is exposed)
- `POST /checkouts` — accepts `{"sku": str, "quantity": int, "amount_cents": int, "currency": str, "recipient": str}`
  and returns HTTP 200 with a generated `checkout_id` (`chk_<uuid>`) and
  the combined downstream results:

  ```json
  {
    "checkout_id": "chk_550e8400-e29b-41d4-a716-446655440000",
    "status": "COMPLETED",
    "payment": {"payment_id": "<uuid>", "status": "AUTHORIZED"},
    "inventory": {"reservation_id": "<uuid>", "status": "RESERVED"},
    "notification": {"notification_id": "<uuid>", "status": "ACCEPTED"}
  }
  ```

  **Orchestration sequence:** Payment → Inventory → Notification. If a
  step fails, later steps are not called — there is intentionally **no
  rollback/compensation** for steps that already succeeded (e.g. a
  reservation failure does not reverse an already-authorized payment).
  Any downstream failure is normalized to a safe HTTP 502 from
  `checkout-service`:
  `{"error": "downstream_failure", "service": "<payment-service|inventory-service|notification-service>", "message": "Downstream service request failed"}`
  — no stack traces, internal URLs, or downstream response bodies are
  ever exposed to the caller. This covers non-2xx responses, connection
  failures, an empty response, an unexpected business status, and a
  malformed/inconsistent successful (HTTP 200) response — specifically a
  missing or blank required result ID (`payment_id`/`reservation_id`/
  `notification_id`) or a returned `checkout_id` that doesn't match the
  one `checkout-service` generated and sent.

Downstream base URLs are configurable via `CHECKOUT_PAYMENT_BASE_URL`,
`CHECKOUT_INVENTORY_BASE_URL`, and `CHECKOUT_NOTIFICATION_BASE_URL`
(defaulting to `localhost` for running outside Compose; Docker Compose
supplies the container-network values).

**Build and test locally** (requires a local Java 21 toolchain — if your
machine only has an older Java version, this will fail to compile; use
the Docker path below instead):

```bash
cd services/checkout-service
./mvnw test
```

**Build and test via Docker** (does not require local Java 21 — the
image build compiles and runs the tests on Java 21 inside the build):

```bash
make checkout-build
```

**Run it through Docker Compose**, alongside the other three services and PostgreSQL:

```bash
make db-up
curl http://localhost:8080/health
curl http://localhost:8080/actuator/health
curl -X POST http://localhost:8080/checkouts \
  -H 'Content-Type: application/json' \
  -d '{"sku":"sku_keyboard_001","quantity":2,"amount_cents":2599,"currency":"USD","recipient":"customer@example.com"}'
make checkout-logs
make db-down
```

**Not implemented anywhere in this workflow yet:** business/checkout
persistence, PostgreSQL usage by any application service, distributed
transactions, retries, backoff, circuit breakers, idempotency keys,
queues/eventing (Kafka/Redpanda/Redis), real payment/inventory/notification
processing, observability/distributed tracing, and any AI/agent
functionality. These are deliberately deferred to later phases.

## Payment Service

`services/payment-service` is the second application service: a Python
3.13 / FastAPI project using a standard `src`-layout package, installed
via `pyproject.toml` (no Poetry/Pipenv). It now has one real business
endpoint, `POST /payments/authorize` — a **simulated** payment
authorization (no real payment provider, no persistence). It still does
**not** connect to PostgreSQL and does **not** communicate with
`checkout-service` or any other service.

Endpoints:

- `GET /health` — a small typed JSON response: `{"status": "UP", "service": "payment-service"}`
- `POST /payments/authorize` — accepts `{"checkout_id": str, "amount_cents": int, "currency": str}`
  (money as integer cents; `currency` must be exactly three uppercase
  letters) and returns HTTP 200 with a generated `payment_id`, the
  echoed `checkout_id`/`amount_cents`/`currency`, and `status: "AUTHORIZED"`.
  Invalid requests return FastAPI/Pydantic's standard HTTP 422 validation
  error. Every authorization in this phase deterministically succeeds —
  there are no declines, no real payment processing, and no database
  persistence yet.

**Build and test locally** (requires a local Python 3.13 toolchain — if
your machine has a different Python version, install may still work but
is not the authoritative check; use the Docker path below instead):

```bash
cd services/payment-service
pip install -e ".[dev]"
pytest
```

**Test on Python 3.13 via Docker** (reproducible regardless of your local
Python version):

```bash
make payment-test
```

**Run it through Docker Compose**, alongside PostgreSQL and checkout-service:

```bash
make db-up
curl http://localhost:8081/health
make payment-logs
make db-down
```

### payment-service instrumentation (Phase 2A.3)

`payment-service` is instrumented using **OpenTelemetry Python
zero-code auto-instrumentation** — no manual SDK initialization or
source changes under `services/payment-service/src/payment_service/`.
Pinned packages, added as an `observability` optional-dependency group
in `pyproject.toml` (kept separate from the service's core runtime
dependencies): `opentelemetry-distro==0.65b0`,
`opentelemetry-instrumentation-fastapi==0.65b0`,
`opentelemetry-exporter-otlp-proto-http==1.44.0` (the `1.44.0` / `0.65b0`
OpenTelemetry Python release family). Resolution against Python 3.13 and
FastAPI 0.141.1 and `pip check` were both verified clean before use.

The Dockerfile installs the `observability` extra but its `CMD` is
still plain Uvicorn (`uvicorn payment_service.main:app ...`) — the image
still runs telemetry-free when launched standalone. Docker Compose is
what opts into instrumentation, by overriding `payment-service`'s
`command:` to `opentelemetry-instrument uvicorn payment_service.main:app
--host 0.0.0.0 --port 8081`, mirroring checkout-service's
environment-activated (not image-baked) instrumentation. Compose also
sets the same `OTEL_*` variables as checkout-service (service name,
resource attributes, OTLP endpoint/protocol, `tracecontext,baggage`
propagation, `OTEL_LOGS_EXPORTER=none`, short export intervals), plus
`OTEL_SEMCONV_STABILITY_OPT_IN=http` to align HTTP semantic conventions
with checkout-service's Java agent.

Auto-instrumentation captures a SERVER span and HTTP server metrics
(`http_server_request_duration_seconds_*`, `http_server_active_requests`,
`http_server_response_body_size_bytes_*`) for `POST /payments/authorize`
— no custom metrics or manual spans. A real `POST /checkouts` request
proves genuine distributed trace continuation into this service: the
checkout-service CLIENT span for the payment call and the
payment-service SERVER span for `POST /payments/authorize` share one
Trace ID, and the payment span's Parent Span ID equals the checkout
CLIENT span's own Span ID — confirmed against real Collector debug
output (not assumed), and re-confirmed independently on a second,
fully fresh run with different (still-matching) span/trace IDs.

## Inventory Service

`services/inventory-service` is the third application service: a Go 1.27
project using only the standard library (`net/http`, `encoding/json`,
`crypto/rand`, `net/http/httptest`, etc. — no web framework, no external
dependencies). It now has one real business endpoint,
`POST /inventory/reservations` — a **simulated** reservation. It does
**not** track real stock levels, does **not** persist reservations, does
**not** connect to PostgreSQL, and does **not** communicate with
`checkout-service` or `payment-service`.

Endpoints:

- `GET /health` — a small typed JSON response: `{"status": "UP", "service": "inventory-service"}`
  (only `GET` is accepted; other methods return `405`)
- `POST /inventory/reservations` — accepts `{"checkout_id": str, "sku": str, "quantity": int}`
  (strict JSON: unknown fields and trailing data are rejected) and
  returns HTTP 200 with a generated `reservation_id` (UUID v4, via
  `crypto/rand` — no external UUID dependency), the echoed
  `checkout_id`/`sku`/`quantity`, and `status: "RESERVED"`. Invalid
  requests return HTTP 400 with `{"error": "invalid_request", "message": "..."}`.
  Only `POST` is accepted on this path; other methods return `405` with
  an `Allow: POST` header. Every valid reservation in this phase
  deterministically succeeds — there is no real stock, so there is no
  out-of-stock behavior yet.

The HTTP server uses explicit `ReadHeaderTimeout`/`ReadTimeout`/
`WriteTimeout`/`IdleTimeout` and shuts down gracefully on `SIGTERM`/`SIGINT`.

**Test and build locally** (requires a local Go 1.27 toolchain — if Go
isn't installed, use the Docker path below instead):

```bash
cd services/inventory-service
gofmt -l .
go vet ./...
go test ./...
```

**Test on Go 1.27 via Docker** (reproducible regardless of whether Go is
installed locally):

```bash
make inventory-test
```

**Run it through Docker Compose**, alongside PostgreSQL, checkout-service,
and payment-service:

```bash
make db-up
curl http://localhost:8082/health
make inventory-logs
make db-down
```

The container image is built in two stages: a `golang:1.27` builder
(which also runs `gofmt`/`go vet`/`go test`) producing a static binary,
and a `gcr.io/distroless/static-debian12:nonroot` runtime with no shell
and no package manager. Since that runtime has no `curl`/`wget` for a
Compose healthcheck, the same binary exposes a built-in `healthcheck`
subcommand (a plain HTTP GET against its own `/health`) that Compose
calls directly.

### inventory-service instrumentation (Phase 2A.4)

Unlike checkout-service (Java auto-instrumentation agent) and
payment-service (Python zero-code auto-instrumentation), Go has no
equivalent auto-instrumentation mechanism, so `inventory-service` uses
**explicit, minimal OpenTelemetry Go SDK initialization** in a new
`internal/telemetry` package, plus
`go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` wrapping
the whole `http.ServeMux` at the server boundary in `internal/server`
(not inside the business handlers in `internal/api`). Pinned versions:
`go.opentelemetry.io/otel`/`sdk` `v1.46.0`, `otlptracehttp`/`otlpmetrichttp`
`v1.46.0`, `otelhttp` `v0.71.0` — resolved cleanly against Go 1.27 via
`go mod tidy`, with `go.sum` committed. Zero changes to
`internal/api/reservations.go` or `internal/reservation/` — no manual
spans, no custom metrics.

`internal/telemetry.Setup` builds a `resource.New(ctx, resource.WithFromEnv(), ...)`
(reading `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES` from the
environment — never hard-coded), an OTLP/HTTP trace exporter feeding a
`BatchSpanProcessor`, an OTLP/HTTP metric exporter feeding a
`PeriodicReader`, and installs a global composite
`tracecontext`+`baggage` propagator — critical for extracting
checkout-service's incoming `traceparent` header and continuing that
trace. Neither the batch processor's schedule delay nor the periodic
reader's export interval are overridden in code, so both honor
`OTEL_BSP_SCHEDULE_DELAY`/`OTEL_METRIC_EXPORT_INTERVAL` via the Go SDK's
own env-aware defaults, confirmed by their real 5s/1s timing in
practice.

**Telemetry is only ever initialized in the normal server path**
(`cmd/inventory-service/main.go`'s `run()`), never for the `healthcheck`
subcommand, which still `os.Exit()`s before `run()` is even called —
confirmed empirically: running `/inventory-service healthcheck`
standalone (no server, no Collector reachable) fails in ~0.24s with a
plain "connection refused" on `/health`, with no OTLP dial attempt or
delay. A telemetry setup failure fails server startup clearly (`log.Fatal`)
rather than running with partially configured telemetry. Graceful
shutdown flushes and closes the trace/metric providers after the HTTP
server itself has shut down.

Auto-instrumentation captures a SERVER span and HTTP server metrics
(`http_server_request_duration_seconds_*`,
`http_server_request_body_size_bytes_*`,
`http_server_response_body_size_bytes_*`) for `POST /inventory/reservations`
— confirmed empirically that `otelhttp` v0.71.0 re-derives the span
name/route from the standard library's own matched `ServeMux` pattern
(`*http.Request.Pattern`, a Go 1.22+ field populated by `ServeMux`
itself once the wrapped mux has dispatched) rather than needing a
separate per-route tagging call. A real `POST /checkouts` request
proves genuine distributed trace continuation into this service: the
checkout-service CLIENT span for the inventory call and the
inventory-service SERVER span for `POST /inventory/reservations` share
one Trace ID, and the inventory span's Parent Span ID equals the
checkout CLIENT span's own Span ID — confirmed against real Collector
debug output, and independently re-confirmed on a second, fully
torn-down-and-restarted run with a different (still-matching) trace ID.

## Notification Service

`services/notification-service` is the fourth application service: a
Node.js 24 / TypeScript (strict) / Fastify project using npm. It now has
one real business endpoint, `POST /notifications` — a **simulated**
notification trigger (no real email/SMS/push provider, no persistence,
no queue). It does **not** send email, SMS, or push notifications, does
**not** consume events, does **not** use Kafka/Redpanda, does **not**
connect to PostgreSQL, and does **not** communicate with any other
service.

Endpoints:

- `GET /health` — a small typed JSON response: `{"status": "UP", "service": "notification-service"}`
  (only `GET` is handled; `POST /health` returns `404`, not the valid response)
- `POST /notifications` — accepts `{"checkout_id": str, "kind": "ORDER_CONFIRMATION", "recipient": str}`
  (validated via Fastify's built-in JSON-schema/Ajv support: `checkout_id`
  1–100 chars, `kind` must be exactly `"ORDER_CONFIRMATION"`, `recipient`
  1–254 chars, opaque — no email-format validation) and returns HTTP 200
  with a generated `notification_id` (via `crypto.randomUUID()`, no
  external UUID package), the echoed `checkout_id`/`kind`/`recipient`,
  and `status: "ACCEPTED"`. `ACCEPTED` means only that this demo service
  accepted the simulated trigger — no message is actually delivered.
  Invalid requests return Fastify's normal HTTP 400 validation error.
  Only `POST` is registered on this path; other methods get Fastify's
  normal `404`.

`src/app.ts` builds the Fastify instance without binding a port, so
tests exercise it via Fastify's `inject()` rather than a live network
listener. `src/server.ts` starts the listener and shuts it down cleanly
on `SIGTERM`/`SIGINT`.

**Test and build locally** (requires a local Node 24 toolchain — if your
machine has a different Node version, use the Docker path below instead):

```bash
cd services/notification-service
npm ci
npm run typecheck
npm test
npm run build
```

**Test on Node 24 via Docker** (reproducible regardless of your local
Node version):

```bash
make notification-test
```

**Run it through Docker Compose**, alongside PostgreSQL, checkout-service,
payment-service, and inventory-service:

```bash
make db-up
curl http://localhost:8083/health
make notification-logs
make db-down
```

The container image is built in two stages: a `node:24` builder (which
also runs `npm ci`, typecheck, and `node --test` via `tsx`) producing
compiled JavaScript in `dist/`, and a `node:24-slim` runtime with only
production dependencies, running as the official image's built-in
`node` user. Since installing `curl` solely for a healthcheck was to be
avoided, the Compose healthcheck instead uses Node's built-in `fetch`
(with a bounded 3-second timeout) via `node -e`.

### notification-service instrumentation (Phase 2A.5)

Node has no auto-instrumentation agent equivalent to the Java agent or
Python's zero-code distro, so `notification-service` uses **explicit
OpenTelemetry Node SDK initialization** (`NodeSDK`) in a new
`src/telemetry.ts`, combining `@opentelemetry/instrumentation-http`
(generic HTTP client/server instrumentation, required for
`@fastify/otel` to propagate trace context) with `@fastify/otel`'s
`FastifyOtelInstrumentation` (the Fastify-maintained package — the
older, now-deprecated `@opentelemetry/instrumentation-fastify` is not
used). Pinned versions: `@opentelemetry/sdk-node`/`exporter-trace-otlp-http`/
`exporter-metrics-otlp-http`/`instrumentation-http` `0.222.0`,
`@fastify/otel` `0.21.0`, plus `@opentelemetry/sdk-metrics` `2.11.0`
(a directly-imported peer, pinned at the version the family already
resolved to). All installed as regular `dependencies` (not
`devDependencies`), confirmed present in the image after
`npm prune --omit=dev`. Zero changes to business logic under
`src/routes/`, `src/services/`, or `src/types/`.

**Startup ordering is the critical piece.** `@fastify/otel`'s
`registerOnInitialization: true` option patches the `fastify` module
itself when the SDK starts, so any Fastify instance constructed
afterward is auto-instrumented with no `app.register()` call needed —
but only if that patch happens *before* `fastify` is ever imported. A
plain static `import` at the top of `server.ts` would not guarantee
that, since ESM hoists and evaluates all of a module's static imports
(including transitive ones through `app.ts`) before its own top-level
code runs. The fix is a new **dedicated bootstrap entrypoint**,
`src/bootstrap.ts` (compiled to `dist/bootstrap.js`, now the
Dockerfile's `CMD` and `package.json`'s `start` script — updated
minimally from `dist/server.js`, per the ESM-safe-entrypoint case):
it calls `startTelemetry()` synchronously first, then
`await import("./server.js")` — a genuine dynamic import, which defers
loading (and therefore evaluating) `server.js`/`app.js`/`fastify`
until after the SDK has already started. This was verified empirically,
not assumed: the real Collector output shows the expected
`POST /notifications` SERVER span from the
`@opentelemetry/instrumentation-http` scope, confirmed on two
independent, fully-clean `make verify-observability` runs.

Existing tests (`test/*.test.ts`) call `buildApp()` directly and never
import `telemetry.ts` or `bootstrap.ts`, so they remain fully isolated
from OpenTelemetry — no real OTLP exporters are initialized, and tests
pass with no Collector running (confirmed: same 10/10 pass count before
and after this phase). `app.ts` required no changes at all — auto-patch
registration via `registerOnInitialization: true` was sufficient.

Resource attributes (`service.name`, `service.version`,
`deployment.environment.name`) are never hard-coded — `NodeSDK`'s
default resource detectors (`envDetector`, `processDetector`,
`hostDetector`) already read `OTEL_SERVICE_NAME`/
`OTEL_RESOURCE_ATTRIBUTES` from the environment, confirmed by inspecting
`@opentelemetry/sdk-node`'s own source. `OTLPTraceExporter`/
`OTLPMetricExporter` (from the `-http` packages, i.e. HTTP+protobuf
transport, not the `-proto`/`-grpc` variants) both read
`OTEL_EXPORTER_OTLP_ENDPOINT` automatically — confirmed in
`@opentelemetry/otlp-exporter-base`'s source — so no URL is
hard-coded. Passing `traceExporter` (rather than a pre-built
`BatchSpanProcessor`) to `NodeSDK` makes the SDK construct an
env-aware `BatchSpanProcessor` internally, honoring
`OTEL_BSP_SCHEDULE_DELAY` — confirmed in source, matching the other
three services' behavior. `PeriodicExportingMetricReader`, however,
does **not** read `OTEL_METRIC_EXPORT_INTERVAL` on its own when
constructed directly (confirmed empirically by reading the installed
package) — unlike the trace side, this is read explicitly in
`telemetry.ts` and passed as `exportIntervalMillis`. Graceful shutdown
(SIGTERM/SIGINT and startup-failure paths alike) closes Fastify first,
then flushes/closes telemetry with its own independent, bounded
(10s) timeout — never calling `process.exit()` before that shutdown
has had a chance to complete.

## Observability Infrastructure

`observability/` contains configuration for a local OpenTelemetry
Collector, Prometheus, and Grafana, all running via Docker Compose
(Phase 2A.1). As of Phase 2A.5, **all four application services** feed
this stack real telemetry.

```
checkout-service      --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
payment-service       --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
inventory-service     --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
notification-service  --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
(all four)            --OTLP (traces)--> otel-collector --debug exporter--> collector logs

One real checkout trace — a COMPLETE distributed trace across all four services:
                    +-> checkout payment CLIENT      -> payment SERVER
  checkout SERVER --|-> checkout inventory CLIENT    -> inventory SERVER
                    +-> checkout notification CLIENT -> notification SERVER
  (siblings off the one checkout SERVER span — NOT a sequential
   payment -> inventory -> notification chain)
```

- **`otel-collector`** (`otel/opentelemetry-collector-contrib`) — an OTLP
  receiver (gRPC `:4317`, HTTP `:4318`) → `batch` processor, fanning out
  to two pipelines: metrics → Prometheus exporter (`:8889`, with
  `resource_to_telemetry_conversion` enabled so OTel resource attributes
  like `service.name` become Prometheus labels), and traces → `debug`
  exporter (prints detailed span data to the Collector's own container
  logs — there is intentionally no trace backend yet). Its own internal
  metrics are exposed separately on `:8888`. A `health_check` extension
  is exposed on `:13133`, but it does **not** back a Docker Compose
  healthcheck: the official Contrib image is a single static binary with
  no shell, `wget`, or `curl`, so no `healthcheck:` block can be defined
  for it without modifying the image. This is an intentional exception —
  `docker compose ps` shows it as `running` with no health status, and
  its liveness is instead verified functionally: a direct request to
  `:13133/` succeeds, and more meaningfully, Prometheus reports its
  scrape target as `up`.
- **`prometheus`** — scrapes itself, the Collector's self-telemetry
  (`:8888`), and the Collector's application-telemetry-relay endpoint
  (`:8889`), which now carries real metrics from all four application
  services, on a persistent named volume.
- **`grafana`** — Prometheus is auto-provisioned as its default
  datasource (`observability/grafana/provisioning/datasources/datasource.yml`,
  resolving `http://prometheus:9090` by Compose service name) so no
  manual click-through setup is needed after `docker compose up`. No
  dashboards are provisioned yet beyond what's needed to prove Grafana
  can query Prometheus. Anonymous auth is disabled; the admin password
  is a local-only placeholder from `.env.example`, never a real credential.

All three host ports above (`4317`/`4318`/`13133`, `9090`, `3000`) are
published bound to `127.0.0.1` only — none of them sit behind
authentication (Grafana is the exception, via its own admin login), so
they are not reachable from other machines on the network even in local
development. This differs from the four Phase 1 application services and
PostgreSQL, whose ports remain published on all interfaces.

### checkout-service instrumentation (Phase 2A.2)

`checkout-service` is instrumented using the **OpenTelemetry Java
auto-instrumentation agent**, pinned to `v2.31.1` (not the Spring Boot
starter, and not `latest`). The agent JAR is fetched in the runtime
stage of `services/checkout-service/Dockerfile` via
`ADD --chmod=644 --checksum=sha256:...` (a pinned checksum, no
curl/wget needed in the image) to `/opt/opentelemetry-javaagent.jar`,
world-readable so the image's non-root `app` user can load it. It is
**not** referenced by the Dockerfile's `ENTRYPOINT`, so the image still
runs with no telemetry when launched standalone outside this Compose
stack; Docker Compose attaches it only for `checkout-service` via
`JAVA_TOOL_OPTIONS=-javaagent:/opt/opentelemetry-javaagent.jar`, along
with `OTEL_*` environment variables configuring OTLP export over
`http/protobuf` to `http://otel-collector:4318`, `tracecontext,baggage`
propagation, `OTEL_LOGS_EXPORTER=none` (log export is explicitly
deferred), and short export intervals (5s metrics, 1s span batch delay)
for fast local feedback. `payment-service`, `inventory-service`, and
`notification-service` are all instrumented too now, each its own
idiomatic way (see their own sections above).

Auto-instrumentation captures, with no manual/custom spans or metrics
added: a SERVER span and HTTP server metrics
(`http_server_request_duration_seconds_*`) for `POST /checkouts`; CLIENT
spans and HTTP client metrics (`http_client_request_duration_seconds_*`)
for each of the three downstream calls made via Spring `RestClient`
(to `payment-service`, `inventory-service`, `notification-service`);
and JVM/runtime metrics (`jvm_*`). All four spans generated by a single
`POST /checkouts` request share one trace ID, with each downstream
CLIENT span's parent ID matching the SERVER span's own ID — verified
against real Collector debug-exporter output, not assumed.

**Run it through Docker Compose**, alongside the four application services and PostgreSQL:

```bash
make db-up
curl http://127.0.0.1:9090/-/ready               # Prometheus
curl http://127.0.0.1:9090/api/v1/targets        # scrape targets, including otel-collector
curl http://127.0.0.1:3000/api/health            # Grafana
make db-down
```

**Bundled verification:** `make verify-observability` (or
`scripts/verify-observability.sh`) runs the full Phase 2A.1-2A.5
verification path in one deterministic script — starts Compose, waits
for every service's health (with the `otel-collector` exception above),
checks Prometheus targets and the Grafana datasource, re-runs the
`POST /checkouts` regression check, then verifies all four application
services' HTTP server metrics (plus checkout's HTTP client metrics)
actually reached Prometheus (bounded retry, since export intervals and
Prometheus's scrape cycle are both async), that trace evidence for the
checkout SERVER span and all three downstream CLIENT spans appears in
the Collector's own logs, and that ONE checkout trace is a **complete**
distributed trace across **all three** downstream branches — payment,
inventory, and notification, siblings, not parent/child of each other
— using a small deterministic parser
(`scripts/parse-checkout-trace.py`, generalized across Phases 2A.3-2A.5
from an initial payment-only parser) that proves each downstream CLIENT
span and its corresponding SERVER span share a Trace ID with the
correct parent/child Span IDs on every branch, rather than just
grepping for service names appearing somewhere in the logs — then
always tears the environment down (without deleting volumes) and
confirms the three named volumes still exist. Run twice from a fully
clean state in this phase specifically (not just once), since Node/ESM
module-evaluation ordering is more delicate than the other three
services' instrumentation mechanisms — both runs produced a
correctly-correlated trace, each with an independent, different real
Trace ID.

**Not implemented yet:** a real trace backend (traces are only visible
via the Collector's `debug` exporter logs); an application log
pipeline; dashboards beyond the minimal datasource-connectivity check;
alerting rules; and any consumption of telemetry by an agent. Those are
deliberately deferred to later phases.

## Continuous Integration

A GitHub Actions workflow (`.github/workflows/ci.yml`) has been added. It
runs on pushes and pull requests targeting `main`, and can also be
triggered manually (`workflow_dispatch`). Using `contents: read`
permissions only, it validates: shell script syntax, that the Makefile is
usable, that `checkout-service` builds and its tests pass (Java 21 via
`actions/setup-java`), that `payment-service`'s dependencies install and
its tests pass (Python 3.13 via `actions/setup-python`), that
`inventory-service` is `gofmt`-clean and passes `go vet`/`go test`/build
(Go 1.27 via `actions/setup-go`), that `notification-service` installs
(`npm ci`), typechecks, tests, and builds (Node 24 via `actions/setup-node`),
that Docker Compose config resolves, that PostgreSQL and all four
application services start and reach a healthy state (bounded retry
loops, not assumed), a basic SQL smoke test, HTTP smoke tests against
all four application services' health endpoints, an end-to-end smoke
test that calls `POST /checkouts` and verifies the real orchestrated
response over the actual Compose network, that Prometheus and Grafana
reach a healthy state, that Prometheus reports all three scrape targets
— `prometheus` (self), `otel-collector` (self-telemetry), and
`otel-collector-app-metrics` (the application-telemetry relay) — as
`up` (bounded retry loop, since Prometheus needs a scrape cycle after
startup), that Grafana's health
API and provisioned Prometheus datasource are reachable, that all four
application services' relevant HTTP metrics (checkout's server+client,
payment's, inventory's, and — new in this phase — notification's server
metrics) actually reach Prometheus, and that trace evidence (checkout
SERVER span, all three downstream CLIENT spans) plus a deterministic
proof that ONE checkout trace is a **complete** distributed trace across
**all three** downstream branches — payment, inventory, and — new in
this phase — notification (via the same generalized
`scripts/parse-checkout-trace.py` the local verifier uses) appear in
the Collector's logs, all via bounded retry loops (the OTel Java
agent's, Python SDK's, Go SDK's, and Node SDK's export intervals,
Prometheus's scrape cycle, and the Collector's batch export are all
asynchronous) — then always tears the environment down (without
deleting volumes).

The repository has a GitHub remote
(`abheesh-03/autonomous-reliability-platform`). The workflow version
covering repository baseline checks, all four application services
(Java + Python + Go + Node setup, build/test, Compose, PostgreSQL, and
all four services' health/smoke tests), and the `POST /checkouts`
end-to-end orchestration smoke test has been verified running
successfully on a GitHub-hosted runner (CI run `36350946497`, for commit
`1ef34e6`). The workflow has since been updated further, first with
Phase 2A.1's observability steps (Prometheus/Grafana health waits,
scrape-target verification, and datasource check), then with Phase
2A.2's `checkout-service` telemetry checks (Prometheus metrics,
Collector trace evidence), then with Phase 2A.3's `payment-service`
telemetry and distributed-trace-continuation checks (extending, not
duplicating, the existing checkout metrics/trace steps) — the
Phase 2A.3 version of the workflow was committed (`1118fda`) and has
run successfully on GitHub Actions. Phase 2A.4 further extended the
existing metrics and trace steps with `inventory-service`'s checks and
was committed (`d6c3292`); that version also ran successfully on
GitHub Actions (run #15), with the working tree left clean afterward.
Phase 2A.5 extends the same two steps once more with
`notification-service`'s checks (see above); this has been locally
validated end-to-end by reproducing the workflow's steps against the
real Compose network (via `make verify-observability`, run twice from a
clean state, which covers equivalent ground), but the Phase 2A.5
version of the workflow has **not yet run on GitHub Actions** — that
will only be true once it runs there after a push.

The previous run also noted an informational warning that `ubuntu-latest`
will migrate to Ubuntu 26 in the future; per guidance, the runner has
been left as `ubuntu-latest` since there is no concrete compatibility
problem today.

## VERIFIED COMPLETED FEATURES

- Git repository initialized on branch `main`.
- Baseline repository documentation (`README.md`, architecture overview,
  ADR process and ADR-001) created.
- `.gitignore` and `.editorconfig` established for the eventual polyglot
  stack (Python, Go, Java, TypeScript/JavaScript).
- `.env.example` created with placeholder-only values (no real secrets).
- `scripts/check-env.sh` created, made executable, and run successfully;
  it correctly detects locally available tooling and distinguishes
  Phase 0.1 requirements from later-phase requirements.
- `docker-compose.yml` created, defining a single `postgres` service
  (PostgreSQL 18, pinned) configured entirely via environment variables.
- `docker compose config` validated successfully.
- PostgreSQL starts via `docker compose up -d` and reaches Docker-reported
  `healthy` status using a `pg_isready`-based healthcheck.
- Verified via `psql` inside the container: `SELECT version()`,
  `SELECT current_database()`, and `SELECT current_user` all return the
  expected, environment-configured values.
- Verified data persistence: a table created and populated in the running
  database survived `docker compose restart postgres` and was still
  present with the same content afterward.
- Verified `.env` is created locally from `.env.example`, is correctly
  ignored by Git (`git check-ignore`), and never appears in `git status`
  or any commit.
- Verified `docker compose down` (without `-v`) stops and removes the
  container while preserving the named data volume.
- `Makefile` created with `help`, `check`, `compose-config`, `db-up`,
  `db-down`, `db-status`, `db-logs`, and `db-restart` targets, each a
  thin wrapper around the already-verified underlying commands.
- Verified `make help`, `make check`, and `make compose-config` all run
  and exit successfully.
- Verified `make db-up` starts PostgreSQL and `make db-status` confirms
  Docker-reported `healthy` status (health was polled, not assumed).
- Verified `make db-logs` returns real PostgreSQL log output.
- Verified `make db-down` stops the container while the named data
  volume remains present afterward.
- `.github/workflows/ci.yml` created (triggers: push/PR to `main`,
  `workflow_dispatch`; `contents: read` permissions only).
- Locally reproduced every CI step end-to-end on this machine: shell
  syntax check, `make help`, `.env` creation from `.env.example`,
  `docker compose config`, `make db-up`, the workflow's exact bounded
  health-check retry loop (reached `healthy`), the exact SQL smoke test
  (`SELECT 1`, `current_database()`, `current_user`), log output, and
  cleanup via `docker compose down` (volume preserved).
- Verified: the CI workflow (repository baseline checks + Java 21 setup +
  `checkout-service` build/test + Docker Compose + PostgreSQL health/SQL
  smoke test + `checkout-service` health/HTTP smoke test) executed
  successfully on a real GitHub-hosted runner (CI run `36268092550`)
  after the repository was pushed to `main` on GitHub; this coverage was
  re-verified together with `payment-service` in CI run `36269437529`,
  and again together with `inventory-service` in CI run `36272398003`.
- `services/checkout-service` created: a Java 21 / Spring Boot 3.5.16
  Maven project exposing `GET /health` and `GET /actuator/health` only,
  with no checkout, payment, inventory, or database logic.
- Automated tests (`CheckoutServiceApplicationTests`, `HealthControllerTest`)
  pass. Local Java is 17, so `./mvnw test` fails to compile locally
  (`release version 21 not supported`) — this is a known local-toolchain
  limitation, not a code defect; tests were verified running for real on
  Java 21 inside the Docker build (`Tests run: 2, Failures: 0, Errors: 0`).
- `services/checkout-service/Dockerfile` (multi-stage, Java 21 builder →
  Java 21 JRE runtime, non-root user) builds successfully via
  `docker compose build` / `make checkout-build`.
- `docker-compose.yml` updated with a `checkout-service` entry (build,
  port 8080, `curl`-based Actuator healthcheck, no PostgreSQL
  dependency/credentials, default network only).
- Verified `docker compose up -d` starts both `postgres` and
  `checkout-service`, and both independently reach Docker-reported
  `healthy` status (bounded polling, not assumed).
- Verified `curl http://localhost:8080/health` returns HTTP 200 with
  `{"status":"UP","service":"checkout-service"}`.
- Verified `curl http://localhost:8080/actuator/health` returns HTTP 200
  with `{"status":"UP"}`, and that only the `health` Actuator endpoint is
  exposed (`/actuator/env` returns 404).
- Verified the `checkout-service` container process runs as a non-root
  user (`uid=999(app)`).
- Verified `docker compose down` (without `-v`) stops both containers
  while the PostgreSQL named volume remains present afterward.
- `Makefile` extended with `checkout-build`, `checkout-test`, and
  `checkout-logs`; existing `db-*` targets continue to work unchanged.
- `.github/workflows/ci.yml` updated to build/test `checkout-service` on
  a real Java 21 toolchain (`actions/setup-java`) and to add a bounded
  health-check + HTTP smoke test for it — **verified running successfully
  on GitHub Actions** (CI run `36268092550`).
- `services/payment-service` created: a Python 3.13 / FastAPI project
  (`src`-layout, `pyproject.toml`, no Poetry/Pipenv) exposing `GET /health`
  only, with no payment, checkout, or database logic.
- Automated test (`test_health_returns_200_with_expected_body`) passes.
  Host Python is 3.14 (not the 3.13 target); it happened to pass natively
  in a scratch venv too, but the authoritative check was running the same
  test inside a real `python:3.13-slim` container (`1 passed`) — this is
  also what `make payment-test` and CI's `actions/setup-python` do.
- `services/payment-service/Dockerfile` (single-stage `python:3.13-slim`,
  non-root user; no separate builder stage since all dependencies have
  prebuilt wheels) builds successfully via `docker compose build` /
  `make payment-build`.
- `docker-compose.yml` updated with a `payment-service` entry (build,
  port 8081, Python-`urllib`-based healthcheck, no PostgreSQL or
  checkout-service dependency/credentials, default network only).
- Verified `docker compose up -d` starts all three of `postgres`,
  `checkout-service`, and `payment-service`, and all three independently
  reach Docker-reported `healthy` status (bounded polling, not assumed).
- Verified `curl http://localhost:8080/health` still returns HTTP 200
  with `{"status":"UP","service":"checkout-service"}` (unaffected by
  adding payment-service).
- Verified `curl http://localhost:8081/health` returns HTTP 200 with
  `{"status":"UP","service":"payment-service"}`.
- Verified the `payment-service` container process runs as a non-root
  user (`uid=999(app)`), and that `docker compose logs payment-service`
  returns real Uvicorn log output.
- Verified `docker compose down` (without `-v`) stops all three
  containers while the PostgreSQL named volume remains present afterward.
- `Makefile` extended with `payment-build`, `payment-test` (runs inside a
  `python:3.13-slim` container for reproducibility regardless of host
  Python version), and `payment-logs`; existing `db-*` and `checkout-*`
  targets continue to work unchanged.
- `.github/workflows/ci.yml` updated to install `payment-service`
  dependencies and run its tests on a real Python 3.13 toolchain
  (`actions/setup-python`), and to add a bounded health-check + HTTP
  smoke test for it. `actions/checkout` and `actions/setup-java` were
  bumped to their current major versions (`v5`) to resolve GitHub's
  deprecation warnings from the previous verified run, with equivalent
  behavior — **verified running successfully on GitHub Actions**
  (CI run `36269437529`).
- `services/inventory-service` created: a Go 1.27 project using only the
  standard library (`net/http`, `encoding/json`, `net/http/httptest`, no
  web framework, no external dependencies) exposing `GET /health` only,
  with no inventory, checkout, payment, or database logic.
- Go was not installed locally (confirmed before starting); the official
  `golang:1.27` Docker image was used as the authoritative local
  build/test environment throughout, matching what CI's
  `actions/setup-go` does.
- `gofmt -l .` produced no output (fully formatted), `go vet ./...`
  passed with no findings, and `go test ./...` passed all 3 tests
  (health-handler body/content-type, GET /health accepted, POST /health
  rejected) — verified both standalone (via `docker run golang:1.27`)
  and again inside the Docker image build itself.
- `services/inventory-service/Dockerfile` (multi-stage: `golang:1.27`
  builder running `gofmt`/`go vet`/`go test` before compiling a static
  binary → `gcr.io/distroless/static-debian12:nonroot` runtime, no
  shell, no package manager, no Go toolchain) builds successfully via
  `docker compose build` / `make inventory-build`.
- Verified the built binary's own `healthcheck` subcommand (used by the
  Compose healthcheck in place of curl/wget, which the distroless
  runtime doesn't have) exits 0 against a running instance.
- `docker-compose.yml` updated with an `inventory-service` entry (build,
  port 8082, exec-form healthcheck via the binary itself, no PostgreSQL
  or other service dependency/credentials, default network only).
- Verified `docker compose up -d` starts all four of `postgres`,
  `checkout-service`, `payment-service`, and `inventory-service`, and all
  four independently reach Docker-reported `healthy` status (bounded
  polling, not assumed).
- Verified `curl http://localhost:8080/health` and
  `curl http://localhost:8081/health` still return their expected bodies
  (unaffected by adding inventory-service).
- Verified `curl http://localhost:8082/health` returns HTTP 200 with
  `{"status":"UP","service":"inventory-service"}`.
- Verified `curl -X POST http://localhost:8082/health` returns HTTP 405
  Method Not Allowed, not the valid health response.
- Verified the `inventory-service` container process runs as
  `nonroot:nonroot`, and that `docker compose logs inventory-service`
  returns real log output.
- Verified `docker compose down` (without `-v`) stops all four
  containers while the PostgreSQL named volume remains present afterward.
- `Makefile` extended with `inventory-build`, `inventory-test` (runs
  `gofmt`/`go vet`/`go test` inside a `golang:1.27` container for
  reproducibility regardless of whether Go is installed locally), and
  `inventory-logs`; existing `db-*`, `checkout-*`, and `payment-*`
  targets continue to work unchanged.
- `.github/workflows/ci.yml` updated to set up Go 1.27 (`actions/setup-go`),
  validate `inventory-service` formatting/vet/tests/build, and add a
  bounded health-check + HTTP smoke test for it. `actions/setup-python`
  was bumped from `v5` to `v6` (confirmed to move from `node20` to
  `node24`) to resolve the Node.js 20 deprecation warning noted from the
  previous run, with equivalent behavior — **verified running
  successfully on GitHub Actions** (CI run `36272398003`).
- `services/notification-service` created: a Node.js 24 / TypeScript
  (strict) / Fastify project using npm, exposing `GET /health` only,
  with no notification, checkout, payment, inventory, or database logic.
- Host Node is v20.20.2 (not the 24 target); `package-lock.json` was
  generated, and `npm ci`/typecheck/`node --test`/build were all run,
  authoritatively inside a real `node:24` container (`node -v` → 24.x
  confirmed) — this is also what `make notification-test` and CI's
  `actions/setup-node` do.
- `tsc --noEmit` (typecheck) passed clean; `node --test` (via `tsx`)
  passed both tests (GET /health body/content-type, POST /health
  returns non-200); `tsc -p tsconfig.json` (build) produced compiled
  `dist/app.js`, `dist/server.js`, `dist/routes/health.js` — verified
  both standalone (via `docker run node:24`) and again inside the Docker
  image build itself.
- `services/notification-service/Dockerfile` (multi-stage: `node:24`
  builder running `npm ci`/typecheck/test/build then `npm prune
  --omit=dev` → `node:24-slim` runtime with only production
  dependencies, running as the official image's built-in `node` user)
  builds successfully via `docker compose build` / `make
  notification-build`.
- Verified the container's built-in `node` user is used (`uid=1000`),
  and that the Compose healthcheck (Node's `fetch` with a bounded
  3-second timeout, no curl/wget installed) exits 0 against a running
  instance.
- `docker-compose.yml` updated with a `notification-service` entry
  (build, port 8083, exec-form Node-`fetch`-based healthcheck, no
  PostgreSQL or other service dependency/credentials, default network
  only).
- Verified `docker compose up -d` starts all five of `postgres`,
  `checkout-service`, `payment-service`, `inventory-service`, and
  `notification-service`, and all five independently reach
  Docker-reported `healthy` status (bounded polling, not assumed).
- Verified `curl http://localhost:8080/health`,
  `curl http://localhost:8081/health`, and
  `curl http://localhost:8082/health` still return their expected bodies
  (unaffected by adding notification-service).
- Verified `curl http://localhost:8083/health` returns HTTP 200 with
  `{"status":"UP","service":"notification-service"}`.
- Verified `curl -X POST http://localhost:8083/health` returns HTTP 404
  Not Found, not the valid health response.
- Verified the `notification-service` container process runs as `node`
  (`uid=1000`), and that `docker compose logs notification-service`
  returns real structured (pino) log output.
- Verified `docker compose down` (without `-v`) stops all five
  containers while the PostgreSQL named volume remains present afterward.
- `Makefile` extended with `notification-build`, `notification-test`
  (runs `npm ci`/typecheck/test/build inside a `node:24` container for
  reproducibility regardless of the developer's local Node version), and
  `notification-logs`; existing `db-*`, `checkout-*`, `payment-*`, and
  `inventory-*` targets continue to work unchanged.
- `.github/workflows/ci.yml` updated to set up Node 24 (`actions/setup-node`,
  confirmed to run on `node24` itself), install/typecheck/test/build
  `notification-service`, and add a bounded health-check + HTTP smoke
  test for it. `actions/setup-go` was given an explicit
  `cache-dependency-path: services/inventory-service/go.mod` to resolve
  the "Dependencies file is not found" cache warning noted from the
  previous run (confirmed the input is supported by `setup-go@v7`), with
  equivalent behavior otherwise. `ubuntu-latest` was left unchanged per
  instructions (informational Ubuntu 26 migration notice only, no
  concrete compatibility problem). Locally reproduced the full updated
  CI path end-to-end (all five services healthy, all smoke tests, logs,
  cleanup) — **verified running successfully on GitHub Actions**
  (CI run `36350946497`, commit `1ef34e6`).
- `services/checkout-service` gained `POST /checkouts`: a `CheckoutController`
  → `CheckoutOrchestrationService` → three small `RestClient`-based
  clients (`PaymentClient`, `InventoryClient`, `NotificationClient`),
  with typed request/response DTOs throughout (no `Map<String, Object>`)
  and a `@RestControllerAdvice` translating downstream failures to a
  safe HTTP 502. `spring-boot-starter-validation` was added for Bean
  Validation (`@NotBlank`/`@Positive`/`@Pattern`) on the request DTO.
  Downstream base URLs are configurable via `CHECKOUT_PAYMENT_BASE_URL` /
  `CHECKOUT_INVENTORY_BASE_URL` / `CHECKOUT_NOTIFICATION_BASE_URL`
  (`localhost` defaults; Compose supplies container-network values).
- Verified `./mvnw test` (via `eclipse-temurin:21-jdk` Docker, since
  local Java is 17) — **36/36 tests pass**: 14 controller contract tests
  (valid request, each validation rule, 502 mapping with no leaked
  detail), 14 orchestration-service unit tests (Mockito — call order,
  shared `checkout_id`, payment/inventory/notification failure short-
  circuiting, unexpected-status handling for all three services, and
  response-contract validation for each service: missing/blank required
  downstream IDs and mismatched returned `checkout_id`), 6 client
  serialization tests (`MockRestServiceServer` — snake_case
  request/response mapping and 5xx → `DownstreamServiceException` for
  each of the three clients), plus the existing 2 health tests. The full
  Spring context also loads successfully with the new configuration.
- Verified `docker compose build checkout-service` and the full
  five-service Compose environment: all five containers reached
  Docker-reported `healthy`.
- Verified `POST /checkouts` end-to-end through the real Compose network
  (`checkout-service` → `payment-service` → `inventory-service` →
  `notification-service`): HTTP 200, `checkout_id` prefixed `chk_`,
  `status: "COMPLETED"`, and real `payment_id`/`reservation_id`/
  `notification_id` values with `AUTHORIZED`/`RESERVED`/`ACCEPTED`.
- Verified invalid requests (lowercase currency, zero quantity) return
  HTTP 400, and that `GET /health`, `POST /health` (405, `Allow: GET`),
  `/actuator/health` (200), and `/actuator/env` (404) on checkout-service
  are all unchanged.
- Verified a real downstream-failure scenario by stopping the running
  `payment-service` container (no committed configuration changed):
  `POST /checkouts` returned exactly
  `{"error":"downstream_failure","service":"payment-service","message":"Downstream service request failed"}`
  with HTTP 502 — no stack trace, URL, or exception class name leaked.
  After restarting `payment-service` and it becoming healthy again, a
  repeat request succeeded normally.
- Inspected logs across all five services after this testing: the only
  `WARN`/exception entries present were the ones directly caused by
  these deliberate test requests (validation failures, the induced
  downstream outage, a manual `POST /health` check) — no unexpected
  errors.
- Verified `docker compose down` (without `-v`) stops all five
  containers while the PostgreSQL named volume remains present afterward.
- `docker-compose.yml` updated with `checkout-service`'s three
  `CHECKOUT_*_BASE_URL` environment variables (container-network values);
  no `depends_on` was added (checkout-service's own healthcheck doesn't
  check downstream, and no additional startup coupling was introduced).
  `.env.example` updated: the stale "no variables are consumed" comment
  was removed, and the three `CHECKOUT_*_BASE_URL` variables are
  documented as optional local overrides.
- `.github/workflows/ci.yml` extended with an end-to-end
  "checkout orchestration smoke test" step (`curl` + `jq`) run after all
  four services report healthy; the exact `jq` assertion was verified
  against a real captured orchestration response before being added —
  **verified running successfully on GitHub Actions** (CI run
  `36350946497`, commit `1ef34e6`).
- `observability/` added: an OpenTelemetry Collector
  (`otel/opentelemetry-collector-contrib:0.161.0`), Prometheus
  (`prom/prometheus:v3.15.0`), and Grafana
  (`grafana/grafana-oss:13.0.2`) — versions confirmed to exist and be
  pullable before use, all pinned (no `latest`). Infrastructure only —
  no application service was modified, and none sends telemetry yet.
- Verified `docker compose up -d` starts all 8 containers (the existing
  5 plus `otel-collector`/`prometheus`/`grafana`); `postgres`,
  `checkout-service`, `payment-service`, `inventory-service`,
  `notification-service`, `prometheus`, and `grafana` all independently
  reach Docker-reported `healthy` (bounded polling, not assumed).
  `otel-collector`'s official image has no shell/wget/curl (a single
  static binary), so no Docker-level healthcheck is possible for it —
  confirmed empirically (`sh`/`wget`/`curl` all absent, and the binary
  has no self-check subcommand); its liveness was instead verified via
  its exposed `health_check` port (`13133`, direct `curl` from the host
  returned `{"status":"Server available",...}`) and, more meaningfully,
  via Prometheus successfully scraping it.
- Verified `curl http://localhost:9090/-/ready` (200, "Prometheus
  Server is Ready") and `curl http://localhost:9090/api/v1/targets`:
  all three configured scrape targets (`prometheus` self,
  `otel-collector` self-telemetry on `:8888`, and the currently-empty
  `otel-collector-app-metrics` relay on `:8889`) report `"health":"up"`.
- Verified `curl http://localhost:3000/api/health` returns
  `{"database":"ok",...}`, and that Grafana's `/api/datasources` (via
  basic auth) shows the auto-provisioned `Prometheus` datasource with
  `url: "http://prometheus:9090"` (the Compose service name, not
  `localhost`) — no manual click-through setup was needed.
- Verified `POST /checkouts` still returns the full `COMPLETED`
  orchestration response, unchanged, with the observability stack
  running alongside it.
- Inspected logs across all 8 containers: `otel-collector`, `prometheus`,
  and `grafana` all started cleanly with no errors; the four application
  services showed no unexpected errors either.
- Verified `docker compose down` (without `-v`) stops all 8 containers
  while all three named volumes (`postgres_data`, `prometheus_data`,
  `grafana_data`) remain present afterward.
- `.github/workflows/ci.yml` extended with health waits for Prometheus
  and Grafana, a bounded-retry check that Prometheus reports all three
  scrape targets — `prometheus` (self), `otel-collector` (self-telemetry),
  and `otel-collector-app-metrics` (the application-telemetry relay) —
  as `up` (necessary since Prometheus needs a scrape cycle after
  startup), and a Grafana health/datasource check —
  every exact `jq` expression added was tested against real captured
  responses before being added. Locally reproduced the full updated CI
  path end-to-end — **not yet verified running on GitHub Actions in
  this updated form.**

### Phase 2A.2 — checkout-service OpenTelemetry instrumentation

- `services/checkout-service/Dockerfile` updated: the pinned
  OpenTelemetry Java agent (`v2.31.1`, official GitHub release asset)
  is fetched in the runtime stage via
  `ADD --chmod=644 --checksum=sha256:bbf83c15... /opt/opentelemetry-javaagent.jar`
  — no curl/wget added to the image, checksum verified against a
  locally downloaded copy of the same release asset before use. Caught
  and fixed a real bug during verification: the first version (without
  `--chmod`) left the JAR `-rw-------` owned by `root`, unreadable by
  the image's non-root `app` user — confirmed via
  `docker run --entrypoint sh ... sha256sum` failing with "Permission
  denied" before the fix, and succeeding after it. The agent is present
  in the image but not referenced by `ENTRYPOINT`, so the image still
  runs with no telemetry standalone.
- `docker-compose.yml`'s `checkout-service` service (only) updated with
  `JAVA_TOOL_OPTIONS=-javaagent:/opt/opentelemetry-javaagent.jar` and
  `OTEL_*` variables (service name, resource attributes, OTLP endpoint
  `http://otel-collector:4318` over `http/protobuf`, `tracecontext,baggage`
  propagation, `OTEL_LOGS_EXPORTER=none`, 5s metric export interval, 1s
  span batch delay). No other service was touched; no new host ports
  were added.
- `observability/otel-collector/config.yaml` updated: `prometheus`
  exporter gained `resource_to_telemetry_conversion: enabled: true`
  (confirmed this is what makes `service.name` etc. appear as
  Prometheus labels); a new `debug` exporter (`verbosity: detailed`)
  and `traces` pipeline (`otlp` → `batch` → `debug`) were added,
  separate from the existing `metrics` pipeline. Collector self-telemetry
  on `:8888` untouched.
- Verified checkout-service's existing test suite: `36` tests, `0`
  failures, via `./mvnw -B test` on Java 21 (Docker), confirming zero
  business-logic regression from the Dockerfile/Compose changes.
- Started the full 8-container Compose stack, confirmed via container
  logs that the agent attaches cleanly (`Picked up JAVA_TOOL_OPTIONS`,
  `opentelemetry-javaagent - version: 2.31.1`, no exporter connection
  errors), and that `POST /checkouts` still returns the unchanged
  `COMPLETED` orchestration response.
- Inspected real Collector debug-exporter output for a live
  `POST /checkouts` request (not assumed): `checkout-service` produced
  one SERVER span (`Name: POST /checkouts`, `Kind: Server`,
  `http.route: /checkouts`) and three CLIENT spans (`Kind: Client`, one
  each with `url.full: http://payment-service:8081/payments/authorize`,
  `.../inventory-service:8082/inventory/reservations`,
  `.../notification-service:8083/notifications`) — all four spans
  shared one Trace ID, and each CLIENT span's Parent ID matched the
  SERVER span's own ID (not previously guaranteed — Spring's newer
  `RestClient` was not known in advance to be covered by this agent
  version, and turned out to be). This confirms the Java agent injects
  W3C trace context on the outgoing `RestClient` calls; it does **not**
  prove end-to-end propagation across the whole
  checkout → payment → inventory → notification chain, since
  `payment-service`, `inventory-service`, and `notification-service`
  are uninstrumented and cannot be observed continuing (or even
  receiving) that trace context until a later phase.
- Queried Prometheus directly (not assumed) and confirmed the real
  metric/label names actually emitted: series labeled
  `service_name="checkout-service"` exist for
  `http_server_request_duration_seconds_{count,sum,bucket}` (with
  `http_route="/checkouts"`) and
  `http_client_request_duration_seconds_{count,sum,bucket}` (with
  distinct `server_address` values `payment-service`,
  `inventory-service`, `notification-service`), plus `jvm_*` runtime
  metrics — no custom business metrics were added. Resource labels
  observed include `service_name`, `service_version="0.1.0"`,
  `deployment_environment_name="local"`, `telemetry_distro_version="2.31.1"`.
- `scripts/verify-observability.sh` extended (not replaced) with two
  new sections after the existing `POST /checkouts` regression check:
  a bounded-retry Prometheus query for checkout-service HTTP
  server+client metrics, and a bounded-retry check of Collector logs
  for the SERVER span and all three downstream CLIENT spans' evidence
  strings. Hit and fixed a real bug while adding the trace-evidence
  check: `echo "$logs" | grep -qF ...` under `set -o pipefail` produced
  spurious `Broken pipe` failures, because `grep -q` exits as soon as
  it finds a match, sending `echo` a `SIGPIPE` that `pipefail` then
  reports as a failed pipeline — fixed by using `grep -qF '...' <<<"$logs"`
  (a here-string, no pipe) instead. The full `make verify-observability`
  run passed end-to-end after the fix, including both new sections and
  the pre-existing persistence check (all three named volumes still
  present after teardown).
- `.github/workflows/ci.yml` extended with two new steps after the
  existing Grafana datasource check: a bounded-retry Prometheus query
  for checkout-service metrics, and a bounded-retry Collector-log check
  for trace evidence — both using the same safe `if cmd1 && cmd2; then`
  control-flow pattern (rather than a bare assignment) so an
  expected-to-fail early attempt cannot abort the step under GitHub
  Actions' default `bash -e`. Locally reproduced equivalent verification
  via `make verify-observability` — **not yet verified running on
  GitHub Actions in this updated form.**
- **Limitation, honestly reported, not worked around:** Phase 2A.2 has
  no real trace backend — trace evidence is only visible via the
  Collector's `debug` exporter logs, which is acceptable for this phase
  per the task's own scope but means traces are not queryable or
  persisted anywhere. `payment-service`, `inventory-service`, and
  `notification-service` remain fully uninstrumented; propagation past
  checkout-service's own CLIENT spans (i.e. whether those downstream
  services would continue a received trace context) is unverified and
  out of scope until they are instrumented in a later phase.

### Phase 2A.3 — payment-service OpenTelemetry instrumentation + distributed trace continuation

- `services/payment-service/pyproject.toml` updated: added an
  `observability` optional-dependency group (kept separate from core
  runtime deps, dev group preserved unchanged) pinning
  `opentelemetry-distro==0.65b0`,
  `opentelemetry-instrumentation-fastapi==0.65b0`,
  `opentelemetry-exporter-otlp-proto-http==1.44.0`. Verified this
  resolves cleanly against `fastapi==0.141.1`/`uvicorn==0.54.0`/
  `pydantic==2.13.5` on Python 3.13 (via `python:3.13-slim`) and that
  `pip check` reports no broken requirements, both with the extra alone
  and combined with `dev`.
- `services/payment-service/Dockerfile` updated: `pip install` now
  installs the `.[observability]` extra, but `CMD` is unchanged — still
  plain `uvicorn payment_service.main:app ...` — confirmed via
  `docker inspect --format '{{.Config.Cmd}}'` on the built image, so the
  image still runs telemetry-free standalone.
- `docker-compose.yml`'s `payment-service` service (only) updated with
  a `command:` override (`opentelemetry-instrument uvicorn
  payment_service.main:app --host 0.0.0.0 --port 8081`, list/exec
  syntax) and the same `OTEL_*` variables as checkout-service, plus
  `OTEL_SEMCONV_STABILITY_OPT_IN=http`. Top-of-file and
  checkout-service-block comments claiming checkout-service was "the
  only instrumented service" or that the stack was "not yet fed by any
  application service" were corrected. No other service touched; no new
  host ports added.
- `observability/otel-collector/config.yaml`: comments only, updated to
  reflect that payment-service now also sends telemetry through the
  same existing metrics/traces pipelines — no new pipeline or exporter
  was added, per scope.
- Verified payment-service's existing test suite is unaffected: `9`
  tests, `0` failures, via `pytest -v` on Python 3.13 (Docker), both
  with only the `dev` extra and with `dev`+`observability` combined —
  zero business-logic regression, zero source changes under
  `services/payment_service/src/payment_service/`.
- Started the full 8-container Compose stack and confirmed via
  container logs that payment-service starts cleanly through
  `opentelemetry-instrument` with no exporter connection errors, and
  that `POST /checkouts` still returns the unchanged `COMPLETED`
  response.
- **Distributed trace continuation — the main goal of this phase —
  proven against real Collector debug-exporter output for a live
  `POST /checkouts` request, not assumed:** the checkout-service CLIENT
  span (`url.full: http://payment-service:8081/payments/authorize`) and
  the payment-service SERVER span (`Name: POST /payments/authorize`,
  `service.name: payment-service`) share one Trace ID
  (`07ad268aa13c7ddea325b7f8669315f7` in the captured run), and the
  payment SERVER span's Parent ID (`8d1be32b28caf0ef`) exactly equals
  the checkout CLIENT span's own Span ID — real parent/child distributed
  tracing across a process/service boundary, via the Java agent's and
  the Python SDK's shared W3C `tracecontext` propagation. Independently
  re-confirmed on a second, fully torn-down-and-restarted run, which
  produced a different (still internally consistent) Trace ID
  (`0944f75c2f38f757299422ddebf839a2`), ruling out a one-off coincidence.
  This proves only the checkout → payment segment; inventory and
  notification remain uninstrumented and are not part of this proof.
- Queried Prometheus directly (not assumed) for payment-service's real
  metric/label names: `http_server_request_duration_seconds_{count,sum,bucket}`,
  `http_server_active_requests`, `http_server_response_body_size_bytes_{count,sum,bucket}`,
  with `service_name="payment-service"`, `http_route="/payments/authorize"`,
  `service_version="0.1.0"`, `deployment_environment_name="local"`. No
  `telemetry_distro_name`/`telemetry_distro_version` labels (that's
  Java-agent-specific); the Python zero-code distro instead produces
  `telemetry_auto_version="0.65b0"`, `telemetry_sdk_language="python"`,
  `telemetry_sdk_name="opentelemetry"`, `telemetry_sdk_version="1.44.0"`,
  `otel_scope_version="0.65b0"`. No custom payment metrics were added.
- `scripts/verify-observability.sh` extended (not replaced): section G
  gained a bounded-retry Prometheus query for payment-service's HTTP
  server metric; section H gained a bounded-retry call to a new small,
  deterministic parser, `scripts/parse-payment-trace.py` (~90 lines),
  which groups Collector debug-exporter output into spans (associating
  each span with its enclosing ResourceSpans block's `service.name`)
  and proves the exact checkout-CLIENT/payment-SERVER Trace
  ID/Parent-ID/Span-ID relationship — not just that both service names
  appear somewhere in the logs. Existing checkout-only checks were left
  unmodified. Hit and fixed a real parsing bug while building this:
  `ResourceSpans #N` lines (unlike `Span #N` lines) carry a
  timestamp+level prefix from the Collector's own logger, so a naive
  `line.startswith('ResourceSpans #')` never matched and every span was
  silently mis-attributed to whichever resource happened to be parsed
  first; fixed by matching on line suffix (`re.search(r'ResourceSpans
  #\d+$', line)`) instead. The full `make verify-observability` run
  passed end-to-end twice in a row (two independent fresh trace IDs),
  including both new checks and all pre-existing Phase 2A.1/2A.2 checks
  and the persistence check.
- `.github/workflows/ci.yml` extended, not duplicated: the existing
  checkout-metrics step gained a payment-service metrics query; the
  existing checkout-trace step gained a call to the same
  `scripts/parse-payment-trace.py` used locally. Kept the same safe
  `if cmd1 && cmd2; then` control-flow pattern throughout so an
  expected-to-fail early retry attempt cannot abort the step under
  GitHub Actions' default `bash -e`. Locally reproduced equivalent
  verification via `make verify-observability` — **not yet verified
  running on GitHub Actions in this updated form.**
- **Limitation, honestly reported, not worked around:** this proves
  distributed tracing for the checkout → payment segment only.
  `inventory-service` and `notification-service` remain fully
  uninstrumented — the full four-service chain is not yet a verified
  distributed trace, and there is still no real trace backend (Collector
  `debug` exporter logs only), no application log pipeline, and no
  dashboards/alerts.

### Phase 2A.4 — inventory-service OpenTelemetry instrumentation + second distributed trace branch

- `services/inventory-service/go.mod`/`go.sum` updated: added the
  pinned OpenTelemetry Go SDK/instrumentation family —
  `go.opentelemetry.io/otel`/`sdk` `v1.46.0`,
  `otlptracehttp`/`otlpmetrichttp` `v1.46.0`, `otelhttp` `v0.71.0` —
  resolved cleanly against Go 1.27 via `go mod tidy` (verified twice:
  once to generate `go.sum`, once more afterward to confirm the tree is
  already minimal/stable, i.e. a no-op). `go.sum` is new and committed.
- New `internal/telemetry/telemetry.go`: explicit, minimal Go SDK
  initialization (no auto-instrumentation exists for Go, unlike the
  Java agent or Python zero-code approach) — `resource.New(ctx,
  resource.WithFromEnv(), ...)` (service name never hard-coded; read
  from `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES`), an OTLP/HTTP
  trace exporter feeding a `BatchSpanProcessor`, an OTLP/HTTP metric
  exporter feeding a `PeriodicReader` (neither's timing explicitly
  overridden, so both honor `OTEL_BSP_SCHEDULE_DELAY`/
  `OTEL_METRIC_EXPORT_INTERVAL` via the SDK's own env-aware defaults —
  confirmed by real 5s/1s timing in practice), and a global composite
  `tracecontext`+`baggage` propagator. Returns a `Shutdown` closure;
  setup failure returns an error (→ `log.Fatal` in `main`) rather than
  running with partial telemetry.
- `cmd/inventory-service/main.go`: `telemetry.Setup` is called only
  inside `run()`, never for the `healthcheck` subcommand (which still
  `os.Exit()`s before `run()` is reached, unchanged). Confirmed
  empirically: `docker run ... inventory-service healthcheck` with no
  server or Collector running fails in ~0.24s with a plain "connection
  refused" — no OTLP dial attempt, no delay. `shutdownTelemetry(ctx)` is
  called after `srv.Shutdown(ctx)` during graceful shutdown.
- `internal/server/server.go`: the whole `http.ServeMux` is wrapped with
  `otelhttp.NewHandler(mux, "inventory-service")` at the server
  boundary — zero changes to `internal/api/reservations.go` or
  `internal/reservation/`, no manual spans, no custom metrics. Initial
  attempt used `otelhttp.WithRouteTag` per route (matching a
  now-outdated idiom); real dependency resolution showed that function
  does not exist in `otelhttp` `v0.71.0` — inspected the actual
  installed package source instead of guessing, and found the simpler
  correct mechanism: this version's middleware re-derives the span name
  from the standard library's own matched `ServeMux` pattern
  (`*http.Request.Pattern`, populated by `ServeMux` itself post-dispatch)
  with no separate per-route call needed.
- `services/inventory-service/Dockerfile`: now `COPY go.mod go.sum ./`
  followed by `RUN go mod download` (for layer caching) before copying
  source; `gofmt`/`go vet`/`go test`/build all still run in the builder
  stage unchanged. Runtime stage, `CGO_ENABLED=0`, and
  `ENTRYPOINT ["/inventory-service"]` are all untouched — no shell,
  curl, wget, or extra binary added; all OTel code compiles into the
  same static distroless binary.
- Verified inside the actual Docker build (not just locally): `gofmt`
  clean, `go vet ./...` clean, `go test ./...` — all pre-existing tests
  (health, reservations validation/method-rejection/ID-uniqueness,
  server routing) still pass unchanged, plus the new (empty)
  `internal/telemetry` package compiles with no test files. Zero
  business-logic changes; the mux-wrapping change was verified not to
  alter any externally-visible HTTP behavior (405s, `Allow` headers,
  status codes, response bodies all unchanged) rather than rewriting
  any test's expectations.
- Started the full 8-container Compose stack, confirmed via container
  logs that inventory-service starts cleanly with no OTLP exporter
  errors, and directly exercised both `GET /health` and
  `POST /inventory/reservations` outside of any checkout flow — both
  return their unchanged response shapes.
- **Distributed trace topology — the main goal of this phase — proven
  against real Collector debug-exporter output for a live
  `POST /checkouts` request, not assumed:** one Trace ID
  (`4cb4f3d5f6a718f8aa06d1141dfd368b` in the first captured run) covers
  the checkout SERVER span, its CLIENT span toward payment (parent =
  checkout SERVER span ID) whose child is the payment SERVER span
  (parent = that CLIENT span's own ID), its CLIENT span toward
  inventory (also parented directly to the checkout SERVER span — a
  **sibling** of the payment CLIENT span, not a parent/child of it)
  whose child is the inventory SERVER span (parent = the inventory
  CLIENT span's own ID), and its CLIENT span toward notification
  (parented to the checkout SERVER span, with correctly no SERVER span
  of its own, since notification-service is uninstrumented). Confirmed
  the inventory SERVER span's resource carries
  `service.name: Str(inventory-service)`, `telemetry.sdk.language: Str(go)`,
  `telemetry.sdk.version: Str(1.46.0)`. Independently re-confirmed on a
  second, fully torn-down-and-restarted run, which produced a different
  (still internally consistent) Trace ID
  (`17f15fccfa5d2b44e9438a22c4b004b3`), ruling out a one-off
  coincidence. Empirically discovered and documented (not assumed): the
  Go otelhttp SERVER span carries `url.path` but not a separate
  `http.route` span attribute (unlike the Java/Python SERVER spans,
  which have both) — the Prometheus *metric* `http_route` label is
  still present and correct, this only affects trace-span attribute
  matching, and the generalized parser was written to match on
  `url.path` for the inventory branch accordingly.
- Queried Prometheus directly (not assumed) for inventory-service's
  real metric/label names: `http_server_request_duration_seconds_{count,sum,bucket}`,
  `http_server_request_body_size_bytes_{count,sum,bucket}`,
  `http_server_response_body_size_bytes_{count,sum,bucket}`, with
  `service_name="inventory-service"`, `http_route="/inventory/reservations"`,
  `http_request_method="POST"`, `http_response_status_code="200"`,
  `service_version="0.1.0"`, `deployment_environment_name="local"`,
  `telemetry_sdk_language="go"`, `telemetry_sdk_name="opentelemetry"`,
  `telemetry_sdk_version="1.46.0"`, `otel_scope_name="go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"`,
  `otel_scope_version="0.71.0"`. No custom inventory metrics were added.
- Generalized the trace parser: `git mv scripts/parse-payment-trace.py
  scripts/parse-checkout-trace.py`, then refactored its matching logic
  (the span-parsing core is unchanged) into a `spans_matching()` helper
  plus `find_client_then_server()`/`find_client()` helpers that require
  a checkout SERVER span, then independently resolve the payment branch
  (CLIENT → SERVER), the inventory branch (CLIENT → SERVER), and the
  notification CLIENT span, all anchored to that one SERVER span's
  Trace ID and Span ID. Preserved every Phase 2A.3 hardening rule
  unchanged: Trace IDs exactly 32 lowercase hex chars, Span IDs exactly
  16, fail-closed on any missing/invalid ID (no `None == None`), correct
  `ResourceSpans` → `service.name` attribution (including the earlier
  fix for `ResourceSpans #N`'s logger-prefixed line not matching a bare
  `startswith` check). Exits 0 only when checkout SERVER + both full
  branches + the notification CLIENT span are all found and correctly
  correlated in one trace; prints all seven span IDs on success.
- `scripts/verify-observability.sh` extended (not replaced): section G
  gained a bounded-retry Prometheus query for inventory-service's HTTP
  server metric; section H's parser call now invokes
  `scripts/parse-checkout-trace.py` instead of the old payment-only
  script. Every Phase 2A.1/2A.2/2A.3 check (including the
  checkout-service/payment-service metrics and baseline checkout trace
  grep-evidence checks) is unchanged. The full `make verify-observability`
  run passed end-to-end from a fully torn-down state, including the new
  inventory-metrics check and the generalized parser call, plus the
  persistence check.
- `.github/workflows/ci.yml` extended, not duplicated: the existing
  combined checkout+payment metrics step gained an inventory-service
  metrics query; the existing trace step now calls
  `scripts/parse-checkout-trace.py` instead of the payment-only script.
  Kept the same safe `if cmd1 && cmd2; then` control-flow pattern
  throughout. Locally reproduced equivalent verification via
  `make verify-observability` — **not yet verified running on GitHub
  Actions in this updated form** (Phase 2A.3's version of the workflow
  did run successfully there, per commit `1118fda`).
- **Limitation, honestly reported, not worked around:** this proves
  distributed tracing for the checkout → payment and checkout →
  inventory segments only. `notification-service` remains fully
  uninstrumented — checkout's CLIENT span toward it exists in the
  trace, but there is no notification SERVER span, so the full
  four-service chain is not yet a verified distributed trace. There is
  still no real trace backend (Collector `debug` exporter logs only),
  no application log pipeline, and no dashboards/alerts.

### Phase 2A.5 — notification-service OpenTelemetry instrumentation + complete four-service distributed trace

- `services/notification-service/package.json`/`package-lock.json`
  updated: added `@opentelemetry/sdk-node`, `exporter-trace-otlp-http`,
  `exporter-metrics-otlp-http`, `instrumentation-http` (all `0.222.0`),
  `@fastify/otel` (`0.21.0`), and `@opentelemetry/sdk-metrics` (`2.11.0`,
  a directly-imported peer not in the original pinned list but needed
  for `PeriodicExportingMetricReader` — added at the version the family
  already resolved to, matching the task's own allowance for this).
  Verified `npm ls` reports a fully deduped tree with no invalid/ERESOLVE
  state, and that `@fastify/otel`'s only peer
  (`@opentelemetry/api@^1.9.0`) resolves cleanly against `fastify@5.12.5`.
  Deliberately used the Fastify-maintained `@fastify/otel`, not the
  deprecated `@opentelemetry/instrumentation-fastify`. All six packages
  added as regular `dependencies` (not `devDependencies`) — confirmed
  present in the built image's `node_modules` after
  `npm prune --omit=dev`, with `typescript`/`tsx` correctly absent.
- New `services/notification-service/src/telemetry.ts`: explicit
  `NodeSDK` initialization — `OTLPTraceExporter` (passed directly as
  `traceExporter`, which makes `NodeSDK` construct an env-aware
  `BatchSpanProcessor` internally — confirmed by reading
  `@opentelemetry/sdk-node`'s own source, specifically
  `createBatchSpanProcessorFromEnv` reading `OTEL_BSP_SCHEDULE_DELAY`);
  `OTLPMetricExporter` wrapped in a `PeriodicExportingMetricReader`
  (whose `exportIntervalMillis` — unlike the trace side — is **not**
  env-aware on its own when constructed directly, confirmed by reading
  the installed package source, so `OTEL_METRIC_EXPORT_INTERVAL` is read
  explicitly in code instead); `HttpInstrumentation`; and
  `FastifyOtelInstrumentation` (from `@fastify/otel`) with
  `registerOnInitialization: true`. No `resource`/`serviceName`/
  `resourceDetectors` option passed — `NodeSDK`'s own default detectors
  (`envDetector`, `processDetector`, `hostDetector`) read
  `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES` from the environment,
  confirmed by reading source, so the service name is never hard-coded.
  Hit and fixed a real TypeScript interop bug while building this:
  `import FastifyOtelInstrumentation from "@fastify/otel"` (default
  import) failed `tsc` with "not constructable", because the package's
  `export =` + namespace type declarations don't resolve a default
  import cleanly under this project's `NodeNext` + `esModuleInterop`
  config; fixed by switching to the named import,
  `import { FastifyOtelInstrumentation } from "@fastify/otel"`.
- New `services/notification-service/src/bootstrap.ts`: the critical
  ESM-ordering piece. Calls `startTelemetry()` (which, via
  `registerOnInitialization: true`, patches the `fastify` module itself)
  synchronously first, then `await import("./server.js")` — a genuine
  dynamic import, deferring evaluation of `server.js`/`app.js`/`fastify`
  until after the patch is in place. A plain static top-level import
  would not have guaranteed this ordering, since ESM hoists and
  evaluates all of a module's static imports before its own top-level
  code runs. `services/notification-service/src/server.ts` updated
  minimally: imports `shutdownTelemetry` from `telemetry.ts` and calls
  it after `app.close()` on the SIGTERM/SIGINT path, and also (wrapped
  in its own try/catch) on the `app.listen()` startup-failure path,
  before `process.exit(1)` — telemetry is never abandoned mid-flush.
  `telemetry.ts`'s `shutdownTelemetry` races `sdk.shutdown()` against a
  10-second independent timeout, never reusing the HTTP server's own
  `shutdownCtx`-equivalent. `app.ts` required **zero** changes —
  `registerOnInitialization: true` alone was sufficient, confirmed
  empirically against real Collector output, not assumed.
  `package.json`'s `start` script and the Dockerfile's `CMD` both
  updated from `dist/server.js` to `dist/bootstrap.js` — per the task's
  own explicit allowance for a dedicated bootstrap entrypoint, this
  differs architecturally from payment-service's Compose-activated
  approach: the image itself now always launches instrumented (ESM
  ordering makes a Compose-level command override impractical here).
- Verified existing tests are fully isolated from OpenTelemetry: `test/*.test.ts`
  call `buildApp()` directly and never import `telemetry.ts` or
  `bootstrap.ts`, so `npm test` still passes **10/10**, unchanged, with
  no Collector running and no real OTLP exporters initialized. Zero
  business-logic changes under `src/routes/`, `src/services/`, or
  `src/types/`. `npm run typecheck` and `npm run build` both pass
  (after the `@fastify/otel` import fix above), and the full
  authoritative Docker build (`npm ci`, typecheck, test, build,
  `npm prune --omit=dev`) passes end-to-end.
- Started the full 9-container Compose stack, confirmed via container
  logs that notification-service starts cleanly through
  `dist/bootstrap.js` with no OTLP exporter errors, and directly
  exercised both `GET /health` and `POST /notifications` outside of any
  checkout flow — both return their unchanged response shapes.
- **Complete four-service distributed trace — the main goal of this
  phase — proven against real Collector debug-exporter output for a
  live `POST /checkouts` request, not assumed:** one Trace ID
  (`0dbb588b3800c3500d9d130cb4d3cb1b` in the first captured run) covers
  checkout's own SERVER span as the common parent of **three**
  independent branches: CLIENT → payment SERVER, CLIENT → inventory
  SERVER, and CLIENT → notification SERVER — each downstream SERVER
  span's Parent ID exactly equals its own branch's checkout CLIENT
  span's Span ID, and payment/inventory/notification are confirmed
  siblings (all three CLIENT spans share the same Parent ID — checkout
  SERVER's own Span ID — not a payment → inventory → notification
  chain). The notification SERVER span itself comes from the
  `@opentelemetry/instrumentation-http` scope (`Kind: Server`,
  `Name: POST /notifications`, `service.name: notification-service`);
  `@fastify/otel` additionally produces internal (`Kind: Internal`)
  "request" and "handler - notificationRoutes" child spans nested under
  it, which were correctly *not* mistaken for the upstream-facing SERVER
  span — matching by Parent-ID relationship, not by span name, is what
  made this reliable, since a second, *unrelated* "POST /notifications"
  SERVER span (from a direct manual test call, different Trace ID, no
  parent) was also present in the same logs and had to be correctly
  ignored. Independently re-confirmed on a second, fully
  torn-down-and-restarted `make verify-observability` run, which
  produced a different (still internally consistent) Trace ID
  (`7e5076b2865208151d356bdb7af540c6`), ruling out a one-off
  coincidence — Node/ESM startup ordering was treated as the highest
  correctness risk in this phase, so it was verified twice rather than
  once.
- Queried Prometheus directly (not assumed) for notification-service's
  real metric/label names: `http_server_request_duration_seconds_{count,sum,bucket}`,
  with `service_name="notification-service"`, `http_route="/notifications"`,
  `http_request_method="POST"`, `http_response_status_code="200"`,
  `service_version="0.1.0"`, `deployment_environment_name="local"`,
  `telemetry_sdk_language="nodejs"`, `telemetry_sdk_name="opentelemetry"`,
  `telemetry_sdk_version="2.11.0"`, `otel_scope_name="@opentelemetry/instrumentation-http"`,
  `otel_scope_version="0.222.0"`. No custom notification metrics were
  added. **Also observed, and worth reporting honestly:**
  `http_client_request_duration_seconds_*` series also appear for
  `service_name="notification-service"` — these are `HttpInstrumentation`
  capturing the SDK's own outbound OTLP export HTTP calls to
  `otel-collector:4318` (self-telemetry noise from patching the global
  `http` module), not application business traffic; harmless, and not a
  custom metric.
- Generalized `scripts/parse-checkout-trace.py` further (no new parser
  file created): added `notification_server` span matching
  (`service_name="notification-service"`, `kind="Server"`,
  `http.route="/notifications"`), and extended the matching loop to
  require all three downstream branches (payment, inventory,
  notification) via the same `find_client_then_server()` helper used
  for payment and inventory, replacing the old notification-CLIENT-only
  `find_client()` check (now removed as unused). All Phase 2A.3/2A.4
  hardening preserved unchanged: 32-hex Trace IDs, 16-hex Span IDs,
  fail-closed on missing/invalid IDs, correct `ResourceSpans`→
  `service.name` attribution. Exits 0 only when checkout SERVER + all
  three full branches are found and correctly correlated in one trace;
  prints all seven span IDs on success.
- `scripts/verify-observability.sh` extended (not replaced): section G
  gained a bounded-retry Prometheus query for notification-service's
  HTTP server metric; section H's parser-based check now requires the
  complete three-branch trace via the extended
  `scripts/parse-checkout-trace.py`. Every Phase 2A.1-2A.4 check
  (including the checkout/payment/inventory metrics and baseline
  checkout trace grep-evidence checks) is unchanged. The full
  `make verify-observability` run passed end-to-end **twice**, each
  from a fully torn-down state, each producing an independent, valid,
  complete seven-span trace — run specifically twice (rather than the
  usual once) because Node/ESM startup ordering is more delicate than
  the other three services' instrumentation mechanisms.
- `.github/workflows/ci.yml` extended, not duplicated: the existing
  combined checkout+payment+inventory metrics step gained a
  notification-service metrics query; the existing trace step's call to
  `scripts/parse-checkout-trace.py` now implicitly requires the complete
  three-branch trace (no CI-side code change needed beyond the parser
  itself already being generalized). Kept the same safe
  `if cmd1 && cmd2; then` control-flow pattern throughout. Locally
  reproduced equivalent verification via `make verify-observability`
  (twice) — **not yet verified running on GitHub Actions in this
  updated form** (Phase 2A.4's version of the workflow did run
  successfully there, per commit `d6c3292`, CI run #15).
- **Limitation, honestly reported, not worked around:** there is still
  no real trace backend (Collector `debug` exporter logs only), no
  application log pipeline, no dashboards/alerts, and no AI agent
  consumption of any of this telemetry. The four-service distributed
  trace proven here is a single, manually-triggered `POST /checkouts`
  request each time — nothing about this phase adds sampling
  configuration, trace retention, or automated/continuous trace
  collection beyond what the Collector's `debug` exporter already
  prints to its own logs.
