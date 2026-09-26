.PHONY: help check compose-config db-up db-down db-status db-logs db-restart

help: ## Show available targets
	@echo "Available targets:"
	@echo "  help            Show this help"
	@echo "  check           Verify local developer prerequisites"
	@echo "  compose-config  Validate docker-compose.yml"
	@echo "  db-up           Start PostgreSQL (docker compose up -d)"
	@echo "  db-down         Stop PostgreSQL, preserving the data volume"
	@echo "  db-status       Show PostgreSQL container status"
	@echo "  db-logs         Show recent PostgreSQL logs"
	@echo "  db-restart      Restart PostgreSQL without removing data"

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
