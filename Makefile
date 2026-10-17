.PHONY: help check compose-config db-up db-down db-status db-logs db-restart db-migrate checkout-build checkout-test checkout-logs payment-build payment-test payment-logs inventory-build inventory-test inventory-logs notification-build notification-test notification-logs otel-logs prometheus-logs grafana-logs control-plane-build control-plane-test control-plane-logs investigator-build investigator-test investigator-logs retrieval-build retrieval-test retrieval-logs rag-index verify-rag rag-search verify-observability verify-persistence verify-control-plane webhook-secret-init verify-webhook-ingestion verify-alert-ingestion verify-incident-lifecycle verify-incident-audit simulate-payment-outage simulate-inventory-outage test-failure-simulation test-failure-simulation-settling verify-failure-simulation verify-investigator test-verify-investigator-restore investigate agent-runtime-build agent-runtime-test agent-runtime-logs verify-agent-runtime test-db-up-order test-init-agent-runtime-db-fresh tool-gateway-build tool-gateway-test tool-gateway-logs remediation-secret-init verify-remediation test-remediation-cleanup-resilience remediation-approve remediation-reject

help: ## Show available targets
	@echo "Available targets:"
	@echo "  help                Show this help"
	@echo "  check               Verify local developer prerequisites"
	@echo "  compose-config      Validate docker-compose.yml"
	@echo "  db-up               Start the Compose environment (docker compose up -d)"
	@echo "  db-down             Stop the Compose environment, preserving the data volume"
	@echo "  db-status           Show container status"
	@echo "  db-logs             Show recent PostgreSQL logs"
	@echo "  db-restart          Restart PostgreSQL without removing data"
	@echo "  db-migrate          Apply versioned database migrations (Flyway; safe to rerun)"
	@echo "  checkout-build      Build the checkout-service Docker image"
	@echo "  checkout-test       Run checkout-service tests locally (requires Java 21)"
	@echo "  checkout-logs       Show recent checkout-service logs"
	@echo "  payment-build       Build the payment-service Docker image"
	@echo "  payment-test        Run payment-service tests on Python 3.13 (via Docker)"
	@echo "  payment-logs        Show recent payment-service logs"
	@echo "  inventory-build     Build the inventory-service Docker image"
	@echo "  inventory-test      Run inventory-service gofmt/vet/test on Go 1.27 (via Docker)"
	@echo "  inventory-logs      Show recent inventory-service logs"
	@echo "  notification-build  Build the notification-service Docker image"
	@echo "  notification-test   Run notification-service typecheck/test/build on Node 24 (via Docker)"
	@echo "  notification-logs   Show recent notification-service logs"
	@echo "  otel-logs           Show recent otel-collector logs"
	@echo "  prometheus-logs     Show recent Prometheus logs"
	@echo "  grafana-logs        Show recent Grafana logs"
	@echo "  control-plane-build Build the control-plane Docker image"
	@echo "  control-plane-test  Run control-plane unit tests on Python 3.13 (via Docker)"
	@echo "  control-plane-logs  Show recent control-plane logs"
	@echo "  investigator-build  Build the investigator-service Docker image"
	@echo "  investigator-test   Run investigator-service unit tests on Python 3.13 (via Docker)"
	@echo "  investigator-logs   Show recent investigator-service logs"
	@echo "  retrieval-build     Build the retrieval-service Docker image"
	@echo "  retrieval-test      Run retrieval-service unit tests on Python 3.13 (via Docker)"
	@echo "  retrieval-logs      Show recent retrieval-service logs"
	@echo "  rag-index           Phase 6: index source-controlled knowledge + current historical incidents (idempotent)"
	@echo "  verify-rag          Phase 6 real-evidence acceptance: pgvector schema, indexing, search, RAG-integrated investigation, no mutation"
	@echo "  rag-search          Phase 6: search the retrieval index: make rag-search QUERY=\"checkout payment failures\""
	@echo "  verify-observability Bundled Phase 2A.1-2B.4 verification (starts Compose, checks everything, tears down)"
	@echo "  verify-persistence  Phase 3A persistence verification (migrations, schema, constraints, restart persistence)"
	@echo "  verify-control-plane Phase 3B control-plane integration verification (real PostgreSQL, real HTTP API)"
	@echo "  webhook-secret-init  Generate/reuse the local webhook + lifecycle Bearer tokens"
	@echo "  verify-webhook-ingestion Phase 3C/3D focused webhook ingestion verification (auth, dedup/upsert, resolution, real PostgreSQL)"
	@echo "  verify-alert-ingestion Phase 3C/3D full acceptance: real Collector outage -> Alertmanager webhook -> persisted + resolved incident"
	@echo "  verify-incident-lifecycle Phase 3D real PostgreSQL lifecycle verification (state machine, concurrency, restart durability)"
	@echo "  verify-incident-audit Phase 3E real PostgreSQL audit trail verification (attribution, atomicity, concurrency, append-only enforcement)"
	@echo "  simulate-payment-outage Phase 4: deliberately stop payment-service, verify safe 502 + recovery (add FULL_ACCEPTANCE=true for the full alert/incident/audit chain)"
	@echo "  simulate-inventory-outage Phase 4: deliberately stop inventory-service, verify safe 502 + short-circuit + recovery"
	@echo "  test-failure-simulation Phase 4 focused tests: scenario selection, safety checks, restoration behavior (no Docker required)"
	@echo "  test-failure-simulation-settling Phase 4 focused test: the CheckoutServerErrors settling gate added after inventory-outage (no Docker required)"
	@echo "  verify-failure-simulation Phase 4 full acceptance: payment-outage (full alert/incident/audit chain) + inventory-outage, against the real stack"
	@echo "  verify-investigator Phase 5 real-evidence acceptance: investigate a real persisted incident, verify no mutation"
	@echo "  test-verify-investigator-restore Phase 5 focused tests: provider-restoration logic on_exit (no Docker required)"
	@echo "  investigate         Request a real investigation: make investigate INCIDENT_ID=<existing incident UUID>"
	@echo "  agent-runtime-build Build the agent-runtime-service Docker image"
	@echo "  agent-runtime-test  Run agent-runtime-service unit tests on Python 3.13 (via Docker)"
	@echo "  agent-runtime-logs  Show recent agent-runtime-service logs"
	@echo "  verify-agent-runtime Phase 7 real-evidence acceptance: durable LangGraph agent runs, dedicated DB role isolation, restart persistence, no mutation"
	@echo "  test-db-up-order    Phase 7 focused test: db-up's recipe provisions the checkpoint DB credential before agent-runtime-service is created (no Docker required)"
	@echo "  test-init-agent-runtime-db-fresh Phase 7 regression test: init-agent-runtime-db.sh succeeds on a genuinely fresh database (no reliability schema yet), against a real isolated/temporary PostgreSQL"
	@echo "  tool-gateway-build  Build the tool-gateway Docker image"
	@echo "  tool-gateway-test   Run tool-gateway gofmt/vet/test/build on Go 1.27 (via Docker)"
	@echo "  tool-gateway-logs   Show recent tool-gateway logs"
	@echo "  remediation-secret-init Generate/verify the six Phase 8 remediation Bearer tokens in .env (idempotent)"
	@echo "  verify-remediation  Phase 8 real-evidence acceptance: human-approved remediation, tool-gateway execution, real recovery"
	@echo "  test-remediation-cleanup-resilience  Phase 8 correction-round focused test: EXIT cleanup tolerates a simulated payment_fault_get failure (no Docker required)"
	@echo "  remediation-approve Approve a pending remediation proposal: make remediation-approve PROPOSAL_ID=<uuid> [COMMENT=\"...\"]"
	@echo "  remediation-reject  Reject a pending remediation proposal: make remediation-reject PROPOSAL_ID=<uuid> [COMMENT=\"...\"]"

check: ## Verify local developer prerequisites
	./scripts/check-env.sh

compose-config: ## Validate docker-compose.yml
	docker compose config

# Phase 7 correction round (finding #1): agent-runtime-service's real
# checkpoint-database credential (AGENT_RUNTIME_DB_PASSWORD) MUST exist
# in .env BEFORE Docker Compose ever CREATES that container -- Compose
# resolves a service's `environment:` at container-creation time, and
# rewriting .env afterward does NOT change an already-created
# container's environment (it would require recreating it). The
# previous ordering (full `docker compose up -d` THEN
# init-agent-runtime-db.sh) created agent-runtime-service with
# whatever (possibly empty/stale) password happened to already be in
# .env, which fails its startup outright on a fresh checkout (see
# docker-compose.yml's own comment on agent-runtime-service for why
# this fails fast rather than degrading gracefully). Corrected order:
#   1. webhook/lifecycle secrets (host-file-only, no container involved)
#   2. bring up ONLY postgres (the one real dependency
#      init-agent-runtime-db.sh itself needs)
#   3. provision the real agent_runtime role/password into .env
#      (idempotent; this script's own bounded pg_isready loop is a
#      belt-and-suspenders backstop, not the primary readiness
#      mechanism -- step 2's `docker compose up -d postgres` already
#      waits for Compose to report the container created, and the
#      script polls pg_isready itself before running real SQL)
#   4. bring up the REST of the stack -- by this point .env already
#      has the real password, so agent-runtime-service is CREATED with
#      it from the start
# See scripts/test-db-up-order.sh for a static (no-Docker) regression
# test proving this exact ordering in this target.
db-up: ## Start the Compose environment (docker compose up -d)
	./scripts/init-webhook-secret.sh
	./scripts/init-remediation-secrets.sh
	docker compose up -d postgres
	./scripts/init-agent-runtime-db.sh
	docker compose up -d
	@echo "Compose environment started. Run 'make db-status' to check health before using it."

db-down: ## Stop PostgreSQL, preserving the named data volume
	docker compose down

db-status: ## Show PostgreSQL container status
	docker compose ps

db-logs: ## Show recent PostgreSQL logs
	docker compose logs --tail=100 postgres

db-restart: ## Restart PostgreSQL without removing data
	docker compose restart postgres

# Flyway (pinned flyway/flyway:13.9.0, see docker-compose.yml's
# "flyway" service) applies database/migrations/ to the "reliability"
# schema only — never "public". Requires PostgreSQL already running
# (`make db-up`) and healthy. Safe to run repeatedly: Flyway tracks
# applied versions itself and no-ops once up to date.
db-migrate: ## Apply versioned database migrations (Flyway; safe to rerun)
	docker compose run --rm flyway migrate

checkout-build: ## Build the checkout-service Docker image
	docker compose build checkout-service

checkout-test: ## Run checkout-service tests locally (requires Java 21)
	cd services/checkout-service && ./mvnw test

checkout-logs: ## Show recent checkout-service logs
	docker compose logs --tail=100 checkout-service

payment-build: ## Build the payment-service Docker image
	docker compose build payment-service

# Host Python versions vary (this repo targets 3.13); running tests
# inside a python:3.13-slim container keeps results reproducible and
# consistent with CI regardless of the developer's local Python version.
payment-test: ## Run payment-service tests on Python 3.13 (via Docker)
	docker run --rm -v "$(CURDIR)/services/payment-service:/app" -w /app python:3.13-slim \
		bash -c "pip install -q -e '.[dev]' && pytest"

payment-logs: ## Show recent payment-service logs
	docker compose logs --tail=100 payment-service

inventory-build: ## Build the inventory-service Docker image
	docker compose build inventory-service

# Go isn't installed locally for this repo; running gofmt/vet/test
# inside golang:1.27 keeps results reproducible and consistent with CI
# regardless of whether (or which) Go is on the developer's machine.
inventory-test: ## Run inventory-service gofmt/vet/test on Go 1.27 (via Docker)
	docker run --rm -v "$(CURDIR)/services/inventory-service:/build" -w /build golang:1.27 \
		bash -c 'test -z "$$(gofmt -l .)" && go vet ./... && go test ./...'

inventory-logs: ## Show recent inventory-service logs
	docker compose logs --tail=100 inventory-service

notification-build: ## Build the notification-service Docker image
	docker compose build notification-service

# Host Node differs from this repo's Node 24 target; running npm
# ci/typecheck/test/build inside node:24 keeps results reproducible and
# consistent with CI regardless of the developer's local Node version.
notification-test: ## Run notification-service typecheck/test/build on Node 24 (via Docker)
	docker run --rm -v "$(CURDIR)/services/notification-service:/app" -w /app node:24 \
		bash -c "npm ci && npm run typecheck && npm test && npm run build"

notification-logs: ## Show recent notification-service logs
	docker compose logs --tail=100 notification-service

otel-logs: ## Show recent otel-collector logs
	docker compose logs --tail=100 otel-collector

prometheus-logs: ## Show recent Prometheus logs
	docker compose logs --tail=100 prometheus

grafana-logs: ## Show recent Grafana logs
	docker compose logs --tail=100 grafana

control-plane-build: ## Build the control-plane Docker image
	docker compose build control-plane

# Host Python versions vary (this repo targets 3.13); running tests
# inside a python:3.13-slim container keeps results reproducible and
# consistent with CI regardless of the developer's local Python
# version — same convention as payment-test. These are unit tests only
# (fake repository, no real database, see services/control-plane/tests/
# conftest.py); run `make verify-control-plane` for the real
# PostgreSQL-backed integration check.
control-plane-test: ## Run control-plane unit tests on Python 3.13 (via Docker)
	docker run --rm -v "$(CURDIR)/services/control-plane:/app" -w /app python:3.13-slim \
		bash -c "pip install -q -e '.[dev]' && pytest"

control-plane-logs: ## Show recent control-plane logs
	docker compose logs --tail=100 control-plane

investigator-build: ## Build the investigator-service Docker image
	docker compose build investigator-service

# Same convention as control-plane-test: unit tests only, against
# fake/stub doubles (httpx.MockTransport, FakeControlPlane/StubProvider
# — see services/investigator-service/tests/conftest.py), never a real
# network call and never a real, paid LLM API call. Run
# `make verify-investigator` for the real, running-stack integration
# check.
investigator-test: ## Run investigator-service unit tests on Python 3.13 (via Docker)
	docker run --rm -v "$(CURDIR)/services/investigator-service:/app" -w /app python:3.13-slim \
		bash -c "pip install -q -e '.[dev]' && pytest"

investigator-logs: ## Show recent investigator-service logs
	docker compose logs --tail=100 investigator-service

retrieval-build: ## Build the retrieval-service Docker image
	docker compose build retrieval-service

# Same convention as investigator-test: unit tests only, against
# fake/stub doubles (httpx.MockTransport, monkeypatched db.py
# functions, the deterministic LocalLexicalEmbeddingProvider -- see
# services/retrieval-service/tests/), never a real database connection
# and never a real, paid embedding API call. The second mount makes
# the REAL source-controlled knowledge/runbooks/ corpus available at
# /knowledge for the deterministic retrieval-quality smoke test
# (Phase 6 §18) -- a read-only mount, never written to by tests. Run
# `make verify-rag` for the real, running-stack integration check.
retrieval-test: ## Run retrieval-service unit tests on Python 3.13 (via Docker)
	docker run --rm \
		-v "$(CURDIR)/services/retrieval-service:/app" \
		-v "$(CURDIR)/knowledge:/knowledge:ro" \
		-e RETRIEVAL_TEST_KNOWLEDGE_ROOT=/knowledge \
		-w /app python:3.13-slim \
		bash -c "pip install -q -e '.[dev]' && pytest"

retrieval-logs: ## Show recent retrieval-service logs
	docker compose logs --tail=100 retrieval-service

# Phase 6: the explicit, offline indexer (python -m
# retrieval_service.indexer) -- the ONLY code allowed to write
# reliability.retrieval_chunks. Requires retrieval-service (and
# control-plane) already running and healthy (`make db-up`). Safe to
# run repeatedly: idempotent by construction (see db.py's own ON
# CONFLICT upsert target) -- a second immediate run with unchanged
# sources creates no duplicates.
rag-index: ## Phase 6: index source-controlled knowledge + current historical incidents (idempotent)
	docker compose exec -T retrieval-service python -m retrieval_service.indexer

verify-rag: ## Phase 6 real-evidence acceptance: pgvector schema, indexing, search, RAG-integrated investigation, no mutation
	./scripts/verify-rag.sh

# Bound/safely JSON-encoded via python3 -c, never naive shell string
# concatenation -- a QUERY containing a double quote or backslash
# still produces valid JSON. Requires retrieval-service running
# (`make db-up`) and reachable at 127.0.0.1:8002.
rag-search: ## Phase 6: search the retrieval index: make rag-search QUERY="checkout payment failures"
	@if [ -z "$(QUERY)" ]; then \
		echo "usage: make rag-search QUERY=\"<search text>\"" >&2; \
		exit 1; \
	fi
	@body="$$(python3 -c 'import json, sys; print(json.dumps({"query": sys.argv[1], "knowledge_limit": 3, "historical_incident_limit": 3}))' "$(QUERY)")"; \
	curl -sS -X POST http://127.0.0.1:8002/api/v1/retrieval/search \
		-H "Content-Type: application/json" \
		-d "$$body" | python3 -m json.tool

verify-observability: ## Bundled Phase 2A.1-2B.4 verification (starts Compose, checks everything, tears down)
	./scripts/verify-observability.sh

verify-persistence: ## Phase 3A persistence verification (migrations, schema, constraints, restart persistence)
	./scripts/verify-persistence.sh

verify-control-plane: ## Phase 3B control-plane integration verification (real PostgreSQL, real HTTP API)
	./scripts/verify-control-plane.sh

# Phase 3C/3D: generates (or reuses, idempotently — see the script's
# own docstring) the local Bearer tokens Alertmanager (webhook) and a
# human/operator (lifecycle) use to authenticate to control-plane —
# two separate, non-interchangeable secrets. `make db-up` already
# calls this automatically; exposed standalone for rerunning it on its
# own (e.g. after deleting observability/alertmanager/secrets/ to
# inspect a fresh-checkout path) without bringing the whole stack up
# again.
webhook-secret-init: ## Generate/reuse the local webhook + lifecycle Bearer tokens
	./scripts/init-webhook-secret.sh

verify-webhook-ingestion: ## Phase 3C/3D focused webhook ingestion verification (auth, dedup/upsert, resolution, real PostgreSQL)
	./scripts/verify-webhook-ingestion.sh

# Phase 3D: focused real PostgreSQL lifecycle verification — the full
# state machine via the real PATCH endpoint, optimistic concurrency
# (including a genuine concurrent-request race), real restart
# durability, and real occurrence-identity/stale-replay handling via
# the real webhook endpoint. Does not touch otel-collector — no
# Collector outage here at all.
verify-incident-lifecycle: ## Phase 3D real PostgreSQL lifecycle verification (state machine, concurrency, restart durability)
	./scripts/verify-incident-lifecycle.sh

# Phase 3E: focused real PostgreSQL audit-trail verification — the V3
# schema itself (constraints, index, append-only triggers), correct
# event attribution for every accepted mutation, zero events for every
# rejected/ignored/no-op operation, a real transactional-rollback proof
# (an audit-insert failure takes the incident mutation down with it),
# a genuine concurrent-PATCH race producing exactly one event, and
# audit-trail restart durability. Does not touch otel-collector — no
# Collector outage here at all; see verify-alert-ingestion below for
# where the real Collector-outage chain's own audit trail is checked.
verify-incident-audit: ## Phase 3E real PostgreSQL audit trail verification (attribution, atomicity, concurrency, append-only enforcement)
	./scripts/verify-incident-audit.sh

# The expensive real acceptance gate (section 12 of Phase 3C, extended
# Phase 3D with automatic resolution and Phase 3E with a real,
# correctly-attributed audit trail check): reuses the existing Phase
# 2B.4 Collector-outage lifecycle test (scripts/verify-alert-lifecycle.sh)
# with its Phase 3C/3D/3E ingestion assertions enabled, rather than
# running a second, separate Collector-outage test — see that script's
# own docstring.
verify-alert-ingestion: ## Phase 3C/3D/3E full acceptance: real Collector outage -> Alertmanager webhook -> persisted + resolved incident + audit trail
	VERIFY_INGESTION=true ./scripts/verify-alert-lifecycle.sh

# Phase 4: controlled failure injection against the real Compose
# checkout application. simulate-*-outage deliberately stops exactly
# one allowlisted application dependency, verifies the real safe
# failure, restores it, and verifies recovery -- see
# scripts/simulate-failure.sh and
# docs/architecture/phase-4-failure-simulation.md. Pass
# FULL_ACCEPTANCE=true with simulate-payment-outage to additionally
# prove the real Prometheus -> Alertmanager -> incident -> audit ->
# recovery chain (this is the expensive path -- prefer the plain form
# for quick local iteration).
simulate-payment-outage: ## Phase 4: deliberately stop payment-service, verify safe 502 + recovery (FULL_ACCEPTANCE=true for the full alert/incident/audit chain)
	./scripts/simulate-failure.sh payment-outage $(if $(filter true,$(FULL_ACCEPTANCE)),--full-acceptance,)

simulate-inventory-outage: ## Phase 4: deliberately stop inventory-service, verify safe 502 + short-circuit + recovery
	./scripts/simulate-failure.sh inventory-outage

test-failure-simulation: ## Phase 4 focused tests: scenario selection, safety checks, restoration behavior (no Docker required)
	./scripts/test-simulate-failure.sh

test-failure-simulation-settling: ## Phase 4 focused test: the CheckoutServerErrors settling gate added after inventory-outage (no Docker required)
	./scripts/test-failure-simulation-settling.sh

# The Phase 4 real acceptance gate. Deliberately placed after
# verify-alert-ingestion in both the Makefile ordering and CI, so this
# phase's own real outages (payment-service, inventory-service) never
# race or interfere with the Collector-outage gate's preconditions.
verify-failure-simulation: ## Phase 4 full acceptance: payment-outage (full alert/incident/audit chain) + inventory-outage, against the real stack
	./scripts/verify-failure-simulation.sh

# Phase 5: the real-evidence acceptance gate. Deliberately placed
# after verify-failure-simulation in both the Makefile ordering and
# CI, so it can reuse an already-persisted real CheckoutServerErrors
# incident from the Phase 4 gate above instead of causing another
# 8-9 minute outage. See scripts/verify-investigator.sh and
# docs/architecture/phase-5-ai-investigator.md.
verify-investigator: ## Phase 5 real-evidence acceptance: investigate a real persisted incident, verify no mutation
	./scripts/verify-investigator.sh

# Phase 5 correction round (issue 4): on_exit's provider-restoration
# logic, unit-tested in isolation with docker/wait_healthy/
# investigator_provider_mode stubbed. No Docker, Compose, or running
# stack needed -- see scripts/test-verify-investigator-restore.sh.
test-verify-investigator-restore: ## Phase 5 focused tests: provider-restoration logic on_exit (no Docker required)
	./scripts/test-verify-investigator-restore.sh

# Requests one real investigation for an existing incident UUID, e.g.:
#   make investigate INCIDENT_ID=9528f24d-c906-4770-bf8f-e0a499bf6372
# Requires investigator-service running (`make db-up`) and reachable
# at 127.0.0.1:8001. Prints the full structured JSON report. If
# INVESTIGATOR_LLM_API_KEY is not configured, prints the explicit
# "unavailable" response instead of a fabricated investigation — see
# docs/architecture/phase-5-ai-investigator.md for how to configure a
# real provider.
investigate: ## Request a real investigation: make investigate INCIDENT_ID=<existing incident UUID>
	@if [ -z "$(INCIDENT_ID)" ]; then \
		echo "usage: make investigate INCIDENT_ID=<existing incident UUID>" >&2; \
		exit 1; \
	fi
	curl -sS -X POST http://127.0.0.1:8001/api/v1/investigations \
		-H "Content-Type: application/json" \
		-d '{"incident_id": "$(INCIDENT_ID)"}' | python3 -m json.tool

agent-runtime-build: ## Build the agent-runtime-service Docker image
	docker compose build agent-runtime-service

# Same convention as investigator-test/retrieval-test: unit tests only,
# against fake/stub client doubles and InMemorySaver (Phase 7 §LANGGRAPH:
# allowed for focused unit tests where persistence is not under test) --
# never a real database connection. Run `make verify-agent-runtime` for
# the real, running-stack integration check (including the real,
# dedicated-role PostgreSQL checkpoint durability proof).
agent-runtime-test: ## Run agent-runtime-service unit tests on Python 3.13 (via Docker)
	docker run --rm -v "$(CURDIR)/services/agent-runtime-service:/app" -w /app python:3.13-slim \
		bash -c "pip install -q -e '.[dev]' && pytest"

agent-runtime-logs: ## Show recent agent-runtime-service logs
	docker compose logs --tail=100 agent-runtime-service

# Phase 7: the real-evidence acceptance gate. Deliberately placed after
# verify-rag in both the Makefile ordering and CI, so it can reuse the
# exact same real, already-persisted, resolved CheckoutServerErrors
# incident those gates already produced/verified. See
# scripts/verify-agent-runtime.sh and
# docs/architecture/phase-7-durable-agent-runtime.md.
verify-agent-runtime: ## Phase 7 real-evidence acceptance: durable LangGraph agent runs, dedicated DB role isolation, restart persistence, no mutation
	./scripts/verify-agent-runtime.sh

test-db-up-order: ## Phase 7 focused test: db-up's recipe provisions the checkpoint DB credential before agent-runtime-service is created (no Docker required)
	./scripts/test-db-up-order.sh

# Post-commit fix (GitHub Actions run #32): test-db-up-order above is
# static text analysis and never caught the real regression (the
# init script's REVOKEs unconditionally referencing a Flyway-owned
# schema that does not exist yet on a fresh database). This target
# runs the REAL, unmodified scripts/init-agent-runtime-db.sh against a
# real, but completely isolated and temporary PostgreSQL instance
# (distinct COMPOSE_PROJECT_NAME/POSTGRES_PORT -- never the developer's
# own persistent postgres_data volume), proving it succeeds before
# Flyway has ever run and correctly resumes its defense-in-depth
# REVOKEs once Flyway creates the real reliability schema.
test-init-agent-runtime-db-fresh: ## Phase 7 regression test: init-agent-runtime-db.sh succeeds on a genuinely fresh database (no reliability schema yet), against a real isolated/temporary PostgreSQL
	./scripts/test-init-agent-runtime-db-fresh.sh

tool-gateway-build: ## Build the tool-gateway Docker image
	docker compose build tool-gateway

# Go isn't installed locally for this repo; running gofmt/vet/test/build
# inside golang:1.27 keeps results reproducible and consistent with CI,
# same convention as inventory-test. `go build` is included (unlike
# inventory-test) because this is this target's own fastest path to a
# full, real compile check -- `make tool-gateway-build` above already
# does the same compile as part of the real Docker image.
tool-gateway-test: ## Run tool-gateway gofmt/vet/test/build on Go 1.27 (via Docker)
	docker run --rm -v "$(CURDIR)/services/tool-gateway:/build" -w /build golang:1.27 \
		bash -c 'test -z "$$(gofmt -l .)" && go vet ./... && go test ./... && CGO_ENABLED=0 GOOS=linux go build -o /tmp/tool-gateway ./cmd/tool-gateway'

tool-gateway-logs: ## Show recent tool-gateway logs
	docker compose logs --tail=100 tool-gateway

# Phase 8: generates/verifies the six remediation Bearer tokens this
# phase introduces (see scripts/init-remediation-secrets.sh's own
# docstring). `make db-up` already calls this itself, before any
# container that reads one of these tokens is ever created (the same
# startup-ordering lesson Phase 7 learned the hard way) -- this target
# exists for running it standalone, e.g. after a manual `docker compose
# up -d` that bypassed `make db-up`.
remediation-secret-init: ## Generate/verify the six Phase 8 remediation Bearer tokens in .env (idempotent)
	./scripts/init-remediation-secrets.sh

# Phase 8: the real-evidence acceptance gate. Deliberately placed after
# verify-agent-runtime in both the Makefile ordering and CI -- it
# creates its OWN fresh incident (never reuses an already-resolved one)
# and exercises the full human-approval/remediation/recovery path
# against the real running stack. See scripts/verify-remediation.sh and
# docs/architecture/phase-8-human-approval-remediation.md.
verify-remediation: ## Phase 8 real-evidence acceptance: human-approved remediation, tool-gateway execution, real recovery
	./scripts/verify-remediation.sh

test-remediation-cleanup-resilience: ## Phase 8 correction-round focused test: EXIT cleanup tolerates a simulated payment_fault_get failure (no Docker required)
	./scripts/test-remediation-cleanup-resilience.sh

# Human approve/reject helpers -- read CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
# from .env directly; NEVER print it (the token appears only inside the
# curl Authorization header, never in echoed output). COMMENT is
# optional in both.
remediation-approve: ## Approve a pending remediation proposal: make remediation-approve PROPOSAL_ID=<uuid> [COMMENT="..."]
	@if [ -z "$(PROPOSAL_ID)" ]; then \
		echo "usage: make remediation-approve PROPOSAL_ID=<uuid> [COMMENT=\"...\"]" >&2; \
		exit 1; \
	fi
	@token="$$(grep -E '^CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN=' .env 2>/dev/null | head -1 | cut -d= -f2-)"; \
	if [ -z "$$token" ]; then \
		echo "CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN is not set in .env -- run 'make remediation-secret-init' first" >&2; \
		exit 1; \
	fi; \
	body="$$(COMMENT='$(COMMENT)' python3 -c 'import json, os; c = os.environ.get("COMMENT", ""); print(json.dumps({"expected_status": "pending_approval", "decision": "approve", **({"comment": c} if c else {})}))')"; \
	curl -sS -X POST "http://127.0.0.1:8000/api/v1/remediation-proposals/$(PROPOSAL_ID)/decision" \
		-H "Authorization: Bearer $$token" \
		-H "Content-Type: application/json" \
		-d "$$body" | python3 -m json.tool

remediation-reject: ## Reject a pending remediation proposal: make remediation-reject PROPOSAL_ID=<uuid> [COMMENT="..."]
	@if [ -z "$(PROPOSAL_ID)" ]; then \
		echo "usage: make remediation-reject PROPOSAL_ID=<uuid> [COMMENT=\"...\"]" >&2; \
		exit 1; \
	fi
	@token="$$(grep -E '^CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN=' .env 2>/dev/null | head -1 | cut -d= -f2-)"; \
	if [ -z "$$token" ]; then \
		echo "CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN is not set in .env -- run 'make remediation-secret-init' first" >&2; \
		exit 1; \
	fi; \
	body="$$(COMMENT='$(COMMENT)' python3 -c 'import json, os; c = os.environ.get("COMMENT", ""); print(json.dumps({"expected_status": "pending_approval", "decision": "reject", **({"comment": c} if c else {})}))')"; \
	curl -sS -X POST "http://127.0.0.1:8000/api/v1/remediation-proposals/$(PROPOSAL_ID)/decision" \
		-H "Authorization: Bearer $$token" \
		-H "Content-Type: application/json" \
		-d "$$body" | python3 -m json.tool
