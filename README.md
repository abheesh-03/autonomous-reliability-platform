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
**Phase 2A.1 — Observability Infrastructure Bootstrap**. An OpenTelemetry
Collector, Prometheus, and Grafana now run via Docker Compose, but
**no application service is instrumented yet** — none sends telemetry
to the Collector or exposes a metrics endpoint. `checkout-service`
still synchronously orchestrates `payment-service`, `inventory-service`,
and `notification-service` via `POST /checkouts` (Phase 1B.4); none of
the four application services connect to PostgreSQL. No AI functionality
exists.

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
- Application-level observability: metrics/traces/logs emitted by the
  demo services, distributed trace correlation, dashboards, and alerts
  (the OTel Collector / Prometheus / Grafana infrastructure itself now
  exists — see [Observability Infrastructure](#observability-infrastructure) below — but no
  application service is instrumented yet)
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
Grafana — now also runs via Docker Compose (see
[Observability Infrastructure](#observability-infrastructure) below).
**No application service sends it any telemetry yet** — none has an
OpenTelemetry SDK, none exposes a metrics endpoint, and none has been
modified in any way for this. The stack currently only proves its own
internal path is alive (Prometheus scraping itself and the Collector's
self-telemetry, with Grafana able to query Prometheus). No AI
integration has been added yet.

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

## Observability Infrastructure

`observability/` contains configuration for a local OpenTelemetry
Collector, Prometheus, and Grafana, all running via Docker Compose. This
is **infrastructure only** — it is not yet fed by any application
service. No application has an OpenTelemetry SDK, sends OTLP telemetry,
or exposes a metrics endpoint; none was modified in any way for this
phase.

```
(future) app services --OTLP--> otel-collector --Prometheus format--> prometheus --> grafana
```

Today, only the Collector's own internal ("self") telemetry flows
through this path — that's what proves it's alive end-to-end before any
application is instrumented:

- **`otel-collector`** (`otel/opentelemetry-collector-contrib`) — an OTLP
  receiver (gRPC `:4317`, HTTP `:4318`) → `batch` processor → Prometheus
  exporter (`:8889`) pipeline, ready for future application telemetry
  but empty today. Its own internal metrics are exposed separately on
  `:8888`. A `health_check` extension is exposed on `:13133`, but it
  does **not** back a Docker Compose healthcheck: the official Contrib
  image is a single static binary with no shell, `wget`, or `curl`, so
  no `healthcheck:` block can be defined for it without modifying the
  image. This is an intentional exception — `docker compose ps` shows it
  as `running` with no health status, and its liveness is instead
  verified functionally: a direct request to `:13133/` succeeds, and
  more meaningfully, Prometheus reports its scrape target as `up`.
- **`prometheus`** — scrapes itself, the Collector's self-telemetry
  (`:8888`), and the (currently empty) Collector telemetry-relay
  endpoint (`:8889`), on a persistent named volume.
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

**Run it through Docker Compose**, alongside the four application services and PostgreSQL:

```bash
make db-up
curl http://127.0.0.1:9090/-/ready               # Prometheus
curl http://127.0.0.1:9090/api/v1/targets        # scrape targets, including otel-collector
curl http://127.0.0.1:3000/api/health            # Grafana
make db-down
```

**Bundled verification:** `make verify-observability` (or
`scripts/verify-observability.sh`) runs the full Phase 2A.1 verification
path in one deterministic script — starts Compose, waits for every
service's health (with the `otel-collector` exception above),
checks Prometheus targets and the Grafana datasource, re-runs the
`POST /checkouts` regression check, then always tears the environment
down (without deleting volumes) and confirms the three named volumes
still exist.

**Not implemented in this phase:** any application-level metrics, traces,
or logs; distributed trace correlation; dashboards beyond the minimal
datasource-connectivity check; alerting rules; and any consumption of
telemetry by an agent. Those are deliberately deferred to later phases.

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
response over the actual Compose network, and — new in this phase —
that Prometheus and Grafana reach a healthy state, that Prometheus
reports both itself and the `otel-collector` scrape target as `up`
(bounded retry loop, since Prometheus needs a scrape cycle after
startup), and that Grafana's health API and provisioned Prometheus
datasource are reachable — then always tears the environment down
(without deleting volumes).

The repository has a GitHub remote
(`abheesh-03/autonomous-reliability-platform`). The workflow version
covering repository baseline checks, all four application services
(Java + Python + Go + Node setup, build/test, Compose, PostgreSQL, and
all four services' health/smoke tests), and the `POST /checkouts`
end-to-end orchestration smoke test has been verified running
successfully on a GitHub-hosted runner (CI run `36350946497`, for commit
`1ef34e6`). The workflow has since been updated further with this
phase's observability steps (Prometheus/Grafana health waits, scrape-
target verification, and datasource check) and has been locally
validated end-to-end by reproducing its steps against the real Compose
network, but has **not yet run on GitHub Actions in this updated
form** — that will only be true once it runs there after a push.

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
  and Grafana, a bounded-retry check that Prometheus reports itself and
  the `otel-collector` target as `up` (necessary since Prometheus needs
  a scrape cycle after startup), and a Grafana health/datasource check —
  every exact `jq` expression added was tested against real captured
  responses before being added. Locally reproduced the full updated CI
  path end-to-end — **not yet verified running on GitHub Actions in
  this updated form.**
