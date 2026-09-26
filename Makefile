.PHONY: help check compose-config db-up db-down db-status db-logs db-restart checkout-build checkout-test checkout-logs payment-build payment-test payment-logs

help: ## Show available targets
	@echo "Available targets:"
	@echo "  help            Show this help"
	@echo "  check           Verify local developer prerequisites"
	@echo "  compose-config  Validate docker-compose.yml"
	@echo "  db-up           Start the Compose environment (docker compose up -d)"
	@echo "  db-down         Stop the Compose environment, preserving the data volume"
	@echo "  db-status       Show container status"
	@echo "  db-logs         Show recent PostgreSQL logs"
	@echo "  db-restart      Restart PostgreSQL without removing data"
	@echo "  checkout-build  Build the checkout-service Docker image"
	@echo "  checkout-test   Run checkout-service tests locally (requires Java 21)"
	@echo "  checkout-logs   Show recent checkout-service logs"
	@echo "  payment-build   Build the payment-service Docker image"
	@echo "  payment-test    Run payment-service tests on Python 3.13 (via Docker)"
	@echo "  payment-logs    Show recent payment-service logs"

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
