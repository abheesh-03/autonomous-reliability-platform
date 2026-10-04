.PHONY: help check compose-config db-up db-down db-status db-logs db-restart db-migrate checkout-build checkout-test checkout-logs payment-build payment-test payment-logs inventory-build inventory-test inventory-logs notification-build notification-test notification-logs otel-logs prometheus-logs grafana-logs control-plane-build control-plane-test control-plane-logs investigator-build investigator-test investigator-logs verify-observability verify-persistence verify-control-plane webhook-secret-init verify-webhook-ingestion verify-alert-ingestion verify-incident-lifecycle verify-incident-audit simulate-payment-outage simulate-inventory-outage test-failure-simulation verify-failure-simulation verify-investigator test-verify-investigator-restore investigate

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
	@echo "  verify-failure-simulation Phase 4 full acceptance: payment-outage (full alert/incident/audit chain) + inventory-outage, against the real stack"
	@echo "  verify-investigator Phase 5 real-evidence acceptance: investigate a real persisted incident, verify no mutation"
	@echo "  test-verify-investigator-restore Phase 5 focused tests: provider-restoration logic on_exit (no Docker required)"
	@echo "  investigate         Request a real investigation: make investigate INCIDENT_ID=<existing incident UUID>"

check: ## Verify local developer prerequisites
	./scripts/check-env.sh

compose-config: ## Validate docker-compose.yml
	docker compose config

db-up: ## Start the Compose environment (docker compose up -d)
	./scripts/init-webhook-secret.sh
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
