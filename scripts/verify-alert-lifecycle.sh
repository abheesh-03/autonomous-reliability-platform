#!/usr/bin/env bash
#
# verify-alert-lifecycle.sh — Phase 2B.4 alert lifecycle acceptance
# test. Proves a REAL Prometheus alert rule (TelemetryPipelineUnavailable
# by default) goes through: inactive -> firing (caused by a real,
# controlled failure, not a rule-file edit or a direct POST to
# Alertmanager's API) -> observed in Alertmanager -> recovery ->
# inactive, and that the real telemetry path resumes afterward.
#
# Shell is responsible for the Docker lifecycle operations (stopping
# and restarting otel-collector); scripts/verify-alerting.py is
# responsible for all HTTP API validation against Prometheus and
# Alertmanager — no validation logic is duplicated here.
#
# Safe to source ALERT_NAME/PROMETHEUS_URL/ALERTMANAGER_URL from the
# environment; otherwise defaults to the deterministic
# TelemetryPipelineUnavailable rule against the standard local ports.
#
# On any failure (or success), the EXIT trap restores otel-collector if
# this script is the one that stopped it — the environment is never
# left with the Collector down.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
ALERT_NAME="${ALERT_NAME:-TelemetryPipelineUnavailable}"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

COLLECTOR_STOPPED=false
restore_collector() {
  if [ "$COLLECTOR_STOPPED" = true ]; then
    echo "" >&2
    echo "-- trap: restoring otel-collector (this script left it stopped) --" >&2
    docker compose start otel-collector >/dev/null 2>&1 || true
  fi
}
trap restore_collector EXIT

section "1. Confirm both Collector scrape targets are UP before the test"
targets_up=false
for i in $(seq 1 20); do
  up_body="$(curl -fsS -G "$PROMETHEUS_URL/api/v1/query" --data-urlencode 'query=up{job=~"otel-collector|otel-collector-app-metrics"}')"
  if echo "$up_body" | python3 -c '
import json, sys
result = json.load(sys.stdin)["data"]["result"]
ok = len(result) == 2 and all(r["value"][1] == "1" for r in result)
sys.exit(0 if ok else 1)
'; then
    targets_up=true
    break
  fi
  echo "  attempt $i/20: both Collector scrape targets not UP yet"
  sleep 3
done
[ "$targets_up" = true ] || fail "Collector scrape targets (otel-collector, otel-collector-app-metrics) were not both UP before the test even started"
echo "  both Collector scrape targets UP"

section "2. Confirm $ALERT_NAME is initially inactive"
python3 scripts/verify-alerting.py state --prometheus-url "$PROMETHEUS_URL" --alert "$ALERT_NAME" --expect-state inactive

section "3. Stop otel-collector (controlled, real failure)"
docker compose stop otel-collector >/dev/null
COLLECTOR_STOPPED=true
echo "  otel-collector stopped"

section "4-7. Wait for the scrape failure, the rule's for: duration, and Alertmanager propagation, then confirm firing in both Prometheus and Alertmanager"
firing_ok=false
for i in $(seq 1 40); do
  if python3 scripts/verify-alerting.py firing \
       --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$ALERT_NAME"
  then
    firing_ok=true
    break
  fi
  echo "  attempt $i/40: $ALERT_NAME not yet firing in Prometheus + visible in Alertmanager"
  sleep 5
done
[ "$firing_ok" = true ] || fail "$ALERT_NAME never reached firing in Prometheus and a matching active alert in Alertmanager"

section "8. Restart otel-collector"
docker compose start otel-collector >/dev/null
COLLECTOR_STOPPED=false
echo "  otel-collector restarted"

section "9. Wait for Collector readiness (health_check endpoint)"
collector_ready=false
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:13133/ >/dev/null 2>&1; then
    collector_ready=true
    break
  fi
  echo "  attempt $i/20: otel-collector health_check endpoint not ready yet"
  sleep 3
done
[ "$collector_ready" = true ] || fail "otel-collector health_check endpoint (127.0.0.1:13133) never responded after restart"
echo "  otel-collector health_check endpoint responded"

section "10-12. Wait for both scrape targets UP again, the Prometheus rule to return to inactive, and Alertmanager to reflect resolution"
recovered_ok=false
for i in $(seq 1 40); do
  if python3 scripts/verify-alerting.py recovered \
       --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$ALERT_NAME"
  then
    recovered_ok=true
    break
  fi
  echo "  attempt $i/40: $ALERT_NAME not yet recovered (inactive in Prometheus + resolved/absent in Alertmanager)"
  sleep 5
done
[ "$recovered_ok" = true ] || fail "$ALERT_NAME never recovered to inactive in Prometheus / resolved in Alertmanager"

section "13. Trigger a fresh real checkout and confirm telemetry resumes normally"
before_count="$(curl -fsS -G "$PROMETHEUS_URL/api/v1/query" \
  --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="checkout-service",http_route="/checkouts"}' \
  | python3 -c '
import json, sys
result = json.load(sys.stdin)["data"]["result"]
print(sum(float(r["value"][1]) for r in result) if result else 0)
')"

curl -fsS -X POST http://127.0.0.1:8080/checkouts \
  -H "Content-Type: application/json" \
  -d '{"sku":"sku_keyboard_001","quantity":1,"amount_cents":2599,"currency":"USD","recipient":"customer@example.com"}' \
  >/dev/null || fail "POST /checkouts (post-recovery regression trigger) failed"

resumed_ok=false
for i in $(seq 1 20); do
  after_count="$(curl -fsS -G "$PROMETHEUS_URL/api/v1/query" \
    --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="checkout-service",http_route="/checkouts"}' \
    | python3 -c '
import json, sys
result = json.load(sys.stdin)["data"]["result"]
print(sum(float(r["value"][1]) for r in result) if result else 0)
')"
  if python3 -c "import sys; sys.exit(0 if $after_count > $before_count else 1)"; then
    resumed_ok=true
    break
  fi
  echo "  attempt $i/20: fresh checkout telemetry not yet reflected in Prometheus (before=$before_count after=$after_count)"
  sleep 3
done
[ "$resumed_ok" = true ] || fail "telemetry did not resume after Collector recovery (checkout-service /checkouts request count did not increase: before=$before_count after=$after_count)"
echo "  telemetry resumed normally: checkout-service /checkouts request count $before_count -> $after_count"

echo ""
echo "ALERT LIFECYCLE VERIFIED: $ALERT_NAME went inactive -> firing (real Collector outage) -> observed in Alertmanager -> recovered -> inactive, and telemetry resumed."
