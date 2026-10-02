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
# As of Phase 3C, setting VERIFY_INGESTION=true additionally proves —
# using this SAME real, controlled Collector outage, not a second one
# — that Alertmanager's real webhook delivery (not a synthetic POST
# from this script) persisted the firing alert as a genuine
# reliability.incidents row, correctly mapped, with one distinct
# incident per active alert instance. As of Phase 3D, the SAME flag
# additionally proves that once the Collector recovers and Alertmanager
# resolves, its real resolved webhook delivery (send_resolved: true)
# actually transitions that exact incident to status=resolved with
# resolved_at populated — never a simulated resolution. As of Phase
# 3E, the SAME flag additionally proves that this exact real chain
# produced a genuine, correctly-attributed audit trail — a 'created'
# event and a resolving 'status_transition' event, both attributed to
# actor_type='alertmanager', with no fabricated operator intervention
# (see scripts/verify-ingestion.py's confirm-resolved subcommand).
# Default (unset/false) preserves the original Phase 2B.4-only behavior
# exactly, including when called from scripts/verify-observability.sh.
# See scripts/verify-ingestion.py for the HTTP-API cross-checking logic
# (also not duplicated here) and `make verify-alert-ingestion` for the
# wrapped invocation.
#
# Safe to source ALERT_NAME/PROMETHEUS_URL/ALERTMANAGER_URL/
# CONTROL_PLANE_URL/VERIFY_INGESTION from the environment; otherwise
# defaults to the deterministic TelemetryPipelineUnavailable rule
# against the standard local ports, with ingestion assertions off.
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
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
ALERT_NAME="${ALERT_NAME:-TelemetryPipelineUnavailable}"
VERIFY_INGESTION="${VERIFY_INGESTION:-false}"

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

if [ "$VERIFY_INGESTION" = "true" ]; then
  section "1b. (Phase 3C) Prepare webhook secret; confirm control-plane ready"

  ./scripts/init-webhook-secret.sh
  # Recreates control-plane only if CONTROL_PLANE_WEBHOOK_TOKEN changed
  # since it last started (Compose's own config-diff detection) — a
  # freshly-generated secret always actually reaches a running
  # process, with no manual restart needed.
  docker compose up -d control-plane

  cp_ready=false
  for i in $(seq 1 20); do
    status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/health/ready" || echo 000)"
    [ "$status" = "200" ] && cp_ready=true && break
    echo "  attempt $i/20: control-plane GET /health/ready -> $status"
    sleep 3
  done
  [ "$cp_ready" = true ] || fail "control-plane readiness never reached 200 before the ingestion-enabled lifecycle test began"
  echo "  control-plane ready to receive the real Alertmanager webhook"

  # Captured now, before the controlled failure begins — passed to
  # scripts/verify-ingestion.py as the freshness floor an incident's
  # last_seen_at must meet, so a PRE-EXISTING incident from an earlier
  # genuine outage (tolerated, never deleted) cannot be mistaken for
  # proof that THIS run's webhook delivery actually happened.
  ingestion_since="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
fi

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

if [ "$VERIFY_INGESTION" = "true" ]; then
  section "7b. (Phase 3C) Confirm the real Alertmanager webhook created/updated a persistent incident"

  echo "-- waiting for genuine webhook delivery: Alertmanager's own group_wait"
  echo "   (10s, see observability/alertmanager/alertmanager.yml) plus real HTTP"
  echo "   delivery and ingestion time — polling scripts/verify-ingestion.py,"
  echo "   which only reads Alertmanager's and control-plane's own HTTP APIs and"
  echo "   never posts anything itself, so this is proof of the real"
  echo "   Prometheus -> Alertmanager -> webhook -> PostgreSQL chain, not a test"
  echo "   helper inserting rows directly --"

  # Captured so section 12b below (Phase 3D) can confirm these EXACT
  # incidents — not merely "some incident" — genuinely transition to
  # resolved once Alertmanager delivers its own real resolved webhook.
  ingestion_ids_file="$(mktemp)"

  ingestion_ok=false
  for i in $(seq 1 30); do
    if python3 scripts/verify-ingestion.py incident-from-alert \
         --alert "$ALERT_NAME" --prometheus-url "$PROMETHEUS_URL" \
         --alertmanager-url "$ALERTMANAGER_URL" \
         --control-plane-url "$CONTROL_PLANE_URL" --since "$ingestion_since" \
         --ids-out "$ingestion_ids_file"
    then
      ingestion_ok=true
      break
    fi
    echo "  attempt $i/30: incident not yet confirmed for $ALERT_NAME via the real webhook path"
    sleep 3
  done
  [ "$ingestion_ok" = true ] || fail "the real Alertmanager webhook never resulted in a confirmed, correctly-mapped reliability.incidents row for $ALERT_NAME"
fi

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

if [ "$VERIFY_INGESTION" = "true" ]; then
  section "12b. (Phase 3D/3E) Confirm the real Alertmanager resolved webhook actually resolved the matching incident(s), with a genuine, correctly-attributed audit trail"

  echo "-- Alertmanager has already delivered its own real resolved webhook"
  echo "   as part of reaching the 'recovered' state confirmed above (send_resolved:"
  echo "   true, see observability/alertmanager/alertmanager.yml) — polling"
  echo "   scripts/verify-ingestion.py confirm-resolved, which only reads"
  echo "   control-plane's own HTTP API, so this is proof of the real"
  echo "   Collector recovery -> Prometheus resolves -> Alertmanager resolved"
  echo "   webhook -> incident resolved chain, not a simulated resolution — and,"
  echo "   as of Phase 3E, also confirms each incident's real, persisted audit"
  echo "   timeline shows a 'created' event and a resolving 'status_transition'"
  echo "   event, both attributed to actor_type='alertmanager', with no"
  echo "   fabricated operator intervention --"

  resolution_ok=false
  for i in $(seq 1 20); do
    if python3 scripts/verify-ingestion.py confirm-resolved \
         --ids-file "$ingestion_ids_file" --control-plane-url "$CONTROL_PLANE_URL" --since "$ingestion_since"
    then
      resolution_ok=true
      break
    fi
    echo "  attempt $i/20: incident(s) not yet confirmed resolved (with a genuine audit trail) via the real webhook path"
    sleep 3
  done
  rm -f "$ingestion_ids_file"
  [ "$resolution_ok" = true ] || fail "the real Alertmanager resolved webhook never resulted in the matching incident(s) transitioning to resolved with a genuine audit trail"
fi

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
if [ "$VERIFY_INGESTION" = "true" ]; then
  echo "ALERT LIFECYCLE + INGESTION + RESOLUTION + AUDIT VERIFIED: $ALERT_NAME went inactive -> firing (real Collector outage) -> observed in Alertmanager -> delivered via its real webhook -> persisted as reliability.incidents row(s), correctly mapped, with a genuine 'created' audit event -> recovered -> inactive -> Alertmanager's real resolved webhook delivered -> matching incident(s) transitioned to resolved with resolved_at populated and a genuine, correctly-attributed resolving audit event, and telemetry resumed."
else
  echo "ALERT LIFECYCLE VERIFIED: $ALERT_NAME went inactive -> firing (real Collector outage) -> observed in Alertmanager -> recovered -> inactive, and telemetry resumed."
fi
