.PHONY: help check compose-config db-up db-down db-status db-logs db-restart db-migrate checkout-build checkout-test checkout-logs payment-build payment-test payment-logs inventory-build inventory-test inventory-logs notification-build notification-test notification-logs otel-logs prometheus-logs grafana-logs control-plane-build control-plane-test control-plane-logs verify-observability verify-persistence verify-control-plane webhook-secret-init verify-webhook-ingestion verify-alert-ingestion verify-incident-lifecycle

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
	@echo "  verify-observability Bundled Phase 2A.1-2B.4 verification (starts Compose, checks everything, tears down)"
	@echo "  verify-persistence  Phase 3A persistence verification (migrations, schema, constraints, restart persistence)"
	@echo "  verify-control-plane Phase 3B control-plane integration verification (real PostgreSQL, real HTTP API)"
	@echo "  webhook-secret-init  Generate/reuse the local webhook + lifecycle Bearer tokens"
	@echo "  verify-webhook-ingestion Phase 3C/3D focused webhook ingestion verification (auth, dedup/upsert, resolution, real PostgreSQL)"
	@echo "  verify-alert-ingestion Phase 3C/3D full acceptance: real Collector outage -> Alertmanager webhook -> persisted + resolved incident"
	@echo "  verify-incident-lifecycle Phase 3D real PostgreSQL lifecycle verification (state machine, concurrency, restart durability)"

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

# The expensive real acceptance gate (section 12 of Phase 3C, extended
# Phase 3D with automatic resolution): reuses the existing Phase 2B.4
# Collector-outage lifecycle test (scripts/verify-alert-lifecycle.sh)
# with its Phase 3C/3D ingestion assertions enabled, rather than
# running a second, separate Collector-outage test — see that script's
# own docstring.
verify-alert-ingestion: ## Phase 3C/3D full acceptance: real Collector outage -> Alertmanager webhook -> persisted + resolved incident
	VERIFY_INGESTION=true ./scripts/verify-alert-lifecycle.sh
