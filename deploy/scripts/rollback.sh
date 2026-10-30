#!/usr/bin/env bash
#
# rollback.sh -- Phase 17A correction round, item 8.
#
# Rolls back one or every application service to a SPECIFIC,
# previously tagged local image (see ./deploy/scripts/release-tag.sh,
# which must have been run before the rollout being rolled back from)
# -- WITHOUT touching the database schema or its data, and WITHOUT
# rebuilding (a `--build` here would simply re-create the current
# code again, defeating the entire point).
#
# CORRECTION ROUND: deploy/README.md previously showed
# `up -d --no-deps <service>` as "the" rollback command -- that alone
# selects NO previous image at all; with no explicit `image:` field,
# Compose resolves a `build:`-only service back to whatever is
# CURRENTLY tagged `:latest`, which after a rollout IS the new
# version. A real rollback must first retarget `:latest` at the old,
# preserved image, THEN recreate -- that is what this script does.
#
# Usage:
#   ./deploy/scripts/rollback.sh                      # every app service, to :previous
#   ./deploy/scripts/rollback.sh web-console           # one service, to :previous
#   ./deploy/scripts/rollback.sh web-console a1b2c3d    # one service, to an exact git-sha tag
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

fail() { echo "FAIL: $1" >&2; exit 1; }

ENV_FILE="$DEPLOY_DIR/.env.deploy"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found -- run ./deploy/scripts/init-deploy-secrets.sh first"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-arp-deploy}"

ALL_APP_SERVICES=(
  control-plane retrieval-service investigator-service agent-runtime-service
  checkout-service payment-service tool-gateway inventory-service
  notification-service web-console retention-scheduler
)

TARGET_SERVICE="${1:-all}"
TARGET_TAG="${2:-previous}"

if [ "$TARGET_SERVICE" = "all" ]; then
  SERVICES=("${ALL_APP_SERVICES[@]}")
else
  valid=0
  for s in "${ALL_APP_SERVICES[@]}"; do [ "$s" = "$TARGET_SERVICE" ] && valid=1; done
  [ "$valid" -eq 1 ] || fail "unknown service '$TARGET_SERVICE' -- must be one of: all ${ALL_APP_SERVICES[*]}"
  SERVICES=("$TARGET_SERVICE")
fi

COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

for service in "${SERVICES[@]}"; do
  image="${PROJECT_NAME}-${service}"
  docker image inspect "${image}:${TARGET_TAG}" >/dev/null 2>&1 \
    || fail "${image}:${TARGET_TAG} does not exist -- run ./deploy/scripts/release-tag.sh before a rollout to make a rollback target available, or pass an exact git-sha tag that was tagged in the past"
  rolled_back_from="$(docker image inspect "${image}:latest" --format '{{.Id}}' 2>/dev/null || echo "(none)")"
  rolled_back_to="$(docker image inspect "${image}:${TARGET_TAG}" --format '{{.Id}}')"
  if [ "$rolled_back_from" = "$rolled_back_to" ]; then
    echo "no-op: ${image}:latest is already ${TARGET_TAG} (${rolled_back_to:0:19})"
    continue
  fi
  docker tag "${image}:${TARGET_TAG}" "${image}:latest"
  echo "retargeted ${image}:latest -> ${TARGET_TAG} (${rolled_back_to:0:19}), was ${rolled_back_from:0:19}"
done

echo ""
echo "== recreating the rolled-back service(s), WITHOUT rebuilding (--no-deps, no --build) =="
"${COMPOSE[@]}" up -d --no-deps --no-build "${SERVICES[@]}"

echo ""
echo "ROLLBACK COMPLETE: ${SERVICES[*]} now running from tag '${TARGET_TAG}'. Database schema/data untouched."
