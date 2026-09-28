#!/usr/bin/env bash
#
# verify-observability.sh — Bundled Phase 2A.1/2A.2 verification.
#
# Starts the full Docker Compose environment, waits for every
# application and observability service to become healthy (with a
# documented exception for otel-collector, whose official image has no
# shell/wget/curl and therefore no Docker-level healthcheck), verifies
# Prometheus's scrape targets and Grafana's provisioned datasource,
# re-runs the POST /checkouts regression check, then (Phase 2A.2) checks
# that checkout-service's OTel Java agent telemetry actually reached
# Prometheus (application metrics) and the Collector (trace spans),
# then always tears the environment down (without deleting volumes) and
# confirms the named volumes still exist.
#
# Exits non-zero immediately on the first failed check.

set -euo pipefail

# Always operate from the repository root, regardless of caller cwd.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

cleanup() {
  section "Cleanup (trap): stopping Compose environment (preserving volumes)"
  docker compose down || true
}
trap cleanup EXIT

# --------------------------------------------------------------------
# A. Static checks
# --------------------------------------------------------------------
section "A. Static checks"

echo "-- git diff --check --"
git diff --check

echo "-- docker compose config --quiet --"
docker compose config --quiet

echo "-- required observability config files --"
for f in \
  observability/otel-collector/config.yaml \
  observability/prometheus/prometheus.yml \
  observability/grafana/provisioning/datasources/datasource.yml
do
  [ -f "$f" ] || fail "missing required config file: $f"
  echo "  found: $f"
done

# --------------------------------------------------------------------
# B. Start environment
# --------------------------------------------------------------------
section "B. Start environment"
docker compose up -d

# --------------------------------------------------------------------
# C. Wait for Docker-reported health
# --------------------------------------------------------------------
section "C. Wait for Docker-reported health"

wait_for_healthy() {
  local service="$1"
  local attempts=20
  local cid health
  for i in $(seq 1 "$attempts"); do
    cid="$(docker compose ps -q "$service")"
    health="$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
    echo "  [$service] attempt $i/$attempts: health=$health"
    if [ "$health" = "healthy" ]; then
      return 0
    fi
    sleep 3
  done
  fail "$service did not become healthy in time"
}

for svc in postgres checkout-service payment-service inventory-service notification-service prometheus grafana; do
  wait_for_healthy "$svc"
done

echo ""
echo "-- otel-collector: no Docker health status is possible (official image"
echo "   has no shell/wget/curl); verifying it is running and functionally"
echo "   reachable on its health_check port instead --"

otel_state="$(docker inspect --format='{{.State.Status}}' "$(docker compose ps -q otel-collector)" 2>/dev/null || true)"
[ "$otel_state" = "running" ] || fail "otel-collector container is not running (state=$otel_state)"
echo "  otel-collector container state: running"

otel_ready=false
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:13133/ >/dev/null 2>&1; then
    otel_ready=true
    break
  fi
  echo "  [otel-collector] attempt $i/20: health_check endpoint not ready yet"
  sleep 3
done
[ "$otel_ready" = true ] || fail "otel-collector health_check endpoint (127.0.0.1:13133) never responded"
echo "  otel-collector health_check endpoint (127.0.0.1:13133) responded"

# --------------------------------------------------------------------
# D. Prometheus
# --------------------------------------------------------------------
section "D. Prometheus"

curl -fsS http://127.0.0.1:9090/-/ready >/dev/null || fail "Prometheus /-/ready did not respond"
echo "  Prometheus /-/ready OK"

targets_ok=false
for i in $(seq 1 20); do
  if body="$(curl -fsS http://127.0.0.1:9090/api/v1/targets 2>/dev/null)" && echo "$body" | jq -e '
      ([.data.activeTargets[] | select(.labels.job=="prometheus") | .health] | length > 0 and all(.[]; . == "up"))
      and
      ([.data.activeTargets[] | select(.labels.job=="otel-collector") | .health] | length > 0 and all(.[]; . == "up"))
      and
      ([.data.activeTargets[] | select(.labels.job=="otel-collector-app-metrics") | .health] | length > 0 and all(.[]; . == "up"))
    ' >/dev/null 2>&1
  then
    targets_ok=true
    break
  fi
  echo "  attempt $i/20: prometheus/otel-collector/otel-collector-app-metrics targets not all UP yet"
  sleep 3
done
[ "$targets_ok" = true ] || fail "Prometheus targets (prometheus, otel-collector, otel-collector-app-metrics) never all reported UP"
echo "  Prometheus targets UP: prometheus, otel-collector, otel-collector-app-metrics"

# --------------------------------------------------------------------
# E. Grafana
# --------------------------------------------------------------------
section "E. Grafana"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-local_dev_only_change_me}"

health_body="$(curl -fsS http://127.0.0.1:3000/api/health)" || fail "Grafana /api/health did not respond"
echo "$health_body" | jq -e '.database == "ok"' >/dev/null || fail "Grafana /api/health did not report database == ok"
echo "  Grafana /api/health OK"

datasources_body="$(curl -fsS -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" http://127.0.0.1:3000/api/datasources)" \
  || fail "Grafana /api/datasources did not respond"
echo "$datasources_body" | jq -e '
    [.[] | select(.type == "prometheus" and .url == "http://prometheus:9090" and .isDefault == true)] | length > 0
  ' >/dev/null || fail "Grafana provisioned Prometheus datasource not found or misconfigured"
echo "  Grafana Prometheus datasource OK (type=prometheus, url=http://prometheus:9090, isDefault=true)"

# --------------------------------------------------------------------
# F. Regression: POST /checkouts
# --------------------------------------------------------------------
section "F. Regression: POST /checkouts"

checkout_body="$(curl -fsS -X POST http://127.0.0.1:8080/checkouts \
  -H 'Content-Type: application/json' \
  -d '{"sku":"sku_keyboard_001","quantity":2,"amount_cents":2599,"currency":"USD","recipient":"customer@example.com"}')" \
  || fail "POST /checkouts request failed"
echo "$checkout_body"
echo "$checkout_body" | jq -e '
    (.checkout_id | type == "string" and length > 0 and startswith("chk_"))
    and .status == "COMPLETED"
    and (.payment.payment_id | type == "string" and length > 0)
    and .payment.status == "AUTHORIZED"
    and (.inventory.reservation_id | type == "string" and length > 0)
    and .inventory.status == "RESERVED"
    and (.notification.notification_id | type == "string" and length > 0)
    and .notification.status == "ACCEPTED"
  ' >/dev/null || fail "POST /checkouts did not return the expected completed orchestration response"
echo "  POST /checkouts OK"

# --------------------------------------------------------------------
# G. Observability: checkout-service application metrics in Prometheus
# --------------------------------------------------------------------
section "G. Observability: checkout-service application metrics in Prometheus"

echo "-- waiting for checkout-service metrics to reach Prometheus (the OTel"
echo "   Java agent's metric export interval and Prometheus's own scrape"
echo "   cycle are both asynchronous) --"

checkout_metrics_ok=false
for i in $(seq 1 20); do
  if server_body="$(curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
        --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="checkout-service",http_route="/checkouts"}' 2>/dev/null)" \
      && echo "$server_body" | jq -e '.data.result | length > 0' >/dev/null 2>&1 \
      && client_body="$(curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
        --data-urlencode 'query=count by (server_address) (http_client_request_duration_seconds_count{service_name="checkout-service"})' 2>/dev/null)" \
      && echo "$client_body" | jq -e '
          ([.data.result[].metric.server_address] | unique | sort) ==
          ["inventory-service", "notification-service", "payment-service"]
        ' >/dev/null 2>&1
  then
    checkout_metrics_ok=true
    break
  fi
  echo "  attempt $i/20: checkout-service HTTP server/client metrics not in Prometheus yet"
  sleep 3
done
[ "$checkout_metrics_ok" = true ] || fail "checkout-service application metrics (HTTP server + HTTP client) never appeared in Prometheus"
echo "  checkout-service HTTP server metrics present (http_server_request_duration_seconds_count, service_name=checkout-service, http_route=/checkouts)"
echo "  checkout-service HTTP client metrics present for all 3 downstream calls (payment-service, inventory-service, notification-service)"

# --------------------------------------------------------------------
# H. Observability: checkout-service trace evidence in Collector logs
# --------------------------------------------------------------------
section "H. Observability: checkout-service trace evidence in Collector logs"

echo "-- Phase 2A.2 has no trace backend yet; traces are verified via the"
echo "   Collector's debug exporter output in its own container logs --"

trace_evidence_ok=false
for i in $(seq 1 20); do
  if logs="$(docker compose logs otel-collector 2>&1)" \
      && grep -qF 'service.name: Str(checkout-service)' <<<"$logs" \
      && grep -qF 'Name           : POST /checkouts' <<<"$logs" \
      && grep -qF 'Kind           : Server' <<<"$logs" \
      && grep -qF 'Kind           : Client' <<<"$logs" \
      && grep -qF 'url.full: Str(http://payment-service:8081/payments/authorize)' <<<"$logs" \
      && grep -qF 'url.full: Str(http://inventory-service:8082/inventory/reservations)' <<<"$logs" \
      && grep -qF 'url.full: Str(http://notification-service:8083/notifications)' <<<"$logs"
  then
    trace_evidence_ok=true
    break
  fi
  echo "  attempt $i/20: checkout-service trace evidence not in Collector logs yet"
  sleep 3
done
[ "$trace_evidence_ok" = true ] || fail "checkout-service trace evidence (server span + 3 downstream client spans) never appeared in Collector logs"
echo "  checkout-service SERVER span 'POST /checkouts' present in Collector logs"
echo "  CLIENT spans present for all 3 downstream calls (payment-service, inventory-service, notification-service)"

# --------------------------------------------------------------------
# I. Container/log sanity
# --------------------------------------------------------------------
section "I. Container/log sanity"

docker compose ps

echo ""
echo "-- checking for exited containers --"
exited_found=false
for cid in $(docker compose ps -aq); do
  status="$(docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
  name="$(docker inspect --format='{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##')"
  if [ "$status" = "exited" ]; then
    echo "  EXITED: $name"
    exited_found=true
  fi
done
if [ "$exited_found" = true ]; then
  fail "one or more containers exited — see above"
fi
echo "  no exited containers"

echo ""
echo "-- otel-collector logs (last 50 lines) --"
docker compose logs --tail=50 otel-collector
echo ""
echo "-- prometheus logs (last 50 lines) --"
docker compose logs --tail=50 prometheus
echo ""
echo "-- grafana logs (last 50 lines) --"
docker compose logs --tail=50 grafana

# --------------------------------------------------------------------
# J. Persistence after cleanup
# --------------------------------------------------------------------
section "J. Persistence after cleanup"

echo "-- docker compose down (preserving volumes) --"
docker compose down
# Teardown already happened above; disable the trap so it doesn't run
# (and log a confusing duplicate teardown) on normal exit.
trap - EXIT

for vol in \
  autonomous-reliability-platform_postgres_data \
  autonomous-reliability-platform_prometheus_data \
  autonomous-reliability-platform_grafana_data
do
  docker volume inspect "$vol" >/dev/null 2>&1 || fail "expected named volume missing after teardown: $vol"
  echo "  volume present: $vol"
done

section "SUCCESS"
echo "Phase 2A.1/2A.2 observability verification passed."
