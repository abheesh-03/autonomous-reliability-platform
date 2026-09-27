# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

As of Phase 1B.3, the repository contains foundational scaffolding, a
running infrastructure dependency, and four application service
bootstraps. Conceptually, the current demo application shape is:

```
Client
  |
  +--> checkout-service      :8080
  |
  +--> payment-service       :8081  (POST /payments/authorize — simulated)
  |
  +--> inventory-service     :8082  (POST /inventory/reservations — simulated)
  |
  +--> notification-service  :8083  (POST /notifications — simulated)
```

`checkout-service` remains a standalone health-only bootstrap.
`payment-service`, `inventory-service`, and `notification-service` each
additionally have one simulated business endpoint (see below). There
are still no arrows between the application services, and none of them
talks to PostgreSQL, which exists alongside them as a separate,
currently-unused infrastructure dependency.

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
  target system" below to actually exist. It runs through the same Docker
  Compose environment as PostgreSQL, but does not connect to it.

  **Implemented in this service:**
  - Application bootstrap (`CheckoutServiceApplication`)
  - `GET /health` — a small typed JSON health response
  - `GET /actuator/health` — Spring Boot Actuator health (only `health`
    is exposed)
  - Automated tests (application context load + health endpoint test)
  - A multi-stage Dockerfile producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck

  **Not implemented in this service:**
  - Any actual checkout workflow or business logic
  - Payment integration
  - Inventory integration
  - Database access of any kind
  - Telemetry / observability
  - Communication with any other service
  - Agent functionality of any kind

- **`payment-service`** (`services/payment-service`), a Python 3.13 /
  FastAPI project (`src`-layout, `pyproject.toml`) — the second piece of
  the planned "demonstration target system" below to actually exist. It
  runs through the same Docker Compose environment as PostgreSQL and
  `checkout-service`, but does not connect to or communicate with either.

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
  - Checkout integration (Checkout Service does not call this endpoint yet)
  - Inventory integration
  - Database access or payment history of any kind
  - Telemetry / observability
  - Communication with any other service
  - Agent functionality of any kind

- **`inventory-service`** (`services/inventory-service`), a Go 1.27
  project using only the standard library — the third piece of the
  planned "demonstration target system" below to actually exist. It runs
  through the same Docker Compose environment as PostgreSQL,
  `checkout-service`, and `payment-service`, but does not connect to or
  communicate with any of them.

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
  - Checkout integration (Checkout Service does not call this endpoint yet)
  - Payment integration
  - Database access of any kind
  - Telemetry / observability
  - Communication with any other service
  - Agent functionality of any kind

- **`notification-service`** (`services/notification-service`), a
  Node.js 24 / TypeScript (strict) / Fastify project using npm — the
  fourth piece of the planned "demonstration target system" below to
  actually exist. It runs through the same Docker Compose environment as
  PostgreSQL, `checkout-service`, `payment-service`, and
  `inventory-service`, but does not connect to or communicate with any
  of them.

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
  - Checkout integration (Checkout Service does not call this endpoint yet)
  - Payment integration
  - Inventory integration
  - Database access of any kind
  - Telemetry / observability
  - Agent functionality of any kind

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
and `notification-service` — now exist as bootstraps (see Current
Implementation above); `payment-service`, `inventory-service`, and
`notification-service` each have one simulated business endpoint,
`checkout-service` remains health-only, and they do not call each
other.

### Observability
- **OpenTelemetry** for traces, metrics, and logs emitted by the demo
  services and platform components.
- **Prometheus** for metrics storage and alerting.
- **Grafana** for dashboards.

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
