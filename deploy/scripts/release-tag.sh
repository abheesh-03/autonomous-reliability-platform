#!/usr/bin/env bash
#
# release-tag.sh -- Phase 17A correction round, item 8.
#
# Gives every currently-running application image this deployment
# built a REAL, identifiable local tag (the git commit it was built
# from) BEFORE a rollout overwrites `:latest` -- without this, once a
# new `up -d --build` replaces `:latest`, the previous version is
# simply gone; there is no registry in this phase (see
# deploy/RELEASE_MANIFEST.md's own "Application release identity"
# note), so a local tag is the only thing that can make a later
# rollback possible at all.
#
# Usage (run BEFORE pulling/building a new version):
#   ./deploy/scripts/release-tag.sh
#
# Tags every application service's CURRENT `:latest` image (if it
# exists) as `:<short-git-sha>` AND `:previous` (a floating pointer to
# "whatever was running immediately before the last rollout" --
# deploy/scripts/rollback.sh's own default target). Never deletes or
# modifies `:latest` itself -- only adds tags pointing at the same
# image.
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

# Matches deploy/RELEASE_MANIFEST.md's own "Application images" table
# exactly -- every service built from this repository, never a pulled
# third-party image.
APP_SERVICES=(
  control-plane retrieval-service investigator-service agent-runtime-service
  checkout-service payment-service tool-gateway inventory-service
  notification-service web-console retention-scheduler
)

current_sha="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
[ "$current_sha" != "unknown" ] || fail "could not resolve the current git commit -- refusing to tag a release with an unidentifiable version"

tagged_count=0
for service in "${APP_SERVICES[@]}"; do
  image="${PROJECT_NAME}-${service}"
  if ! docker image inspect "${image}:latest" >/dev/null 2>&1; then
    echo "skip: ${image}:latest does not exist yet (never built) -- nothing to tag"
    continue
  fi
  docker tag "${image}:latest" "${image}:${current_sha}"
  docker tag "${image}:latest" "${image}:previous"
  echo "tagged: ${image}:latest -> ${image}:${current_sha} and ${image}:previous"
  tagged_count=$((tagged_count + 1))
done

echo ""
echo "RELEASE TAGGED: ${tagged_count} application image(s) now identifiable as git commit ${current_sha} (and :previous)."
echo "Safe to roll out a new version now; roll back with: ./deploy/scripts/rollback.sh [<service>|all] [<tag>]"
