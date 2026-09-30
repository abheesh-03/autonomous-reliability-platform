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
**Phase 2B.4 — Production-Style Alerting**. An OpenTelemetry Collector, Prometheus, and
Grafana run via Docker Compose (Phase 2A.1). All four application
services are instrumented, each its own idiomatic way: `checkout-service`
with the OpenTelemetry Java auto-instrumentation agent (Phase 2A.2);
`payment-service` with OpenTelemetry Python zero-code
auto-instrumentation (Phase 2A.3); `inventory-service` with manual
OpenTelemetry Go SDK initialization plus `otelhttp` (Phase 2A.4); and
`notification-service` with manual OpenTelemetry Node SDK initialization
plus `@opentelemetry/instrumentation-http` and `@fastify/otel`
(Phase 2A.5) — together producing a complete, verified distributed
trace across checkout-service and its three sibling downstream branches
(payment, inventory, notification — **not** a sequential chain) for
every real `POST /checkouts` request. As of Phase 2B.1, traces are no
longer visible only in Collector logs: **Grafana Tempo 3.0.3** now runs
as a persistent, queryable trace backend, with the Collector's traces
pipeline exporting to both Tempo and the existing `debug` exporter.
A real checkout's seven-span trace has been retrieved directly from
Tempo's own HTTP query API (`GET /api/v2/traces/{traceID}`) and
independently re-verified — same Trace ID, same seven spans, same six
parent/child relationships — and confirmed to survive a graceful Tempo
restart using the same persistent volume. As of Phase 2B.2, the four
application services' existing stdout/stderr output — not new,
synthetic, or specially-formatted logs — is also centrally collected:
**Grafana Alloy 1.20.1** discovers each service's container via the
Docker API, ships its logs to **Grafana Loki 3.7.8**, and Loki
persists them to a named volume with a 7-day retention policy. Real,
non-synthetic log entries from all four services have been retrieved
directly from Loki's own query API, and a specific already-ingested
entry has been confirmed to survive a graceful Loki restart using the
same volume. `checkout-service` and `inventory-service` currently only
log at container startup — neither has per-request access logging
today — while `payment-service` and `notification-service` log per
request; none of the four services' current log output contains trace
or span IDs, so logs and traces are **not** correlated yet (see
Observability Infrastructure below). `checkout-service` still
synchronously orchestrates all three downstream services via
`POST /checkouts` (Phase 1B.4), with no change to any business logic or
application instrumentation; none of the four application services
connect to PostgreSQL. As of Phase 2B.3, Grafana is no longer just
three connected-but-unused datasources: **three dashboards are
auto-provisioned on startup** — Application Health (per-service HTTP
throughput/latency/error-rate from real Prometheus metrics, plus
checkout-service's downstream dependency traffic and latency),
Centralized Logging (real Loki log streams and log-line-rate-by-service,
no fabricated severity filter — see below), and Observability
Infrastructure (Prometheus scrape-target availability and the OTel
Collector's own ingestion/export/process health). Every query on every
panel was verified against real telemetry from a running stack before
being added, and a dedicated validator
(`scripts/verify-grafana-dashboards.py`) independently re-executes
every panel's own query directly against Prometheus/Loki, with
dashboard/interval variables substituted for real values. As of
Phase 2B.4, Prometheus evaluates four real alert rules
(`observability/prometheus/rules/alerts.yml`) and routes firing alerts
to **Prometheus Alertmanager 0.34.1**, which receives, groups, and
tracks their state through its own real API — a genuine, empirically
verified lifecycle test stopped `otel-collector`, watched
`TelemetryPipelineUnavailable` transition `inactive → pending → firing`
in Prometheus, confirmed the same alert active in Alertmanager,
restarted the Collector, and confirmed both systems returned to
`inactive`/resolved and that application telemetry resumed. There is
deliberately **no outbound notification integration** yet (email,
Slack, PagerDuty, or any webhook) — Alertmanager's single receiver is
a no-op local sink, so this phase builds the alert pipeline itself, not
a notification channel — and no automatic remediation, control plane,
or AI functionality of any kind.

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
- Outbound alert notification and an operator-facing control plane
  (the OTel Collector / Prometheus / Grafana infrastructure exists, all
  four application services export metrics and traces to it, one real
  `POST /checkouts` request produces a complete, verified distributed
  trace across checkout-service and all three of its downstream
  branches — payment, inventory, notification, as siblings, not a
  sequential chain — that trace is retrievable from a persistent trace
  backend, Grafana Tempo (Phase 2B.1), the four services' existing
  stdout/stderr logs are centrally collected and persisted via Grafana
  Alloy + Grafana Loki (Phase 2B.2), three dashboards built from real,
  verified queries are auto-provisioned in Grafana (Phase 2B.3), and,
  as of Phase 2B.4, Prometheus evaluates four real alert rules and
  routes firing alerts into Prometheus Alertmanager, with an
  empirically verified full inactive→firing→resolved lifecycle — see
  [Observability Infrastructure](#observability-infrastructure) below —
  but Alertmanager's only receiver is a no-op local sink today, with no
  email/Slack/PagerDuty/webhook integration and no control plane to
  consume these incident signals yet, no automatic remediation, and
  logs are not yet correlated with traces)
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

An observability stack — an OpenTelemetry Collector, Prometheus,
Grafana (with three auto-provisioned dashboards as of Phase 2B.3),
(Phase 2B.1) Grafana Tempo, (Phase 2B.2) Grafana Loki + Grafana Alloy,
and (Phase 2B.4) Prometheus Alertmanager — also runs via Docker Compose
(see [Observability Infrastructure](#observability-infrastructure)
below).
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
run. As of Phase 2B.1, that same trace has also been independently
retrieved and re-verified directly from **Grafana Tempo** (pinned
`3.0.3`, monolithic mode, local filesystem storage), which the
Collector's traces pipeline now exports to alongside the existing
`debug` exporter — traces are persisted and queryable via Tempo's own
HTTP API, not just visible in Collector logs, and the same trace was
confirmed retrievable after a graceful Tempo restart using its
persistent volume. As of Phase 2B.2, the four application services'
existing stdout/stderr output is also centrally collected: **Grafana
Alloy** (pinned `v1.20.1`) discovers each service's container via the
Docker API and ships its logs to **Grafana Loki** (pinned `3.7.8`,
single-binary mode, local filesystem storage), which persists them to
a named volume with a 7-day retention policy. Real log entries — not
synthetic lines injected to pass a check — have been retrieved
directly from Loki's own query API for all four services, and a
specific already-ingested entry was confirmed to survive a graceful
Loki restart using the same volume. `checkout-service` and
`inventory-service` currently only log at container startup (no
per-request access logging exists in either today); `payment-service`
and `notification-service` log per request. None of the four
services' current log output contains a trace or span ID, so logs and
traces are not yet correlated — see
[Observability Infrastructure](#observability-infrastructure) below
for details. As of Phase 2B.3, Grafana auto-provisions three
dashboards (Application Health, Centralized Logging, Observability
Infrastructure) built entirely from metrics/logs confirmed to exist
against a real running stack. As of Phase 2B.4, Prometheus evaluates
four real alert rules and routes firing alerts to **Prometheus
Alertmanager** (pinned `v0.34.1`), which receives, groups, and tracks
alert state through its own real API; a genuine controlled failure
(stopping `otel-collector`) was used to empirically prove a real rule's
full `inactive → pending → firing → (Alertmanager) → resolved →
inactive` lifecycle, and that application telemetry resumes afterward.
Alertmanager's only receiver is a no-op local sink — no outbound
notification integration exists yet, and no control plane consumes
these incident signals yet. No AI integration has been added yet.

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
Collector, Prometheus, Grafana, (Phase 2B.1) Grafana Tempo, and
(Phase 2B.2) Grafana Loki + Grafana Alloy, all running via Docker
Compose (Phase 2A.1). As of Phase 2A.5, **all four application
services** feed this stack real telemetry; as of Phase 2B.1, traces
are also persisted and queryable in Tempo, not just visible in
Collector logs; as of Phase 2B.2, each service's existing stdout/stderr
logs are also centrally collected and persisted in Loki, via a
completely separate path that does **not** go through the Collector.

```
checkout-service      --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
payment-service       --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
inventory-service     --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
notification-service  --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
(all four)            --OTLP (traces)--> otel-collector --debug exporter--> collector logs
(all four)            --OTLP (traces)--> otel-collector --OTLP--> tempo --> grafana

(all four)   --stdout/stderr (via dockerd)--> alloy --loki.write--> loki --> grafana
  (a separate path: Alloy reads each container's logs directly from the
   Docker API, not via the OTel Collector or any OTEL_* setting above)

One real checkout trace — a COMPLETE distributed trace across all four services,
now persisted in and independently re-verified from Tempo's own HTTP query API:
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
  like `service.name` become Prometheus labels), and traces → **two**
  exporters — the existing `debug` exporter (prints detailed span data
  to the Collector's own container logs; kept because
  `scripts/verify-observability.sh` and `scripts/parse-checkout-trace.py`
  still read it) and, as of Phase 2B.1, an OTLP exporter to Tempo (type
  `otlp_grpc`, not the deprecated `otlp` alias — confirmed via a real
  Collector deprecation warning during implementation). Its own internal
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
- **`tempo`** (`grafana/tempo:3.0.3`, Phase 2B.1) — a persistent,
  queryable distributed-tracing backend, running in monolithic mode
  (no `target` set, so it defaults to `all`) with local filesystem
  storage under `/var/tempo` on a persistent named volume (`tempo_data`).
  Single-tenant (no multitenancy/auth configured). Its internal OTLP
  receiver (gRPC `:4317`, HTTP `:4318`) is **not** published to the
  host — only otel-collector talks to it, over the Compose network, as
  `tempo:4317`. Only its HTTP query API (`:3200`) is published, bound to
  `127.0.0.1` like every other observability port. No Docker-level shell
  or curl/wget exists in this image either (`ENTRYPOINT` is the `/tempo`
  binary directly), so the healthcheck instead uses the binary's own
  built-in `-health` mode (confirmed empirically: it performs a GET
  against its own `/ready` and exits 0/1 accordingly).
- **`loki`** (`grafana/loki:3.7.8`, Phase 2B.2) — a persistent,
  queryable log-storage backend, running in single-binary mode with
  local filesystem storage on a persistent named volume (`loki_data`).
  Single-tenant (`auth_enabled: false`). TSDB index + schema `v13` (the
  image's own current default, confirmed empirically, not assumed) and
  a `compactor`-driven 7-day retention (`limits_config.retention_period:
  168h`). Only its HTTP API (`:3100`) is published, bound to
  `127.0.0.1`. Like otel-collector and tempo, the official image has no
  shell/curl/wget — but unlike tempo, its `/usr/bin/loki` binary also
  has no built-in `-health`-style flag, so readiness is checked purely
  externally, via `GET /ready` from the host.
- **`alloy`** (`grafana/alloy:v1.20.1`, Phase 2B.2) — reads
  `/var/run/docker.sock` to discover containers, filters them down to
  this Compose project's four application services (never
  otel-collector/prometheus/tempo/grafana/loki/alloy's own logs, and
  never an unrelated Compose project — see
  [alloy configuration](#alloy-configuration-phase-2b2) below), and
  ships their stdout/stderr to Loki via `loki.write`. Its debug/health
  HTTP interface (`:12345`) is published to `127.0.0.1` only. Has a
  shell but no curl/wget, so — like loki — readiness is checked
  externally, via its own `GET /api/v0/web/components` API (all 4
  pipeline components must report `health.state: healthy`).
- **`alertmanager`** (`prom/alertmanager:v0.34.1`, Phase 2B.4) —
  receives alerts Prometheus fires from
  `observability/prometheus/rules/alerts.yml`, groups them
  (`group_by: [alertname, severity]`), and tracks their firing/resolved
  state through its own real HTTP API (`GET /api/v2/alerts`,
  `GET /api/v2/status`). Single-instance, persistent local storage
  (`alertmanager_data`, `--storage.path=/alertmanager`). Its single
  receiver (`observability/alertmanager/alertmanager.yml`) is a no-op
  local sink with no integration configured at all — a normal, fully
  valid Alertmanager receiver that still receives/groups/tracks every
  alert routed to it, it just never sends anything anywhere; see
  [alertmanager configuration](#alertmanager-configuration-phase-2b4)
  below. Has both a shell and `wget` (confirmed via `docker run
  --entrypoint /bin/sh ... -c "which wget"`), so — unlike loki/alloy —
  it has a real Docker-level healthcheck.
- **`grafana`** — Prometheus (default), Tempo (Phase 2B.1), Loki
  (Phase 2B.2), and Alertmanager (Phase 2B.4) are all auto-provisioned
  as datasources
  (`observability/grafana/provisioning/datasources/datasource.yml`,
  resolving `http://prometheus:9090`/`http://tempo:3200`/
  `http://loki:3100`/`http://alertmanager:9093` by Compose service
  name) so no manual click-through setup is needed after `docker
  compose up`. As of Phase 2B.3, three dashboards
  (`observability/grafana/provisioning/dashboards/json/`) are also
  auto-provisioned — see
  [grafana dashboards (Phase 2B.3)](#grafana-dashboards-phase-2b3)
  below. Anonymous auth is disabled; the admin password is a local-only
  placeholder from `.env.example`, never a real credential.

All host ports above (`4317`/`4318`/`13133` for otel-collector, `9090`
for prometheus, `3200` for tempo, `3100` for loki, `12345` for alloy,
`9093` for alertmanager, `3000` for grafana) are published bound to
`127.0.0.1` only — none of them sit behind authentication (Grafana is
the exception, via its own admin login), so they are not reachable
from other machines on the
network even in local development. This differs from the four Phase 1
application services and PostgreSQL, whose ports remain published on
all interfaces.

### tempo configuration (Phase 2B.1)

`observability/tempo/tempo.yaml` was built and verified empirically
against the actual pinned `grafana/tempo:3.0.3` image, not assumed from
older Tempo documentation — its config schema changed significantly in
v3.x. Two real, concrete failures were hit and fixed during
implementation: top-level `ingester:` and `compactor:` keys (valid in
older Tempo versions) are **rejected** by this version's config parser
(`field ingester not found in type app.Config`) — v3.x replaced that
architecture internally with `live-store` / `backend-scheduler` /
`backend-worker` components, confirmed via real startup logs, none of
which require any YAML config from us. The final working config sets
only `server.http_listen_port` (`3200`), `distributor.receivers.otlp`
(gRPC `:4317` + HTTP `:4318`), and `storage.trace` (`backend: local`,
with separate `local.path` and `wal.path` under `/var/tempo`).
Retention is intentionally left at Tempo's documented built-in default
(336h / 14 days) — an explicit override was attempted
(`backend_scheduler.provider...`) but v3.x's real schema for this
differs from what limited public documentation suggests, and guessing
further against a largely undocumented internal path was not worth the
risk; 14 days is already appropriate for local development. No Kafka,
MinIO, S3, or distributed Tempo components are configured anywhere, and
real startup logs confirm no attempt to reach Kafka.

### loki configuration (Phase 2B.2)

`observability/loki/loki.yaml` was built from the actual pinned
`grafana/loki:3.7.8` image's own bundled default config (extracted via
`docker create` + `docker cp`, since the image has no shell/`cat` to
view it in-container) and then extended, not written from scratch —
confirming empirically that this version's own current default already
uses the TSDB index with schema `v13`, rather than assuming it. Runs in
single-binary mode (`auth_enabled: false`, single tenant, in-memory
ring, replication factor 1) with all persistent paths — chunks, rules,
compactor working directory — under `common.path_prefix: /loki` on the
`loki_data` named volume. Retention is `limits_config.retention_period:
168h` (7 days) via the `compactor` (`retention_enabled: true,
delete_request_store: filesystem`); this is the documented mechanism
this image version actually supports for filesystem-backed retention,
not an assumed or unverified setting — the config was accepted by the
real binary on the first attempt, with no schema rejections. No S3,
MinIO, or distributed Loki components (ring/gateway/multi-tenant) are
configured anywhere.

### alloy configuration (Phase 2B.2)

`observability/alloy/config.alloy` implements the pipeline
`discovery.docker → discovery.relabel → loki.source.docker →
loki.write`, validated against the actual pinned `grafana/alloy:v1.20.1`
binary via `alloy validate` (not just by inspection). `discovery.relabel`
applies two sequential `keep` rules — first the container's
`com.docker.compose.project` label, then its `com.docker.compose.service`
label against `checkout-service|payment-service|inventory-service|notification-service`
— so a container must match **both** to be collected; nothing else in
this Compose project (postgres, otel-collector, prometheus, tempo,
grafana, loki, or Alloy's own logs) is ever collected, confirmed via
Loki's own `/loki/api/v1/label/service/values` API returning exactly
the four expected service names and nothing else.

**Compose project filter (hard-coded name avoided):** the project-name
match is `regex = sys.env("COMPOSE_PROJECT_NAME")`, not a literal
string. `docker-compose.yml` passes `COMPOSE_PROJECT_NAME` into the
`alloy` container from Compose's own `${COMPOSE_PROJECT_NAME}`
interpolation variable, which resolves to Compose's actual effective
project name for that run — confirmed empirically to correctly track
all three ways Compose can determine it (the checkout directory's
basename by default, an explicit `-p <name>` flag, or an explicit
`COMPOSE_PROJECT_NAME` environment variable) — so this still works
correctly if the repository is checked out under a differently-named
directory, without ever risking a match against an unrelated Compose
project on the same Docker host: `discovery.relabel`'s `regex` is fully
anchored (`^...$`, the same convention as Prometheus relabeling), so
it is always an exact match, never a substring/prefix match, and if
`COMPOSE_PROJECT_NAME` were ever unset, `sys.env(...)` returns `""`,
which matches no real project label — i.e. this fails closed (collects
nothing) rather than collecting another project's containers.

**Labels:** `service` and `compose_project` are set from the same two
Compose container labels used for filtering; `environment` is a fixed
`local` value. None of these are high-cardinality — no `trace_id`,
`span_id`, `request_id`, or `container_id` is ever set as a Loki
stream label (those may appear in log line *content*, never as an
indexed label). One side effect observed but not configured by us:
`loki.source.docker` automatically adds its own `service_name` label
with the same four values as our `service` label.

**Startup-order reliability (no observed race condition):** Alloy's
`loki.source.docker` component reads each discovered container's log
history from Docker's own log driver, not just a live tail of new
writes from the moment it attaches — confirmed directly: with `alloy`
stopped, `checkout-service` and `inventory-service` were restarted
(each emitting its one-time startup log line while Alloy was down),
then `alloy` was started **after** those lines were already written,
and both were still retrieved from Loki afterward, matching the exact
Docker-side timestamps. This means `checkout-service`/`inventory-service`
starting before `alloy` in CI or locally — a normal, expected sequence
under `docker compose up -d`, which starts all services concurrently
— does not risk losing their startup logs; no corrective reordering
was needed for this reason. (`scripts/verify-observability.sh` and CI
still wait for Loki/Alloy readiness before the checkout regression
request, but that ordering is for a stable/known-good state to assert
against, not because logs would otherwise be lost.)

**Docker socket access:** see [Docker access and security
(Phase 2B.2)](#docker-access-and-security-phase-2b2) below.

### Docker access and security (Phase 2B.2)

`alloy` mounts `/var/run/docker.sock:/var/run/docker.sock:ro` to
discover containers and read their logs. This grants Alloy **full**
Docker daemon API access — equivalent to root on whatever host runs
that daemon — not a "logs-only" scope; the Docker API has no such
scope to begin with. The trailing `:ro` only prevents Alloy from
replacing or deleting the socket special file itself; it does **not**
restrict which Docker API calls Alloy can make through it, and this
repository does not claim otherwise. The Docker API itself is never
published on any host port.

This same `docker-compose.yml` is also used by CI
(`.github/workflows/ci.yml`, via `make db-up` → `docker compose up -d`),
including on `pull_request` from forks — so this mount is active there
too, not only in local development. That is judged acceptable, not
because the mount is somehow restricted, but because it adds no
meaningful privilege beyond what that CI job's own steps already have:
`./mvnw test`, `npm ci`, `go test ./...`, and `pip install -e` already
execute arbitrary PR-authored code directly on the runner, with the
runner's own ambient Docker access (the `docker compose` commands in
that same workflow run unsandboxed from it too), on a single-use VM
with no persistent state and no secrets exposed to fork PRs. If this
workflow ever moves to a shared, persistent, or self-hosted runner, or
switches to `pull_request_target`, this reasoning no longer holds and
would need to be revisited.

### grafana dashboards (Phase 2B.3)

Three dashboards are auto-provisioned on Grafana startup via
`observability/grafana/provisioning/dashboards/dashboards.yml` (a file
provider pointed at
`observability/grafana/provisioning/dashboards/json/`) — a second,
separate mount alongside the existing `datasources/` mount in
`docker-compose.yml`'s `grafana` service, added without touching or
shadowing it. Every metric/label/query below was confirmed against a
real running stack (real checkout traffic, real Loki log streams)
*before* being written into a dashboard — none are assumed from
documentation.

- **Application Health** (`application-health`, Prometheus): request
  throughput (`sum by (service_name) (rate(http_server_request_duration_seconds_count{job="otel-collector-app-metrics"}[$__rate_interval]))`),
  p50/p95 latency via `histogram_quantile` over
  `http_server_request_duration_seconds_bucket` (all four services
  confirmed to share identical OTel SDK default histogram boundaries —
  5ms to 10s — so p95 is directly comparable across services), HTTP
  error rate split into 4xx/5xx using the real `http_response_status_code`
  label (confirmed populated with a genuine `400` from an invalid
  checkout request during verification), and checkout-service's
  downstream dependency traffic/latency via
  `http_client_request_duration_seconds_*{service_name="checkout-service"}`
  (scoped specifically to `checkout-service` so notification-service's
  own unrelated outbound OTLP-export HTTP calls, which are also
  auto-instrumented, don't pollute the panel). A `service` template
  variable (`label_values(http_server_request_duration_seconds_count{job="otel-collector-app-metrics"}, service_name)`)
  filters every panel to one, several, or all four services. Absence of
  traffic renders as a gap (PromQL's `0/0 = NaN` for the error-rate
  ratio, no series at all for throughput/latency), never a fabricated
  zero.
- **Centralized Logging** (`centralized-logging`, Loki): a log-line-rate
  panel (`sum by (service) (rate({service=~"$log_service"}[$__interval]))`
  — LogQL's `rate()`, entries/sec, not `count_over_time()`'s raw count
  per window, which was the original implementation and was corrected
  after review since a raw count is not a rate and isn't comparable
  across different zoom levels) and a raw log-stream panel
  (`{service=~"$log_service"}`), both behind a `log_service` variable.
  Deliberately **no severity/level filter**:
  Loki's own automatic `detected_level` heuristic was checked against
  real log output from all four services and found unreliable —
  checkout-service (Spring Boot `INFO `/`WARN ` prefixes) and
  payment-service (Uvicorn `INFO:` prefix) are classified correctly,
  but inventory-service (plain Go output, no level prefix) and
  notification-service (pino JSON with a numeric `level` field) both
  came back `"unknown"`. Building a severity filter on top of that
  would silently misrepresent half the services, so it was not added —
  an investigated-and-rejected feature, not an oversight. The dashboard
  description also restates the pre-existing limitations directly (not
  hidden): checkout-service/inventory-service only log at startup, and
  no log line in any of the four services contains a trace or span ID,
  so **this dashboard does not claim or imply log/trace correlation**.
- **Observability Infrastructure** (`observability-infrastructure`,
  Prometheus): scrape-target availability (`up{job=~"prometheus|otel-collector|otel-collector-app-metrics"}`,
  the only three scrape jobs Prometheus is configured with), Collector
  telemetry ingestion (`otelcol_receiver_accepted_spans`/
  `_accepted_metric_points`/`_refused_spans`/`_refused_metric_points` by
  receiver — refused *metric points* are a genuinely separate query
  from refused spans, added after review found the original
  implementation only queried refused spans while its description
  claimed both), Collector
  export health (`otelcol_exporter_sent_spans` by exporter — `debug`
  and `otlp_grpc/tempo` — and `otelcol_exporter_queue_size`), and
  Collector process health (`otelcol_process_uptime`,
  `otelcol_process_memory_rss`). This is the Collector's own internal
  self-telemetry (`job="otel-collector"`, scraped from its own `:8888`
  endpoint), not the application services' business metrics.

**Datasource references use plain names, not UIDs — a deliberate
correction made during implementation, not the original design:** an
earlier version of `datasource.yml` pinned an explicit `uid:` on each
datasource so dashboard JSON could reference stable UIDs. This broke
Grafana startup outright on this very machine's own `grafana_data`
volume (already containing Prometheus/Tempo/Loki datasources
auto-provisioned under earlier, auto-generated UIDs from Phase 2B.1/
2B.2): Grafana 13.0.2 fails with `"Datasource provisioning error: data
source not found"` rather than reconciling a name-matched datasource's
UID change, and refuses to start at all. Since this repository's
`grafana_data` volume is meant to survive upgrades across phases (see
the volume-persistence checks in `scripts/verify-observability.sh`),
pinning a `uid` here would break Grafana for anyone who already ran an
earlier phase before pulling this one. `datasource.yml` therefore has
no explicit `uid:` fields, and every dashboard panel/target references
its datasource by name (`"Prometheus"` / `"Loki"`) instead, which
Grafana resolves identically regardless of the datasource's actual
underlying UID — confirmed working against both a fresh and an
already-populated `grafana_data` volume.

**Verification** (`scripts/verify-grafana-dashboards.py`, stdlib-only,
the same script both the local verifier and CI run): confirms Grafana
itself is healthy; that all three dashboards exist, are
`meta.provisioned` (not UI-created), have exactly their expected
panels; that every panel's and every target's datasource reference
resolves to the dashboard's expected datasource *and* that that
datasource is really provisioned in Grafana with the expected type
(cross-checked against `GET /api/datasources`); that expected template
variables exist, reference the right datasource, and have a nonempty
query definition; that panel query text references the metric/label
substrings this script independently confirmed are real; and then, for
**every panel** (not a separately maintained sample list, which risks
silently drifting from what the dashboards actually ship — an earlier
version of this script worked that way and was corrected), requires
every target to have a nonempty expression and the right datasource,
substitutes each dashboard's own template variables (using their real
`allValue`, e.g. `$service` → `.*`) and Grafana's built-in interval
variables (`$__rate_interval`/`$__interval` → `5m`) for concrete
values, and **re-executes that exact substituted expression** directly
against Prometheus's or Loki's own HTTP API — bypassing Grafana's query
proxy entirely. A query is recognized as legitimately allowed to be
empty (HTTP 4xx **or** 5xx error rate, refused-telemetry counters) by
inspecting its own expression text for a `"[45].."` status-code match
or a `refused` metric name, not a hand-maintained list — a CI run that
only issues successful requests against the running Compose application
produces no 4xx or 5xx samples in Prometheus at all (client-side 400s
in CI logs from a service's own unit/build tests never reach the
running application's telemetry, so they must not be mistaken for
evidence this query will have data; this was a real CI failure, fixed
after GitHub Actions run #19 caught it, not a hypothetical); every
other target — and every panel as a whole, unless every one of its
targets is of the legitimately-empty kind — is required to return
real, nonempty data.
This script cannot and does not verify that a panel visually renders
correctly in a browser — only that Grafana served the expected
provisioned structure and that its actual queries are valid and return
real data.

### alertmanager configuration (Phase 2B.4)

`observability/alertmanager/alertmanager.yml` was validated against the
actual pinned `prom/alertmanager:v0.34.1` image's own `amtool
check-config`, not just YAML-parsed. Version selection: the Alertmanager
image was pulled and its own `--version` output inspected directly
(not assumed) across every tag from `v0.28.1` up through `v0.34.1`,
confirming `v0.35.0` and `v0.34.2` do not exist — `v0.34.1` (built
2026-09-17, less than two weeks before this phase) is the genuine
latest stable release. A simple local `route`/`receiver` pair:
`group_by: [alertname, severity]`, `group_wait: 10s`,
`group_interval: 30s`, `repeat_interval: 1h`, routing to a single
receiver, `local-null`, with **no integration configured on it at
all**. This is a normal, fully valid Alertmanager receiver — not a
fake or invented notification service — confirmed empirically to still
receive, group, and track the full firing/resolved lifecycle of every
alert routed to it, visible through Alertmanager's own real
`GET /api/v2/alerts` and `GET /api/v2/status` APIs; it simply never
sends a notification anywhere. `observability/prometheus/prometheus.yml`
gained `rule_files: [/etc/prometheus/rules/*.yml]` and
`alerting.alertmanagers` pointed at `alertmanager:9093` — confirmed via
Prometheus's own `GET /api/v1/alertmanagers` that it discovered exactly
that one target. Prometheus is the only rule evaluator in this stack;
Alertmanager never evaluates a PromQL expression itself, only receives
what Prometheus already decided is firing.

### alert rules (Phase 2B.4)

`observability/prometheus/rules/alerts.yml`, validated against the
actual pinned `prom/prometheus:v3.15.0` image's own `promtool check
rules` (4 rules found, no errors). Every metric/label referenced below
was queried directly against a real running stack (with real checkout
traffic) before being written into a rule — none are assumed. `for:`
durations are chosen relative to this stack's real 15s
`scrape_interval`/`evaluation_interval`, so a single scrape hiccup can
never flip a rule to firing.

- **`TelemetryPipelineUnavailable`** — the deterministic rule used for
  the lifecycle test below.
  `up{job=~"otel-collector|otel-collector-app-metrics"} == 0`,
  `for: 1m` (4 consecutive failed 15s scrapes). Labels:
  `severity=critical`, `component=otel-collector`,
  `category=observability-infrastructure`.
- **`CheckoutServerErrors`** — real HTTP 5xx activity from
  checkout-service, using the real `http_response_status_code` label; a
  genuine 4xx never contributes.
  `sum(rate(http_server_request_duration_seconds_count{service_name="checkout-service",
  http_response_status_code=~"5.."}[5m])) > 0`, `for: 2m`. Labels:
  `severity=critical`, `component=checkout-service`,
  `service=checkout-service`.
- **`CheckoutHighLatency`** — p95 latency for `POST /checkouts` via
  `histogram_quantile` over the real histogram buckets, threshold
  chosen from this stack's own observed baseline, not guessed: 20 real
  checkout requests were fired and measured directly — 19/20 completed
  within 10ms, 20/20 within 250ms (every downstream call is a local
  Docker-network hop). The `1s` threshold is roughly 40-100x that
  baseline, so it will not false-fire under normal local/CI load, and
  is deliberately **not** forced to fire during verification (doing so
  would require artificially slowing business logic, out of this
  phase's scope — it is expected to stay inactive throughout
  verification, same as `CheckoutServerErrors`).
  `histogram_quantile(0.95, sum by (le)
  (rate(http_server_request_duration_seconds_bucket{service_name="checkout-service",
  http_route="/checkouts"}[5m]))) > 1`, `for: 2m`. Labels:
  `severity=warning`, `component=checkout-service`,
  `service=checkout-service`.
- **`CollectorRefusingTelemetry`** — real refusal activity at the
  Collector's OTLP receiver, using the real
  `otelcol_receiver_refused_spans`/`otelcol_receiver_refused_metric_points`
  counters (confirmed always present as real series, value `0` at
  rest — not absent — so no `or vector(0)` guard is needed).
  `sum(rate(otelcol_receiver_refused_spans{job="otel-collector"}[5m]))
  + sum(rate(otelcol_receiver_refused_metric_points{job="otel-collector"}[5m])) > 0`,
  `for: 1m`. Labels: `severity=warning`, `component=otel-collector`,
  `category=observability-infrastructure`.

Every rule also carries `summary`/`description` annotations (with
`{{ $labels.* }}` templating where useful) — no bare alert with no
human-readable context.

**Grafana Alertmanager datasource:** Grafana OSS 13.0.2 genuinely
supports this — added `type: alertmanager`,
`jsonData.implementation: prometheus`, `url: http://alertmanager:9093`
to `datasource.yml`, confirmed via Grafana's own `/api/datasources`
that it provisioned correctly, and **empirically proved functional**
(not just "configured"): a real request through Grafana's own
datasource proxy (`GET /api/datasources/proxy/uid/<uid>/api/v2/status`)
returned Alertmanager's real cluster status and version. Confirmed the
three existing dashboards (and `scripts/verify-grafana-dashboards.py`)
are unaffected by the fourth datasource. No Grafana-managed alert rules
were added — Prometheus remains the only rule evaluator, per this
phase's explicit scope.

**Alert lifecycle acceptance test**
(`scripts/verify-alert-lifecycle.sh`) — the most important part of this
phase: proves a **real** Prometheus rule goes through its full
lifecycle because of a genuine, controlled failure, not a rule-file
edit or a direct POST to Alertmanager's API. Sequence, every step
using real HTTP APIs (`scripts/verify-alerting.py`) with bounded
retries: confirm both Collector scrape targets UP and
`TelemetryPipelineUnavailable` initially `inactive` → `docker compose
stop otel-collector` → poll until Prometheus reports the rule `firing`
**and** Alertmanager's own `GET /api/v2/alerts` shows a matching,
active (non-resolved) alert with the expected `severity`/`component`
labels → `docker compose start otel-collector` → wait for Collector
readiness → poll until Prometheus reports the rule `inactive` again
**and** Alertmanager no longer reports an active (non-resolved) match
→ fire one more real checkout and confirm
`http_server_request_duration_seconds_count` for `/checkouts`
genuinely increased. Run against the real stack, this rule was
observed transitioning `inactive → pending → firing` in Prometheus
(`pending` visible for several polling attempts before `firing`, as
expected given `for: 1m`), confirmed active in Alertmanager with
`severity=critical component=otel-collector`, then fully recovered —
Prometheus `inactive`, Alertmanager showing zero active matches — and a
fresh checkout confirmed telemetry resumed (request count incremented
by exactly 1). The script restores `otel-collector` via its own `EXIT`
trap if anything fails partway through, so a failure here never leaves
the environment with the Collector stopped; both the local verifier and
CI reuse this identical script.

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
`scripts/verify-observability.sh`) runs the full Phase 2A.1-2B.4
verification path in one deterministic script (sections A-R) — starts
Compose, waits for every service's health (with the `otel-collector`
exception above; `tempo` has a real healthcheck and is included in the
normal wait loop; `loki`/`alloy` have neither and are checked
functionally — see below), checks Prometheus targets and all three
Grafana datasources, re-runs the `POST /checkouts` regression check,
then verifies all four application services' HTTP server metrics (plus
checkout's HTTP client metrics) actually reached Prometheus, that trace
evidence for the checkout SERVER span and all three downstream CLIENT
spans appears in the Collector's own logs, and that ONE checkout trace
is a **complete** distributed trace across **all three** downstream
branches — payment, inventory, and notification, siblings, not
parent/child of each other — using a small deterministic parser
(`scripts/parse-checkout-trace.py`, generalized across Phases 2A.3-2A.5
from an initial payment-only parser). It then independently re-verifies
that exact same trace directly against Tempo's own HTTP query API using
a second small deterministic validator, `scripts/verify-tempo-trace.py`
(same script used in CI — no duplicated validation logic), and confirms
the trace remains retrievable — with all seven spans and all six
parent/child relationships still correct — after a graceful
`docker compose restart tempo` using the same persistent volume. As of
Phase 2B.2, it also: waits for Loki `/ready` and for all 4 Alloy
pipeline components to report healthy; verifies Grafana's Loki
datasource; verifies real, non-synthetic logs from all four application
services via `scripts/verify-loki-logs.py` (the same validator CI uses
— no duplicated validation logic there either); and proves an
already-ingested log line survives a graceful `docker compose restart
loki` using the same persistent volume, with `alloy` stopped throughout
so it cannot resend it, then confirms `alloy` and normal log collection
both resume once restarted. As of Phase 2B.3, it also verifies all
three auto-provisioned Grafana dashboards via
`scripts/verify-grafana-dashboards.py` (the same validator CI uses —
no duplicated validation logic): correct panels, correct datasource
references, valid template variables, and every panel's own PromQL/
LogQL (variables substituted with real values) re-executed directly
against Prometheus and Loki with real data. As of Phase 2B.4, it then
verifies Alertmanager health and that Prometheus loaded all four
expected alert rules, each starting `inactive`
(`scripts/verify-alerting.py`), and runs the full alert lifecycle
acceptance test (`scripts/verify-alert-lifecycle.sh`, also reused by
CI) — deliberately placed after every other telemetry/dashboard check,
since stopping `otel-collector` for the controlled failure would
otherwise invalidate them — then explicitly re-confirms both Collector
scrape targets are back `UP` afterward. All of this uses bounded
retries (metric/trace/log/alert propagation, Tempo's/Loki's own
ingest-to-query paths, and post-restart readiness are all asynchronous)
and stays safe under `set -euo pipefail`. The script then always tears
the environment down (without deleting volumes) and confirms every
named volume, including `tempo_data`, `loki_data`, `alloy_data`, and
`alertmanager_data`, still exists.

**Not implemented yet:** outbound alert notification (email, Slack,
PagerDuty, or any webhook — Alertmanager's only receiver is a no-op
local sink); a control plane to consume these incident signals; log/
trace correlation (no service's current log output contains a trace or
span ID — see [alloy configuration](#alloy-configuration-phase-2b2)
above); dashboard panels beyond what Phase 2B.3 built (e.g. no
Tempo/traces panel yet); Grafana-managed alert rules (Prometheus
remains the only rule evaluator); and any consumption of telemetry by
an agent or automatic remediation. Those are deliberately deferred to
later phases.

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
startup), that Grafana's health API and provisioned Prometheus + Tempo +
Loki datasources are reachable, that Tempo itself reaches a healthy
state, that Loki reaches `/ready` and all 4 Alloy pipeline components
report healthy (both checked before the checkout smoke test, so a known
functioning pipeline is in place before it — see
[alloy configuration](#alloy-configuration-phase-2b2) above for why this
ordering is about asserting a known-good state rather than avoiding any
actual log-loss race), that all four application services' relevant
HTTP metrics (checkout's server+client, payment's, inventory's, and
notification's server metrics) actually reach Prometheus, that trace
evidence (checkout SERVER span, all three downstream CLIENT spans) plus
a deterministic proof that ONE checkout trace is a **complete**
distributed trace across **all three** downstream branches — payment,
inventory, and notification (via `scripts/parse-checkout-trace.py`) —
appear in the Collector's logs, that that exact same trace is
independently retrievable and re-verifiable directly from Tempo's own
HTTP query API (via `scripts/verify-tempo-trace.py`, the identical
script the local verifier uses — no duplicated validation logic), and —
new in this phase — that real, non-synthetic logs from all four
application services are retrievable directly from Loki's own query
API (via `scripts/verify-loki-logs.py`, again the identical script the
local verifier uses), all via bounded retry loops (the OTel Java
agent's, Python SDK's, Go SDK's, and Node SDK's export intervals,
Prometheus's scrape cycle, the Collector's batch export, Tempo's own
ingest-to-query path, and Docker log discovery/shipping/Loki indexing
are all asynchronous) — then always tears the environment down
(without deleting volumes). The more expensive Loki restart-persistence
test (see the bundled local verifier above) remains local-only; CI
independently proves all four services' logs are queryable, which is
sufficient given the restart test's cost. As of Phase 2B.3, CI also
runs `scripts/verify-grafana-dashboards.py` (the identical script the
local verifier uses) after the checkout/metrics/log steps above, since
several of its panels need that real traffic and log ingestion to
already have happened. As of Phase 2B.4, CI also waits for Alertmanager
to become healthy, runs `scripts/verify-alerting.py` to confirm all
four alert rules loaded and are initially `inactive`, then runs the
identical `scripts/verify-alert-lifecycle.sh` the local verifier
uses — no lifecycle logic duplicated in the workflow YAML — proving the
same real `inactive → firing → Alertmanager → resolved → inactive`
transition and telemetry recovery in CI, placed after every other
telemetry/dashboard step since it deliberately stops `otel-collector`.
Alertmanager logs were added to the existing "Show service logs"
failure-diagnostics step.

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
Phase 2A.5 extended the same two steps once more with
`notification-service`'s checks and was committed (`7e348a2`); that
version also ran successfully on GitHub Actions (run #16), working tree
clean afterward. Phase 2B.1 adds Tempo readiness, the Tempo datasource
check, and a new trace-retrieval-from-Tempo step (see above); that
version was committed (`d14a1cb`) and ran successfully on GitHub
Actions (run `36724605466`). Phase 2B.2 further adds Loki/Alloy
readiness, the Loki datasource check, and the
real-logs-from-all-four-services step (see above), reusing
`scripts/verify-loki-logs.py`; that version was committed (`20170ea`)
and also ran successfully on GitHub Actions (run `36737863185`). Phase
2B.3's version of the workflow (adding the Grafana dashboard
verification step above) was committed (`1b22f55`) and initially
**failed** on GitHub Actions (run #19, `36763788179`): the dashboard
validator's original sparse-query logic only treated HTTP 5xx queries
as legitimately empty, not 4xx, and a CI run generating only successful
runtime requests genuinely has zero samples of either — the fix
(widening the sparse-ok pattern to `"[45].."`, see above) was committed
(`ce1ea6b`) and ran successfully on GitHub Actions (run #20,
`36765869383`). Phase 2B.4's version of the workflow (adding the
Alertmanager health/rules check and the alert lifecycle acceptance test
above) has been locally validated end-to-end by reproducing the
workflow's steps against the real Compose network (via `make
verify-observability`, which covers equivalent — and, additionally,
the full alert lifecycle — ground), but has **not yet run on GitHub
Actions** — that will only be true once it runs there after a push.

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

### Phase 2B.1 — Grafana Tempo as a persistent, queryable distributed-tracing backend

- Pulled and inspected the actual pinned `grafana/tempo:3.0.3` image
  before writing any config: `docker inspect` showed `ENTRYPOINT
  ["/tempo"]`, `USER 10001:10001`, no shell; `/tempo --help` confirmed
  `-config.file`, a built-in `-health` mode (GETs its own `/ready` and
  exits 0/1 — used for the Docker healthcheck, no curl/shell needed),
  and that `-target` defaults to `all` (monolithic mode, satisfying the
  requirement without needing to set it explicitly).
- New `observability/tempo/tempo.yaml`, built and corrected through
  real, concrete failures against the actual image rather than assumed
  from older Tempo documentation: a first attempt with top-level
  `ingester:`/`compactor:` keys (valid in older Tempo versions) was
  **rejected** by v3.0.3's parser (`field ingester not found in type
  app.Config` / `field compactor not found in type app.Config`) —
  real startup logs then showed v3.x replaced that architecture
  internally with `live-store`/`backend-scheduler`/`backend-worker`
  components, none of which need YAML config from us. The working
  config sets only `server.http_listen_port: 3200`,
  `distributor.receivers.otlp` (gRPC `:4317` + HTTP `:4318`), and
  `storage.trace` (`backend: local`, `local.path`/`wal.path` under
  `/var/tempo`). An explicit retention override
  (`backend_scheduler.provider...`) was attempted and failed twice
  against schema paths that don't match public documentation for this
  version; rather than keep guessing against an undocumented internal
  config surface, retention was left at Tempo's documented built-in
  default (336h/14 days — already appropriate for local dev), and this
  is reported here rather than silently worked around. No
  Kafka/MinIO/S3/distributed-Tempo config anywhere; confirmed via real
  startup logs that no Kafka connection is ever attempted.
- `docker-compose.yml`: new `tempo` service (`grafana/tempo:3.0.3`,
  `tempo_data` named volume at `/var/tempo`, config mounted read-only,
  only `127.0.0.1:3200:3200` published — Tempo's own OTLP receiver
  stays internal to the Compose network, reachable only as
  `tempo:4317`/`tempo:4318`), with a Docker healthcheck using the
  binary's own `-health` mode (`["CMD", "/tempo", "-health"]`) —
  confirmed working in the real stack (reports `healthy` immediately).
  Every existing service, volume, and port was left untouched.
- `observability/otel-collector/config.yaml`: the traces pipeline's
  exporter list changed from `[debug]` to `[debug, otlp_grpc/tempo]` —
  metrics pipeline completely unchanged, no new receivers/processors/
  pipelines. Hit and fixed a real deprecation warning during
  implementation: the Collector logged `"otlp" alias is deprecated;
  use "otlp_grpc" instead` for an exporter configured with type `otlp`;
  fixed by using the `otlp_grpc` type explicitly (`otlp_grpc/tempo`),
  confirmed via a clean restart that the warning is gone.
- `observability/grafana/provisioning/datasources/datasource.yml`:
  added a `Tempo` datasource (`type: tempo`, `url: http://tempo:3200`,
  `access: proxy`), Prometheus remains `isDefault: true`. Verified both
  via Grafana's authenticated `/api/datasources` endpoint.
- **Real trace retrieval — the primary goal of this phase — proven
  against Tempo's actual query API for a live `POST /checkouts`
  request, not assumed:** used the existing `scripts/parse-checkout-trace.py`
  to obtain a real Trace ID and all seven Span IDs from Collector logs,
  then queried `GET /api/v2/traces/{traceID}` directly. **Empirically
  discovered, not assumed:** the response wraps the standard OTLP-JSON
  `resourceSpans`/`scopeSpans`/`spans` structure under a top-level
  `"trace"` key, and — critically — `traceId`/`spanId`/`parentSpanId`
  are **base64-encoded**, not hex (confirmed by decoding
  `2N+0FGWNO919S+pRFh/wBA==` and getting back the exact known hex Trace
  ID). All seven spans (checkout SERVER, three CLIENT spans, and the
  three corresponding downstream SERVER spans) were found in the
  response with span/parent IDs exactly matching what
  `parse-checkout-trace.py` had already established from Collector
  logs, alongside 5 additional internal spans (ASGI/Fastify framework
  spans) that were correctly ignored. Independently repeated for a
  second, separate real checkout request after fixing the collector's
  `otlp_grpc` deprecation warning — same result, different real Trace
  ID and Span IDs, confirming this isn't a one-off.
- New `scripts/verify-tempo-trace.py`: a small, dependency-free
  (stdlib only — `argparse`/`base64`/`json`/`re`/`urllib`) deterministic
  validator. Takes `scripts/parse-checkout-trace.py`'s exact success
  line as input (no duplicated ID-extraction logic), fetches the trace
  from Tempo, decodes every base64 ID to hex, and independently
  re-verifies — not just presence, but Trace ID, span Kind
  (SERVER/CLIENT), resource `service.name`, and all six parent/child
  relationships — for all seven spans, ignoring any other spans in the
  response. Fails closed (nonzero exit, clear message) on an
  unreachable Tempo, a missing trace, a missing span, a wrong Kind, a
  wrong `service.name`, or a wrong parent/child relationship. Verified
  it also fails closed correctly against a deliberately-bogus all-zero
  trace ID (no false positive). The same script is used by both the
  local verifier and CI — no duplicated validation logic.
- **Persistence:** confirmed the `tempo_data` named volume exists and
  survives normal `docker compose down` (without `-v`), alongside the
  three pre-existing volumes. **Also went further and tested actual
  trace durability, not just volume existence, per the task's explicit
  distinction:** inspected the volume directly and found Tempo's
  live-store writes ingested spans to disk incrementally (parquet
  segment files under `/var/tempo/live-store/traces/...`), not purely
  in-memory; then gracefully restarted the `tempo` container (`docker
  compose restart tempo`, same volume) and confirmed the exact
  already-ingested trace — re-validated with `verify-tempo-trace.py`,
  all seven spans and six relationships intact — remained retrievable
  afterward, reproduced twice (once manually, once inside the automated
  verifier). **Honestly-reported limitation:** every trace tested here
  was already at least tens of seconds old (and, per the live-store
  behavior observed, already partially flushed to disk) by the time of
  its restart; the narrower race of a trace restarted within
  milliseconds of ingestion was not specifically stress-tested, so
  immediate-ingestion durability is not claimed — only durability for a
  trace that has had normal processing time, which is the realistic
  case this platform cares about.
- `scripts/verify-observability.sh` extended (not replaced): `tempo`
  added to the standard health-wait loop (it has a real Docker
  healthcheck, unlike otel-collector); the Grafana section gained a
  Tempo datasource check; two new sections retrieve/validate the real
  checkout trace from Tempo and prove restart persistence (both bounded
  retries, both safe under `set -euo pipefail`); the container/log
  sanity section now also dumps Tempo's logs and checks for
  **persistent** (not transient/expected-during-restart)
  Collector-to-Tempo export errors in the most recent log lines; the
  final persistence section now also checks `tempo_data`. Every prior
  Phase 2A.1-2A.5 assertion is unchanged. The full `make verify-observability`
  run passed end-to-end from a fully torn-down state, including every
  new Tempo check and the restart-persistence check, with a fresh,
  independent real Trace ID.
- `.github/workflows/ci.yml` extended, not duplicated: the existing
  Grafana datasource step also checks Tempo; a new "Wait for Tempo to
  become healthy" step mirrors the existing per-service pattern; the
  existing checkout-trace step now has an `id:` and writes its match
  line to `$GITHUB_OUTPUT` so the new "Verify checkout trace retrieval
  and validation from Tempo" step can reuse it directly (via
  `scripts/verify-tempo-trace.py`, the identical script used locally)
  without re-deriving it; log collection and teardown now include
  `tempo`. Kept the same safe `if cmd1 && cmd2; then` control-flow
  pattern throughout so an expected-to-fail early retry attempt cannot
  abort a step under GitHub Actions' default `bash -e`. Locally
  reproduced equivalent verification via `make verify-observability` —
  **not yet verified running on GitHub Actions in this updated form**
  (Phase 2A.5's version of the workflow did run successfully there, per
  commit `7e348a2`, CI run #16).
- **Limitation, honestly reported, not worked around:** Tempo's
  retention configuration could not be confirmed/overridden beyond its
  built-in default within this phase's scope (see above) — this is a
  config-schema-verification limitation, not a functional one; ingest,
  storage, and query all work correctly with the default. No
  dashboards were built against the new Tempo datasource (explicitly
  out of scope for this phase). No application log pipeline exists yet.
  Restart-persistence was proven for traces with normal (tens-of-
  seconds-plus) processing time before the restart, not for traces
  restarted within milliseconds of ingestion.

### Phase 2B.2 — Centralized application log collection with Grafana Loki + Grafana Alloy

- Pulled and inspected the actual pinned `grafana/loki:3.7.8` and
  `grafana/alloy:v1.20.1` images before writing any config. Loki has no
  shell, `cat`, `curl`, or `wget`, and no `-health`-style CLI flag
  (unlike Tempo) — its own bundled `local-config.yaml` was extracted via
  `docker create` + `docker cp` (not `cat`, which does not exist in the
  image) and confirmed to already default to the TSDB index with schema
  `v13`, rather than assuming it. Alloy has a shell but no `curl`/`wget`,
  and its own `alloy validate <path>` CLI subcommand was used to check
  the config syntactically against the real binary, separate from
  functional testing in the real stack.
- New `observability/loki/loki.yaml`: single-binary mode, single tenant,
  filesystem storage under `/loki` (`loki_data` named volume), TSDB
  index/schema v13 (image default, confirmed), `compactor`-driven 7-day
  retention (`limits_config.retention_period: 168h`). Accepted by the
  real binary on the first attempt, unlike Tempo's config in the prior
  phase (which needed two corrective iterations).
- New `observability/alloy/config.alloy`: pipeline `discovery.docker →
  discovery.relabel → loki.source.docker → loki.write`, collecting only
  `checkout-service`/`payment-service`/`inventory-service`/
  `notification-service` — confirmed via Loki's own
  `/loki/api/v1/label/service/values` API returning exactly those four
  names, never postgres/otel-collector/prometheus/tempo/grafana/loki/
  alloy's own logs. Labels: `service`, `compose_project`,
  `environment=local` — no `trace_id`/`span_id`/`request_id`/
  `container_id` is ever set as an indexed label (those may appear in
  log line content only). Observed but not configured by us:
  `loki.source.docker` auto-adds its own `service_name` label mirroring
  `service`.
- **Compose-project filter, corrected after initial review:** the
  first version hard-coded `regex = "autonomous-reliability-platform"`
  for the `com.docker.compose.project` match — functionally correct but
  would silently collect nothing (not leak into another project; the
  service-name filter still requires an exact match too, so this always
  failed closed) under a differently-named checkout directory. Replaced
  with `regex = sys.env("COMPOSE_PROJECT_NAME")`, with
  `docker-compose.yml` passing `COMPOSE_PROJECT_NAME` into the `alloy`
  container from Compose's own `${COMPOSE_PROJECT_NAME}` interpolation
  variable. Verified empirically (`docker compose config`, unrelated to
  Alloy) that this variable correctly resolves to Compose's actual
  effective project name under all three ways Compose can determine it
  — default directory-basename derivation, an explicit `-p <name>`
  flag, and an explicit `COMPOSE_PROJECT_NAME` environment variable —
  and re-validated the corrected config with `alloy validate` and a
  real running stack (Alloy's 4 pipeline components healthy, Loki's
  service-label list still exactly the 4 expected names). Since
  `discovery.relabel`'s `regex` is fully anchored (`^...$`, the same
  convention as Prometheus relabeling), this is always an exact label
  match, so it still cannot accidentally collect an unrelated Compose
  project's containers, even one that happens to use identical service
  names — and if `COMPOSE_PROJECT_NAME` were ever unset, `sys.env(...)`
  returns `""`, which matches no real label, so it still fails closed.
- **Startup-order race, investigated directly, none found:** with
  `alloy` stopped, `checkout-service` and `inventory-service` were
  restarted (each emitting its one-time startup log line while Alloy
  was down), then `alloy` was started **after** those lines were
  already written. Both lines — including `checkout-service`'s
  Spring Boot `Completed initialization` line and `inventory-service`'s
  `listening on 0.0.0.0:8082` line — were still retrieved from Loki
  afterward, with the exact Docker-side timestamps matching. This
  confirms Alloy's `loki.source.docker` reads each container's log
  history from Docker's own log driver, not just a live tail from the
  moment it attaches, so `checkout-service`/`inventory-service`
  starting before `alloy` (the normal case under `docker compose up
  -d`, which starts all services concurrently, in CI as well as
  locally) does not risk losing their startup logs. No code change was
  needed for this item; `scripts/verify-observability.sh` and CI
  already wait for Loki/Alloy readiness before the checkout regression
  request, but that ordering asserts a known-good state to check
  against, not because logs would otherwise be lost.
- `docker-compose.yml`: new `loki` service (`grafana/loki:3.7.8`,
  `loki_data` volume, config mounted read-only, only
  `127.0.0.1:3100:3100` published) and `alloy` service (`grafana/alloy:
  v1.20.1`, `alloy_data` volume, config mounted read-only, only
  `127.0.0.1:12345:12345` published — its debug HTTP listen address is
  overridden to `0.0.0.0:12345` inside the container, since the default
  `127.0.0.1:12345` is loopback *inside* the container's own network
  namespace and unreachable via Docker's host-port publishing).
  `alloy` also mounts `/var/run/docker.sock:ro` — see security note
  below — and receives `COMPOSE_PROJECT_NAME` per the filter fix above.
  Every existing service, volume, and port was left untouched.
- **Docker socket access — documented honestly, not glossed over:**
  the `:ro` on the socket mount only prevents Alloy from
  replacing/deleting the socket file itself; it does **not** restrict
  which Docker API calls Alloy can make through it — full daemon
  access, equivalent to root on the host running that daemon. The
  Docker API is never published on a host port. This same
  `docker-compose.yml` is also used by CI (`make db-up` → `docker
  compose up -d`), including on `pull_request` from forks, so this
  mount is active there too — not local-dev-only in practice, which an
  earlier version of this comment incorrectly implied and was
  corrected. Judged acceptable there specifically because it adds no
  privilege beyond what that CI job's own build/test steps already have
  (arbitrary PR-authored code already runs directly on the runner via
  `mvnw test`/`npm ci`/`go test`/`pip install -e`, with the runner's own
  unsandboxed Docker access) on a single-use, secret-free VM — not
  because the mount itself is restricted.
- `observability/grafana/provisioning/datasources/datasource.yml`:
  added a `Loki` datasource (`type: loki`, `url: http://loki:3100`,
  `access: proxy`); Prometheus remains `isDefault: true`, Tempo
  unchanged. Verified via Grafana's authenticated `/api/datasources`
  endpoint that all three datasources are present and correctly
  configured.
- **Real log retrieval — the primary goal of this phase — proven
  against Loki's actual query API for all four services, not assumed:**
  queried `GET /loki/api/v1/query_range` per service and confirmed
  genuine, distinct log content, not synthetic lines injected to pass
  the check: `checkout-service` (Spring Boot startup lines, e.g.
  `Completed initialization in 1 ms`), `payment-service` (Uvicorn
  access logs, e.g. `INFO: 127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200
  OK`), `inventory-service` (a single Go stdlib startup line,
  `inventory-service listening on 0.0.0.0:8082` — confirmed, via a wide
  query, that this service logs nothing else, ever, including nothing
  per request), and `notification-service` (structured pino JSON
  per-request logs with `reqId`/`statusCode`/`responseTime`).
  **Investigated and confirmed, not assumed: `checkout-service` and
  `inventory-service` currently have no per-request access logging at
  all** — re-triggering `POST /checkouts` produces no new log lines for
  either service, only for `payment-service`/`notification-service`.
- **Trace/log correlation — explicitly investigated, not claimed:**
  searched all four services' actual log content for `trace_id`/
  `traceId`/`span_id`/`spanId` fields. **None of the four services'
  current log output contains any of them.** Logs and traces are
  **not** correlated today; this is reported as a real gap and a
  candidate future enhancement, not worked around or silently assumed
  away, and no application logging code was modified to add it (out of
  this phase's scope).
- New `scripts/verify-loki-logs.py`: a small, dependency-free (stdlib
  only) validator with two modes — a default mode requiring, per
  service, a successful Loki response, at least one stream with the
  correct `service` label, at least one nonempty log entry, and an
  in-window timestamp; and a `--service SVC --expect-line TEXT`
  persistence-check mode for one specific previously-observed line.
  Fails closed on an unreachable Loki, malformed response, empty
  result, wrong label, or out-of-window timestamp. The same script is
  used by both the local verifier and CI — no duplicated validation
  logic.
- **Persistence — went beyond volume existence, per the same
  distinction established in Phase 2B.1:** captured a real,
  already-ingested log line (`inventory-service`'s one-time startup
  line, chosen because it is a stable, known-good fixture), stopped
  `alloy` so it could not resend anything, gracefully restarted `loki`
  (`docker compose restart loki`, same `loki_data` volume), waited for
  `/ready`, and — with `alloy` still stopped — confirmed the *exact
  same* entry (same nanosecond timestamp, same content) was still
  retrievable, ruling out "Alloy just resent it." Then restarted
  `alloy`, confirmed all 4 pipeline components became healthy again,
  triggered a fresh checkout, and confirmed `payment-service`/
  `notification-service` logs resumed flowing into Loki. Reproduced
  twice (once manually, once inside the automated verifier).
- `scripts/verify-observability.sh` extended (not replaced), sections
  A-O: `loki`/`alloy` config files added to the static-file check;
  new section D waits for Loki `/ready` and all 4 Alloy components
  healthy (no Docker-level healthcheck is possible for either image);
  the Grafana section gained a Loki datasource check; new section L
  verifies real logs from all four services via
  `scripts/verify-loki-logs.py`; new section M runs the full
  stop-Alloy/restart-Loki/verify-same-entry/restart-Alloy/verify-resumed
  sequence above; the container/log sanity section now also dumps
  `loki`/`alloy` logs and checks for persistent (non-transient)
  Alloy→Loki shipping errors; the final persistence section now also
  checks `loki_data` and `alloy_data`. Every prior Phase 2A.1-2B.1
  assertion is unchanged. The full `make verify-observability` run
  passed end-to-end from a fully torn-down state (sections A-O, zero
  failures), including every new Loki/Alloy check and the restart-
  persistence test, with a fresh, independent real Trace ID (Tempo) and
  fresh real log entries (Loki) both confirmed in the same run.
- `.github/workflows/ci.yml` extended, not duplicated: new "Wait for
  Loki to become ready" and "Wait for Alloy to become healthy" steps
  (mirroring the existing per-service health-wait pattern) placed
  before the checkout smoke test; the existing Grafana datasource step
  also checks Loki; a new "Verify real application logs reach Loki"
  step reuses `scripts/verify-loki-logs.py` (the identical script used
  locally); log collection and teardown now include `loki`/`alloy`. The
  more expensive Loki restart-persistence test remains local-only, per
  the same reasoning Phase 2B.1 applied to Tempo. Locally reproduced
  equivalent verification via `make verify-observability`, then
  committed (`20170ea`) and confirmed running successfully on GitHub
  Actions (run `36737863185`).
- **Limitations, honestly reported, not worked around:** `checkout-service`
  and `inventory-service` currently produce log output only at container
  startup — no per-request access logging exists in either today, so
  "real logs from all four services" means one thing for
  `payment-service`/`notification-service` (fresh per-request evidence
  on every run) and a different thing for `checkout-service`/
  `inventory-service` (evidence from container start, not from the
  specific request that triggered verification). No service's current
  log output contains a trace or span ID — logs and traces are not
  correlated, and this repository makes no claim otherwise. No
  dashboards were built against the new Loki datasource (explicitly out
  of scope for this phase). Docker-socket access for Alloy is real,
  full daemon access, active in both local dev and CI (including fork
  PRs) — acceptable under the current CI trust model (see above), but
  worth re-evaluating if that model ever changes.

### Phase 2B.3 — Grafana Dashboards

- **Inspected real telemetry before writing any dashboard, not
  assumed:** started the full stack, fired 15 real `POST /checkouts`
  requests plus one deliberately invalid one (to get a genuine `400`),
  then queried Prometheus's `/api/v1/label/__name__/values` and
  `/api/v1/query` directly. Confirmed the actual metric names in use —
  `http_server_request_duration_seconds_{bucket,count,sum}`,
  `http_client_request_duration_seconds_{bucket,count,sum}`,
  `http_server_active_requests`, `jvm_*`, `go_*`, `otelcol_*` — and
  their real labels (`service_name`, `http_route`,
  `http_request_method`, `http_response_status_code`, `server_address`
  for client calls). **Empirically discovered, not assumed:** the OTel
  Collector's own self-telemetry additionally exposes a *second*, oddly
  named set of metrics using raw dotted OTel semantic-convention names
  (`http.server.request.duration_count`, `rpc.client.call.duration_count`)
  with no `service_name` label at all — these turned out to be the
  Collector's own HTTP/gRPC server instrumenting itself
  (`job="otel-collector"`, `instance="otel-collector:8888"`), unrelated
  to the four application services, and were correctly excluded from
  the Application Health dashboard. Confirmed all four services share
  identical OTel SDK default histogram bucket boundaries (5ms–10s), so
  `histogram_quantile` p95 is directly comparable across services.
  Confirmed Loki's real labels (`service`, `compose_project`,
  `environment`, `service_name`) and, critically, that its automatic
  `detected_level` heuristic is **not** reliable across all four
  services (see the Centralized Logging dashboard entry below).
  Confirmed Tempo's `/api/search` and `/api/search/tags` work with the
  current config, but no dashboard panel ended up needing them (no
  traces panel was in scope for this phase).
- New `observability/grafana/provisioning/dashboards/dashboards.yml` +
  `observability/grafana/provisioning/dashboards/json/{application-health,centralized-logging,observability-infrastructure}.json`:
  three dashboards, detailed in
  [grafana dashboards (Phase 2B.3)](#grafana-dashboards-phase-2b3)
  above. `docker-compose.yml`'s `grafana` service gained a second,
  separate read-only mount for
  `observability/grafana/provisioning/dashboards`, added without
  touching or shadowing the existing `datasources` mount or any other
  Grafana provisioning subdirectory.
- **Real bug hit and fixed during implementation, not just noted:** the
  first version of `datasource.yml` pinned explicit `uid:` values so
  dashboards could reference stable datasource UIDs. This broke
  Grafana's own startup (`Datasource provisioning error: data source
  not found`, hard failure, container never becomes healthy) against
  this machine's existing `grafana_data` volume, which already had
  Prometheus/Tempo/Loki provisioned under earlier, auto-generated UIDs
  from Phase 2B.1/2B.2 — reproduced and confirmed via real container
  logs. Reverted the `uid:` pins and switched every dashboard panel/
  target to reference datasources by name (`"Prometheus"`/`"Loki"`)
  instead, then re-verified Grafana starts cleanly against the same
  already-populated volume and that all three dashboards still resolve
  their queries correctly.
- New `scripts/verify-grafana-dashboards.py`: stdlib-only, checks
  Grafana health, that all three dashboards exist and are
  `meta.provisioned` (not UI-created) with exactly their expected
  panels, that every panel's/target's datasource reference resolves to
  the expected datasource *and* that that datasource is really
  provisioned with the expected type (cross-checked against
  `GET /api/datasources`, not just trusted from the dashboard JSON),
  that expected template variables exist, reference the right
  datasource, and have a nonempty query definition, and that panel
  query text references metric/label substrings independently confirmed
  to be real. It then, for **every panel's own targets** (substituting
  each dashboard's real template-variable `allValue` and Grafana's
  built-in interval variables for concrete values), **re-executes those
  exact expressions directly against Prometheus's and Loki's own HTTP
  APIs**, bypassing Grafana's query proxy entirely — requiring real
  (nonempty) data for every target except ones its own expression text
  identifies as legitimately allowed to be empty (a `"[45].."`
  status-code match — 4xx **or** 5xx — or a `refused` metric name), and
  requiring each panel as a whole to have at least one such real result
  unless every one of its targets is of that legitimately-empty kind.
  Explicitly does not and cannot verify visual rendering in a browser.
  The same script is used by both the local verifier and CI — no
  duplicated validation logic.
- **Post-review correction #2 (GitHub Actions run #19):** CI failed
  because the original version of this script only treated 5xx queries
  as legitimately sparse, not 4xx — a CI run generating only successful
  runtime requests genuinely has zero 4xx samples too (the 400s visible
  elsewhere in CI logs come from `checkout-service`'s own unit tests,
  which never touch the running application's Prometheus telemetry).
  Fixed by widening the sparse-ok pattern to `"[45].."`, confirmed by
  reproducing the exact CI precondition locally (a stack with only
  successful checkout traffic) and re-running the validator.
- **Post-review corrections (same phase, before commit):** the
  Centralized Logging panel's title/description claimed "log lines/sec"
  while its query used `count_over_time()` (a raw count per window, not
  a rate) — corrected by switching the query itself to LogQL's `rate()`
  (verified empirically to return real fractional entries/sec values,
  not the earlier integer-like counts) and renaming the panel to "Log
  Line Rate by Service". The Observability Infrastructure ingestion
  panel's description claimed both refused spans *and* refused metric
  points were monitored, but only `otelcol_receiver_refused_spans` was
  actually queried — corrected by adding the missing
  `otelcol_receiver_refused_metric_points` query (confirmed to be a
  real, queryable metric) rather than narrowing the claim. The
  validator itself was then strengthened to catch this exact class of
  problem going forward: it now executes every panel's actual queries
  (see above) instead of a separately maintained "representative"
  query list, so a future description/query or query-list/panel
  mismatch would fail the check rather than go unnoticed.
- `scripts/verify-observability.sh` extended (not replaced), sections
  A–P: dashboard config files added to the static-file check; new
  section N runs `scripts/verify-grafana-dashboards.py` (bounded
  retries) after all telemetry-generating sections (checkout traffic,
  metrics, traces, logs) so its representative queries have real data
  to find. Every prior Phase 2A.1-2B.2 assertion is unchanged. The full
  `make verify-observability` run passed end-to-end from a fully
  torn-down state (sections A–P, zero failures), including every new
  dashboard check.
- `.github/workflows/ci.yml` extended, not duplicated: a new "Verify
  Grafana dashboards" step reuses `scripts/verify-grafana-dashboards.py`
  (the identical script used locally), placed after the existing
  checkout/metrics/trace/log steps so its queries have real data
  available, and before "Show service logs". Committed (`1b22f55`) and
  **initially failed** on GitHub Actions (run #19) for the real reason
  described in the Phase 2B.3 dashboard-verification correction above
  (4xx queries weren't treated as legitimately sparse); fixed
  (`ce1ea6b`) and confirmed passing (run #20).
- **Limitations, honestly reported, not worked around:** no severity/
  level filter on the Centralized Logging dashboard — Loki's
  `detected_level` heuristic was checked against real log output and
  found unreliable for inventory-service and notification-service (see
  above), so building one would have silently misrepresented half the
  services; this was investigated and deliberately rejected, not
  overlooked. No log/trace correlation — no service's current log
  output contains a trace or span ID, and this phase did not change any
  application logging code to add it. No alerting of any kind (no
  Grafana alert rules, no Prometheus Alertmanager) — explicitly out of
  scope for this phase, per its own instructions. No dedicated Tempo/
  traces dashboard panel — not part of this phase's explicit panel
  list, and adding one was judged unnecessary scope. `checkout-service`
  and `inventory-service` still only log at container startup, so their
  log-line-rate panel behavior (a brief spike, then nothing) is expected
  and correct, not a collection gap.

### Phase 2B.4 — Production-Style Alerting

- **Alertmanager version — determined empirically, not assumed:**
  pulled and ran `--version` against every `prom/alertmanager` tag from
  `v0.28.1` through `v0.34.1` in sequence, confirming `v0.35.0` and
  `v0.34.2` do not exist — `v0.34.1` (built 2026-09-17) is the genuine
  latest stable release, not a guess. `amtool`/`promtool` confirmed
  present and working in both pinned images before writing any config.
- New `observability/alertmanager/alertmanager.yml`: a simple
  `route`/`receiver` pair (`group_by: [alertname, severity]`,
  `group_wait: 10s`, `group_interval: 30s`, `repeat_interval: 1h`)
  routing to a single `local-null` receiver with **no integration
  configured on it at all** — a normal, fully valid Alertmanager
  receiver, not an invented notification service, confirmed
  empirically to still receive/group/track the full firing/resolved
  state of every alert through Alertmanager's own real API; it simply
  never sends anything anywhere. Validated with the real pinned image's
  own `amtool check-config` (not just YAML-parsed).
- `observability/prometheus/prometheus.yml` extended (not replaced):
  added `rule_files: [/etc/prometheus/rules/*.yml]` and
  `alerting.alertmanagers` pointed at `alertmanager:9093`; confirmed
  via Prometheus's own `GET /api/v1/alertmanagers` that it discovered
  exactly that one target. All existing scrape jobs untouched.
- New `observability/prometheus/rules/alerts.yml`: four alert rules
  (`TelemetryPipelineUnavailable`, `CheckoutServerErrors`,
  `CheckoutHighLatency`, `CollectorRefusingTelemetry` — full
  expressions/thresholds/`for:`/labels in
  [alert rules (Phase 2B.4)](#alert-rules-phase-2b4) above), every
  metric/label confirmed against a real running stack before being
  written in, not assumed. Validated with the real pinned Prometheus
  image's own `promtool check rules` (4 rules found, zero errors) and
  `promtool check config` (with the rules directory mounted the same
  way Compose mounts it).
- **Grafana Alertmanager datasource — genuinely functional, not just
  configured:** Grafana OSS 13.0.2 does support `type: alertmanager`
  with `jsonData.implementation: prometheus`; added to `datasource.yml`
  and proved working end-to-end via a real request through Grafana's
  own datasource proxy (`GET /api/datasources/proxy/uid/<uid>/api/v2/status`),
  which returned Alertmanager's real cluster status and version — not
  merely that the datasource entry exists. Confirmed the three existing
  dashboards and `scripts/verify-grafana-dashboards.py` are unaffected.
  No Grafana-managed alert rules were added; Prometheus remains the
  only rule evaluator.
- New `scripts/verify-alerting.py`: stdlib-only, five subcommands
  (`rules`, `health`, `state`, `firing`, `recovered`) against
  Prometheus's and Alertmanager's real HTTP APIs. `rules` confirms all
  four expected rules loaded with the correct normalized query
  fragments, `for:` duration, exact labels, and required annotations,
  and that every one starts `inactive`. `firing`/`recovered` each
  cross-check **both** systems — a rule `firing` in Prometheus with a
  matching active (non-resolved) alert in Alertmanager's own
  `GET /api/v2/alerts`, and the reverse for recovery — not just one
  system in isolation. Fails closed throughout.
- New `scripts/verify-alert-lifecycle.sh`: orchestrates the real
  controlled-failure sequence (shell owns Docker lifecycle operations;
  Python owns all HTTP API validation, no logic duplicated between
  them). Restores `otel-collector` via its own `EXIT` trap if any step
  fails partway through, so a failure never leaves the environment with
  the Collector stopped. **Run against the real stack, the full
  lifecycle was empirically observed, not merely asserted:**
  `TelemetryPipelineUnavailable` confirmed `inactive` → `otel-collector`
  stopped → the rule observed transitioning through `pending` (visible
  across several polling attempts, as expected given `for: 1m`) to
  `firing` in Prometheus, with Alertmanager independently confirming an
  active alert bearing `severity=critical component=otel-collector` →
  `otel-collector` restarted → Prometheus rule confirmed back to
  `inactive` and Alertmanager confirmed zero active matches remaining →
  a fresh real checkout confirmed `http_server_request_duration_seconds_count`
  for `/checkouts` genuinely incremented, proving telemetry resumed, not
  just that containers were running again.
- `scripts/verify-observability.sh` extended (not replaced), sections
  A–R: alerting config files added to the static-file check;
  `alertmanager` added to the standard health-wait loop (real Docker
  healthcheck); the Grafana section gained an Alertmanager datasource
  check; new section O verifies Alertmanager health and all four rules
  loaded/inactive; new section P runs the full lifecycle acceptance
  test and then explicitly re-confirms both Collector scrape targets
  are back `UP`, deliberately placed after every other telemetry/
  dashboard check so the controlled failure can't invalidate them; the
  container/log sanity section now also dumps Alertmanager's logs; the
  final persistence section now also checks `alertmanager_data`, using
  the same dynamic Compose-project-name resolution already in place
  (no hard-coded project prefix). Every prior Phase 2A.1-2B.3 assertion
  is unchanged. The full `make verify-observability` run passed
  end-to-end from a fully torn-down state (sections A–R, zero
  failures), including the complete alert lifecycle test.
- `.github/workflows/ci.yml` extended, not duplicated: a new "Wait for
  Alertmanager to become healthy" step mirrors the existing per-service
  pattern; a new "Verify Alertmanager health and alert rules loaded"
  step reuses `scripts/verify-alerting.py`; a new "Run alert lifecycle
  acceptance test" step runs the identical
  `scripts/verify-alert-lifecycle.sh` used locally — no lifecycle logic
  duplicated in the workflow YAML; Alertmanager logs added to the
  existing "Show service logs" failure-diagnostics step. Locally
  reproduced equivalent verification via `make verify-observability` —
  not yet verified running on GitHub Actions in this updated form.
- **Volumes:** new `alertmanager_data` named volume, confirmed to
  survive a normal `docker compose down` (without `-v`) via the same
  label-based dynamic resolution (`com.docker.compose.project`/
  `com.docker.compose.volume`) already used for every other volume —
  no hard-coded `autonomous-reliability-platform_*` prefix, so this
  continues to work under an alternate `COMPOSE_PROJECT_NAME`. No
  silence was manufactured or persisted solely to claim Alertmanager
  state durability; only the named volume's survival was verified, per
  this phase's own instructions.
- **Corrected stale Phase 2B.3 documentation** found while writing this
  phase's docs: two spots still claimed only HTTP 5xx dashboard queries
  may legitimately be empty, when both 4xx and 5xx can be (the real
  CI-run-#19 fix, see above) — corrected in place rather than left
  inconsistent with the actual validator behavior.
- **Limitations, honestly reported, not worked around:** no outbound
  notification integration of any kind (email, Slack, PagerDuty,
  webhook) — Alertmanager's only receiver is a no-op local sink, by
  this phase's explicit design, not an oversight. No control plane
  exists yet to consume these incident signals; a future one can
  without changing this routing structure. No automatic remediation.
  `CheckoutServerErrors` and `CheckoutHighLatency` were not exercised
  firing during this phase's verification — doing so would require
  artificially degrading business logic or injecting latency, both
  explicitly out of scope — so only `TelemetryPipelineUnavailable`'s
  full lifecycle has been empirically proven; the other three rules are
  confirmed loaded, correctly labeled, syntactically valid per
  `promtool`, and initially `inactive`, but not proven to fire
  end-to-end. No AI agent and no Kubernetes/Terraform/AWS/Kafka/Redis
  were added, per this phase's explicit scope.
