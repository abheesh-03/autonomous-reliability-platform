#!/usr/bin/env bash
# deploy-up.sh -- Phase 17A: bring the deployment stack up.
#
# Runs the preflight FIRST and refuses to continue on any failure.
# Always invokes both Compose files together with an explicit,
# separate project name and env file -- never touches the developer's
# own default-project local-development stack, and never shares a
# volume with it (distinct COMPOSE_PROJECT_NAME => distinct named
# volumes).
#
# Order: preflight -> postgres only -> Flyway (V1-V17; V1-V16
# unchanged, V17 newly added this round) -> least-privileged runtime
# roles + auth schema -> the full stack.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.deploy"

"$SCRIPT_DIR/preflight.sh"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$REPO_ROOT"
COMPOSE=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

echo "== starting postgres =="
"${COMPOSE[@]}" up -d postgres

echo "== waiting for postgres to become healthy =="
attempts=30
until "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_BOOTSTRAP_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
  attempts=$((attempts - 1))
  [ "$attempts" -gt 0 ] || { echo "FAIL: postgres did not become ready in time" >&2; exit 1; }
  sleep 2
done

echo "== applying migrations (V1-V17; V1-V16 unchanged, V17 newly added this round) =="
"${COMPOSE[@]}" run --rm flyway migrate

echo "== creating least-privileged runtime roles (control_plane_app, retrieval_app, web_console, agent_runtime) =="
"$SCRIPT_DIR/init-deploy-secrets.sh" --apply-roles

echo "== applying Better Auth's schema to the auth schema (owned by web_console) =="
"$SCRIPT_DIR/apply-deploy-auth-schema.sh"

echo "== building and starting the full stack =="
"${COMPOSE[@]}" up -d --build

echo "Deployment stack is up under project '${COMPOSE_PROJECT_NAME:-arp-deploy}'. Run ./deploy/scripts/deploy-status.sh to check health."
