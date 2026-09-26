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
**Phase 1A.1 — Checkout Service Bootstrap**. This is the first application
service; it has no checkout, payment, or inventory logic yet, and no AI
functionality exists.

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
- Observability via OpenTelemetry, Prometheus, and Grafana
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
PostgreSQL database run via Docker Compose, and the first application
service bootstrap: `checkout-service` (Java / Spring Boot). It currently
only exposes health endpoints — it has no checkout, payment, or inventory
logic and does not connect to PostgreSQL. No AI integration has been
added yet.

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
Spring Boot 3 project built with Maven. At this stage it is a bootstrap
only — it exposes health endpoints and nothing else. It does not
implement checkout logic, does not talk to any other service, and does
not connect to PostgreSQL.

Endpoints:

- `GET /health` — a small typed JSON response: `{"status": "UP", "service": "checkout-service"}`
- `GET /actuator/health` — Spring Boot Actuator's own health endpoint (only `health` is exposed)

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

**Run it through Docker Compose**, alongside PostgreSQL:

```bash
make db-up
curl http://localhost:8080/health
curl http://localhost:8080/actuator/health
make checkout-logs
make db-down
```

## Continuous Integration

A GitHub Actions workflow (`.github/workflows/ci.yml`) has been added. It
runs on pushes and pull requests targeting `main`, and can also be
triggered manually (`workflow_dispatch`). Using `contents: read`
permissions only, it validates: shell script syntax, that the Makefile is
usable, that `checkout-service` builds and its tests pass (on a real Java
21 toolchain via `actions/setup-java`), that Docker Compose config
resolves, that PostgreSQL and `checkout-service` both start and reach a
healthy state (bounded retry loops, not assumed), a basic SQL smoke test,
and an HTTP smoke test against `checkout-service`'s `/health` and
`/actuator/health` endpoints — then always tears the environment down
(without deleting volumes).

The repository has a GitHub remote
(`abheesh-03/autonomous-reliability-platform`), and the pre-checkout-service
version of this workflow has previously been verified running
successfully on a GitHub-hosted runner. The updated workflow (with the
`checkout-service` build/test/smoke-test steps added in this phase) has
been locally validated by reproducing its steps, but has not yet run on
GitHub Actions — that will only be true once it runs there after a push.

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
- Verified: the CI workflow executed successfully on GitHub Actions after
  the repository was pushed to `main` on GitHub. (This was verified for
  the pre-`checkout-service` version of the workflow; the updated
  workflow has only been locally reproduced so far — see below.)
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
  health-check + HTTP smoke test for it. Locally reproduced the full
  updated CI path end-to-end (config validation, both services healthy,
  both smoke tests, logs, cleanup) — **not yet verified running on
  GitHub Actions itself.**
