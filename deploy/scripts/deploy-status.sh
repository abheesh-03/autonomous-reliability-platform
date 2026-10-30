#!/usr/bin/env bash
# deploy-status.sh -- Phase 17A dependency-aware readiness check.
#
# CORRECTION ROUND -- real finding: this script previously only ever
# PRINTED information and fell off the end with whatever exit status
# its last command happened to have, which was always 0 (the final
# line was `curl ... || echo "..."`, and `echo` always succeeds) --
# every container crash-looping, every service reporting unhealthy,
# and a dead reverse proxy all still reported exit 0. It is rewritten
# to actually evaluate three DISTINCT layers and exit non-zero the
# instant any required one is not ready:
#   1. Container liveness   -- is each required container's own State
#      "running" at all (a crash-looped/exited container fails here).
#   2. Application readiness -- for containers with their own Docker
#      HEALTHCHECK already defined (see docker-compose.yml), is that
#      Health status "healthy" (a running-but-still-starting or
#      failing-its-own-healthcheck container fails here, distinct
#      from "not running at all").
#   3. Proxy reachability   -- a real HTTPS request through Caddy,
#      distinguishing "connection/TLS failed outright" (the proxy
#      itself is down) from "a non-2xx HTTP response" (the proxy is up
#      but something behind it is failing) from a genuine 2xx.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.deploy"

[ -f "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE not found"; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$REPO_ROOT" || exit 1
COMPOSE=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

# Matches deploy/scripts/validate-merged-config.py's own
# EXPECTED_SERVICES exactly -- one canonical list, not a second,
# independently-drifting one.
REQUIRED_SERVICES=(
  postgres control-plane retrieval-service investigator-service
  agent-runtime-service tool-gateway checkout-service payment-service
  inventory-service notification-service otel-collector tempo loki
  prometheus alertmanager grafana alloy web-console docker-socket-proxy
  retention-scheduler caddy
)

echo "== container status =="
"${COMPOSE[@]}" ps

echo ""
echo "== disk usage (named volumes for this project) =="
docker system df -v 2>/dev/null | grep -E "^${COMPOSE_PROJECT_NAME:-arp-deploy}_" || echo "(no volumes found yet)"

PS_JSON="$("${COMPOSE[@]}" ps --all --format json 2>/dev/null)"
[ -n "$PS_JSON" ] || { echo "FAIL: could not read container status at all ('docker compose ps' produced no output)"; exit 1; }

FAILED=0

echo ""
echo "== layer 1: container liveness =="
for service in "${REQUIRED_SERVICES[@]}"; do
  state="$(echo "$PS_JSON" | python3 -c "
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get('Service') == '$service':
        print(entry.get('State', ''))
        break
" 2>/dev/null)"
  if [ "$state" != "running" ]; then
    echo "FAIL: $service is not running (state: '${state:-not found}')"
    FAILED=1
  else
    echo "ok: $service is running"
  fi
done

echo ""
echo "== layer 2: application readiness (Docker healthcheck status, where defined) =="
for service in "${REQUIRED_SERVICES[@]}"; do
  health="$(echo "$PS_JSON" | python3 -c "
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get('Service') == '$service':
        print(entry.get('Health', ''))
        break
" 2>/dev/null)"
  case "$health" in
    "")
      echo "ok: $service has no Docker healthcheck defined (liveness-only)"
      ;;
    healthy)
      echo "ok: $service reports healthy"
      ;;
    *)
      echo "FAIL: $service reports health status '$health' (expected 'healthy')"
      FAILED=1
      ;;
  esac
done

echo ""
echo "== layer 3: public HTTPS reachability (via Caddy, real TLS) =="
if [ ! -s "${DEPLOY_DIR}/caddy_root.crt" ]; then
  echo "FAIL: ${DEPLOY_DIR}/caddy_root.crt not extracted yet -- see deploy/README.md's \"Local HTTPS proof\" section"
  FAILED=1
else
  host="$(echo "${DEPLOYMENT_PUBLIC_ORIGIN:-}" | sed -E 's#https?://##')"
  if [ -z "$host" ]; then
    echo "FAIL: DEPLOYMENT_PUBLIC_ORIGIN is not set"
    FAILED=1
  else
    http_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      --resolve "${host}:443:127.0.0.1" \
      --cacert "${DEPLOY_DIR}/caddy_root.crt" \
      "${DEPLOYMENT_PUBLIC_ORIGIN}/" 2>/dev/null)"
    curl_status=$?
    if [ "$curl_status" -ne 0 ] || [ "$http_code" = "000" ]; then
      echo "FAIL: the HTTPS connection to Caddy itself failed outright (curl exit $curl_status) -- the proxy is down, not merely an application behind it"
      FAILED=1
    elif [ "${http_code:0:1}" != "2" ] && [ "${http_code:0:1}" != "3" ]; then
      echo "FAIL: Caddy is reachable but returned HTTP $http_code -- the proxy is up, something behind it is not"
      FAILED=1
    else
      echo "ok: HTTP $http_code through Caddy's real TLS"
    fi
  fi
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "STATUS: all required services are running, healthy, and reachable."
  exit 0
else
  echo "STATUS: one or more required services are NOT ready (see FAIL lines above)." >&2
  exit 1
fi
