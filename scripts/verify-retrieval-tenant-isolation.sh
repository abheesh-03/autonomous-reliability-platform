#!/usr/bin/env bash
#
# verify-retrieval-tenant-isolation.sh — Phase 14 correction round,
# Blocker 2 real-PostgreSQL acceptance.
#
# Runs scripts/retrieval_tenant_isolation_check.py (see its own
# docstring) inside a disposable, throwaway container joined to the
# ALREADY-RUNNING Compose network -- it mounts retrieval-service's
# real source tree (read-write only so `pip install -e .` can write
# its own *.egg-info metadata there; the check itself never edits any
# source file) and connects to the real `postgres` service by its real
# Compose DNS name. It does NOT restart, rebuild, or otherwise touch
# the already-running retrieval-service/postgres containers, so it is
# safe to run alongside other work against the same stack.
#
# Requires `make db-up` (or an already-running stack) and the
# database migrated at least through V10 (organization_id must exist
# on reliability.incidents) -- `make db-migrate` is safe to rerun.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${POSTGRES_USER:?POSTGRES_USER must be set (see .env)}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set (see .env)}"
: "${POSTGRES_DB:?POSTGRES_DB must be set (see .env)}"

NETWORK="${COMPOSE_PROJECT_NAME:-$(basename "$REPO_ROOT" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_-' '_')}_default"
if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  # Fall back to whatever network the already-running postgres
  # container is actually attached to -- more robust than guessing
  # Compose's own project-name derivation rules.
  NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
fi
if [ -z "$NETWORK" ] || ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "FAIL: could not determine the Compose network -- is the stack up? (make db-up)" >&2
  exit 1
fi

echo "Running real-PostgreSQL tenant-isolation check against network '$NETWORK'..."
docker run --rm \
  --network "$NETWORK" \
  -v "$REPO_ROOT/services/retrieval-service:/app" \
  -v "$SCRIPT_DIR/retrieval_tenant_isolation_check.py:/check.py:ro" \
  -e POSTGRES_USER="$POSTGRES_USER" \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -e POSTGRES_DB="$POSTGRES_DB" \
  -w /app \
  python:3.13-slim \
  bash -c "pip install -q -e . >/tmp/pip-install.log 2>&1 && python /check.py"

echo "OK: retrieval-service tenant isolation verified against the real database."
