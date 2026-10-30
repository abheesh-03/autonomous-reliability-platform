#!/usr/bin/env bash
# deploy-down.sh -- Phase 17A: stop the deployment stack, preserving
# its own named volumes by default (same "preserve data" convention
# as the repository root's own `make db-down`). Pass --volumes to
# ALSO remove this deployment's own volumes (never the developer's
# local-development ones -- they are in a completely separate
# Compose project/volume namespace).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.deploy"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$REPO_ROOT"
COMPOSE=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

if [ "${1:-}" = "--volumes" ]; then
  echo "WARNING: removing this deployment's own named volumes (postgres data, etc.) -- never the developer's local-development ones."
  "${COMPOSE[@]}" down --volumes
else
  "${COMPOSE[@]}" down
fi
