# System Overview

This document describes the architecture of the Autonomous Production
Reliability Platform. It is split into two sections: what actually exists
today, and what is planned for future phases. Nothing in the "planned"
section has been implemented.

## Current Implementation

As of Phase 0.2, the repository contains foundational scaffolding plus a
single running infrastructure dependency:

- Repository-level documentation (`README.md`, this document, ADR records)
- Standard configuration files (`.gitignore`, `.editorconfig`, `.env.example`)
- A local environment-check script (`scripts/check-env.sh`)
- **PostgreSQL 18**, run locally via Docker Compose (`docker-compose.yml`),
  configured entirely through environment variables, with a named Docker
  volume for persistent storage and a healthcheck based on `pg_isready`.
  This is the first piece of the planned "durable state" component below
  to actually exist; it currently has no schema, migrations, or
  application connecting to it.

There is no application code, no other services, no message brokers, no
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
distributed system to investigate rather than a synthetic one.

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
