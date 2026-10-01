.PHONY: help check compose-config db-up db-down db-status db-logs db-restart db-migrate checkout-build checkout-test checkout-logs payment-build payment-test payment-logs inventory-build inventory-test inventory-logs notification-build notification-test notification-logs otel-logs prometheus-logs grafana-logs verify-observability verify-persistence

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
	@echo "  verify-observability Bundled Phase 2A.1-2B.4 verification (starts Compose, checks everything, tears down)"
	@echo "  verify-persistence  Phase 3A persistence verification (migrations, schema, constraints, restart persistence)"

check: ## Verify local developer prerequisites
	./scripts/check-env.sh

compose-config: ## Validate docker-compose.yml
	docker compose config

db-up: ## Start PostgreSQL (does not wait for health)
	docker compose up -d
	@echo "PostgreSQL container started. Run 'make db-status' to check health before using it."

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

verify-observability: ## Bundled Phase 2A.1-2B.4 verification (starts Compose, checks everything, tears down)
	./scripts/verify-observability.sh

verify-persistence: ## Phase 3A persistence verification (migrations, schema, constraints, restart persistence)
	./scripts/verify-persistence.sh
