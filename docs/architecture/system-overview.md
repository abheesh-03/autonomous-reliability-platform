# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

As of Phase 1A.2, the repository contains foundational scaffolding, a
running infrastructure dependency, and two application service
bootstraps. Conceptually, the current demo application shape is:

```
Client
  |
  +--> checkout-service :8080
  |
  +--> payment-service :8081
```

Both boxes are standalone health-only bootstraps today — there is no
arrow between them yet, and neither talks to PostgreSQL, which exists
alongside them as a separate, currently-unused infrastructure dependency.

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
  - Automated tests (health endpoint test via FastAPI's `TestClient`)
  - A single-stage Dockerfile producing a runnable, non-root container image
  - Docker Compose integration with its own healthcheck

  **Not implemented in this service:**
  - Any actual payment processing or business logic
  - Checkout integration
  - Inventory integration
  - Database access of any kind
  - Telemetry / observability
  - Communication with any other service
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
distributed system to investigate rather than a synthetic one. Two
services, `checkout-service` and `payment-service`, now exist as
bootstraps (see Current Implementation above); neither has business
logic yet, they do not call each other, and an inventory service does
not exist.

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
