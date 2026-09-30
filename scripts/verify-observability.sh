#!/usr/bin/env bash
#
# verify-observability.sh — Bundled Phase 2A.1-2B.3 verification.
#
# Starts the full Docker Compose environment, waits for every
# application and observability service to become healthy (with a
# documented exception for otel-collector, whose official image has no
# shell/wget/curl and therefore no Docker-level healthcheck), verifies
# Prometheus's scrape targets and Grafana's Prometheus + Tempo
# datasources, re-runs the POST /checkouts regression check, then checks
# that all four application services' (checkout Phase 2A.2, payment
# Phase 2A.3, inventory Phase 2A.4, notification Phase 2A.5) telemetry
# actually reached Prometheus (application metrics) and the Collector
# (trace spans) — including a deterministic parse
# (scripts/parse-checkout-trace.py) proving that one real checkout trace
# is a complete distributed trace across all three downstream branches
# (checkout->payment, checkout->inventory, checkout->notification —
# siblings, not a sequential chain; shared Trace ID, correct
# parent/child Span IDs on every branch). Phase 2B.1 then independently
# re-verifies that exact same trace directly against Tempo's own HTTP
# query API (scripts/verify-tempo-trace.py), and that it survives a
# graceful Tempo restart using the same tempo_data volume. Phase 2B.2
# then verifies centralized application log collection: Loki and Alloy
# readiness/health, Loki provisioned as a third Grafana datasource, real
# (non-synthetic) logs from all four application services retrieved via
# Loki's own query API (scripts/verify-loki-logs.py, the same validator
# CI uses), and that an already-ingested log entry survives a graceful
# Loki restart using the same loki_data volume while Alloy is stopped
# (ruling out "Alloy just resent it"). Phase 2B.3 then verifies the
# three auto-provisioned Grafana dashboards (Application Health,
# Centralized Logging, Observability Infrastructure) through Grafana's
# real API — correct panels, datasource references, template
# variables — and independently re-executes a curated set of the
# dashboards' own PromQL/LogQL queries directly against Prometheus and
# Loki (scripts/verify-grafana-dashboards.py, the same validator CI
# uses) — then always tears the environment down (without deleting
# volumes) and confirms every named volume, including
# tempo_data/loki_data/alloy_data, still exists.
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
  observability/grafana/provisioning/datasources/datasource.yml \
  observability/loki/loki.yaml \
  observability/alloy/config.alloy \
  scripts/verify-loki-logs.py \
  observability/grafana/provisioning/dashboards/dashboards.yml \
  observability/grafana/provisioning/dashboards/json/application-health.json \
  observability/grafana/provisioning/dashboards/json/centralized-logging.json \
  observability/grafana/provisioning/dashboards/json/observability-infrastructure.json \
  scripts/verify-grafana-dashboards.py
do
  [ -f "$f" ] || fail "missing required config file: $f"
  echo "  found: $f"
done

# --------------------------------------------------------------------
# B. Start environment
# --------------------------------------------------------------------
section "B. Start environment"
# Captured before anything starts, so it pre-dates every container's own
# first log line (including checkout-service's/inventory-service's
# startup-only logs) — used later (section L) as a lower bound so that
# stale log entries left over in the persistent loki_data volume from a
# previous run cannot satisfy this run's "real logs were ingested"
# check. Portable across macOS/Linux: unlike `date +%s%N` (whose `%N`
# is GNU-only and silently prints a literal "N" on macOS/BSD date),
# Python's time.time_ns() behaves identically on both.
run_start_ns="$(python3 -c 'import time; print(time.time_ns())')"
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

for svc in postgres checkout-service payment-service inventory-service notification-service prometheus grafana tempo; do
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
# D. Loki and Alloy readiness/health (Phase 2B.2)
# --------------------------------------------------------------------
section "D. Loki and Alloy readiness/health"

echo "-- Loki (grafana/loki:3.7.8): no Docker health status is possible"
echo "   (official image has no shell/curl/wget and no -health-style CLI"
echo "   flag); verifying readiness functionally via GET /ready instead --"

loki_ready=false
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:3100/ready >/dev/null 2>&1; then
    loki_ready=true
    break
  fi
  echo "  [loki] attempt $i/20: /ready not ready yet"
  sleep 3
done
[ "$loki_ready" = true ] || fail "Loki /ready (127.0.0.1:3100) never responded"
echo "  Loki /ready OK"

echo ""
echo "-- Alloy (grafana/alloy:v1.20.1): has a shell but no curl/wget, so no"
echo "   Docker-level healthcheck either; verifying all 4 pipeline"
echo "   components (discovery.docker, discovery.relabel, loki.source.docker,"
echo "   loki.write) report health.state == healthy via its own debug API --"

alloy_healthy=false
for i in $(seq 1 20); do
  if components_body="$(curl -fsS http://127.0.0.1:12345/api/v0/web/components 2>/dev/null)" \
      && echo "$components_body" | jq -e '
          (length >= 4) and (all(.[]; .health.state == "healthy"))
        ' >/dev/null 2>&1
  then
    alloy_healthy=true
    break
  fi
  echo "  [alloy] attempt $i/20: components not all healthy yet"
  sleep 3
done
[ "$alloy_healthy" = true ] || fail "Alloy components (127.0.0.1:12345/api/v0/web/components) never all reported healthy"
echo "  Alloy components all healthy: $(echo "$components_body" | jq -c '[.[].localID]')"

# --------------------------------------------------------------------
# E. Prometheus
# --------------------------------------------------------------------
section "E. Prometheus"

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
# F. Grafana
# --------------------------------------------------------------------
section "F. Grafana"

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

echo "$datasources_body" | jq -e '
    [.[] | select(.type == "tempo" and .url == "http://tempo:3200")] | length > 0
  ' >/dev/null || fail "Grafana provisioned Tempo datasource not found or misconfigured"
echo "  Grafana Tempo datasource OK (type=tempo, url=http://tempo:3200)"

echo "$datasources_body" | jq -e '
    [.[] | select(.type == "loki" and .url == "http://loki:3100")] | length > 0
  ' >/dev/null || fail "Grafana provisioned Loki datasource not found or misconfigured"
echo "  Grafana Loki datasource OK (type=loki, url=http://loki:3100)"

# --------------------------------------------------------------------
# G. Regression: POST /checkouts
# --------------------------------------------------------------------
section "G. Regression: POST /checkouts"

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
# H. Observability: checkout-service application metrics in Prometheus
# --------------------------------------------------------------------
section "H. Observability: checkout-service application metrics in Prometheus"

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

echo ""
echo "-- waiting for payment-service metrics to reach Prometheus (Phase"
echo "   2A.3; same async export/scrape considerations as above) --"

payment_metrics_ok=false
for i in $(seq 1 20); do
  if payment_body="$(curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
        --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="payment-service",http_route="/payments/authorize"}' 2>/dev/null)" \
      && echo "$payment_body" | jq -e '.data.result | length > 0' >/dev/null 2>&1
  then
    payment_metrics_ok=true
    break
  fi
  echo "  attempt $i/20: payment-service HTTP server metrics not in Prometheus yet"
  sleep 3
done
[ "$payment_metrics_ok" = true ] || fail "payment-service HTTP server metrics never appeared in Prometheus"
echo "  payment-service HTTP server metrics present (http_server_request_duration_seconds_count, service_name=payment-service, http_route=/payments/authorize)"

echo ""
echo "-- waiting for inventory-service metrics to reach Prometheus (Phase"
echo "   2A.4; same async export/scrape considerations as above) --"

inventory_metrics_ok=false
for i in $(seq 1 20); do
  if inventory_body="$(curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
        --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="inventory-service",http_route="/inventory/reservations"}' 2>/dev/null)" \
      && echo "$inventory_body" | jq -e '.data.result | length > 0' >/dev/null 2>&1
  then
    inventory_metrics_ok=true
    break
  fi
  echo "  attempt $i/20: inventory-service HTTP server metrics not in Prometheus yet"
  sleep 3
done
[ "$inventory_metrics_ok" = true ] || fail "inventory-service HTTP server metrics never appeared in Prometheus"
echo "  inventory-service HTTP server metrics present (http_server_request_duration_seconds_count, service_name=inventory-service, http_route=/inventory/reservations)"

echo ""
echo "-- waiting for notification-service metrics to reach Prometheus (Phase"
echo "   2A.5; same async export/scrape considerations as above) --"

notification_metrics_ok=false
for i in $(seq 1 20); do
  if notification_body="$(curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
        --data-urlencode 'query=http_server_request_duration_seconds_count{service_name="notification-service",http_route="/notifications"}' 2>/dev/null)" \
      && echo "$notification_body" | jq -e '.data.result | length > 0' >/dev/null 2>&1
  then
    notification_metrics_ok=true
    break
  fi
  echo "  attempt $i/20: notification-service HTTP server metrics not in Prometheus yet"
  sleep 3
done
[ "$notification_metrics_ok" = true ] || fail "notification-service HTTP server metrics never appeared in Prometheus"
echo "  notification-service HTTP server metrics present (http_server_request_duration_seconds_count, service_name=notification-service, http_route=/notifications)"

# --------------------------------------------------------------------
# I. Observability: trace evidence + complete checkout distributed
#    trace (all three downstream branches) in Collector logs
# --------------------------------------------------------------------
section "I. Observability: trace evidence + complete checkout distributed trace"

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

echo ""
echo "-- Phase 2A.5: proving a COMPLETE distributed trace across all three"
echo "   downstream branches of ONE checkout trace — checkout SERVER ->"
echo "   {payment CLIENT -> payment SERVER}, {inventory CLIENT -> inventory"
echo "   SERVER}, and {notification CLIENT -> notification SERVER}, all as"
echo "   siblings (not a sequential payment->inventory->notification"
echo "   chain) — using a small deterministic parser, not a brittle"
echo "   grep-only heuristic --"

checkout_trace_match=""
for i in $(seq 1 20); do
  if checkout_trace_match="$(docker compose logs --no-log-prefix otel-collector 2>/dev/null | python3 scripts/parse-checkout-trace.py)"; then
    break
  fi
  checkout_trace_match=""
  echo "  attempt $i/20: complete checkout distributed trace correlation (payment + inventory + notification branches) not found yet"
  sleep 3
done
[ -n "$checkout_trace_match" ] || fail "checkout SERVER -> {payment,inventory,notification} SERVER correlation (shared Trace ID, matching Parent/Span IDs on every branch) was never found in Collector logs"
echo "  complete checkout distributed trace confirmed (payment + inventory + notification branches): $checkout_trace_match"

# --------------------------------------------------------------------
# J. Observability: retrieve and validate the real checkout trace
#    directly from Tempo (Phase 2B.1)
# --------------------------------------------------------------------
section "J. Observability: retrieve and validate the real checkout trace from Tempo"

echo "-- Collector -> Tempo export and Tempo's own ingest-to-query path are"
echo "   both asynchronous, so this is retried. Reuses the exact Trace ID"
echo "   and seven Span IDs already confirmed via the Collector logs above,"
echo "   independently re-verifying them against Tempo's own stored data"
echo "   (GET /api/v2/traces/{traceID}), not just trusting the same IDs"
echo "   exist somewhere --"

tempo_trace_match=""
for i in $(seq 1 20); do
  if tempo_trace_match="$(python3 scripts/verify-tempo-trace.py --tempo-url http://127.0.0.1:3200 "$checkout_trace_match" 2>/dev/null)"; then
    break
  fi
  tempo_trace_match=""
  echo "  attempt $i/20: checkout trace not yet retrievable/valid from Tempo"
  sleep 3
done
[ -n "$tempo_trace_match" ] || fail "Tempo never served the real checkout trace with all seven spans and correct parent/child relationships (GET /api/v2/traces/${checkout_trace_match%% *} at http://127.0.0.1:3200)"
echo "  $tempo_trace_match"

# --------------------------------------------------------------------
# K. Observability: Tempo trace persistence across a graceful restart
# --------------------------------------------------------------------
section "K. Observability: Tempo trace persistence across a graceful restart"

echo "-- restarting the tempo container (same tempo_data volume) to prove"
echo "   the already-ingested checkout trace survives, not just that the"
echo "   named volume exists — Tempo's live-store writes ingested spans to"
echo "   disk incrementally (confirmed by inspecting the volume directly),"
echo "   so a trace ingested and already queryable before this restart is"
echo "   expected to remain retrievable afterward; a trace ingested only"
echo "   milliseconds before a restart is a narrower race this check does"
echo "   not specifically stress-test --"

docker compose restart tempo >/dev/null
tempo_restart_ok=false
for i in $(seq 1 20); do
  cid="$(docker compose ps -q tempo)"
  health="$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
  echo "  [tempo] attempt $i/20: health=$health"
  if [ "$health" = "healthy" ]; then
    tempo_restart_ok=true
    break
  fi
  sleep 3
done
[ "$tempo_restart_ok" = true ] || fail "tempo did not become healthy again after restart"

tempo_trace_after_restart=""
for i in $(seq 1 20); do
  if tempo_trace_after_restart="$(python3 scripts/verify-tempo-trace.py --tempo-url http://127.0.0.1:3200 "$checkout_trace_match" 2>/dev/null)"; then
    break
  fi
  tempo_trace_after_restart=""
  echo "  attempt $i/20: checkout trace not yet retrievable/valid from Tempo after restart"
  sleep 3
done
[ -n "$tempo_trace_after_restart" ] || fail "the checkout trace already confirmed in Tempo before the restart was not retrievable (with all seven spans and correct relationships) after a graceful Tempo restart using the same tempo_data volume"
echo "  trace persistence across restart confirmed: $tempo_trace_after_restart"

# --------------------------------------------------------------------
# L. Observability: real application logs in Loki (Phase 2B.2)
# --------------------------------------------------------------------
section "L. Observability: real application logs in Loki"

echo "-- verifying genuine, non-synthetic log output from all four"
echo "   application services was actually collected through the Alloy ->"
echo "   Loki pipeline (Docker log discovery/shipping and Loki indexing"
echo "   are both asynchronous, so this is retried); uses the same"
echo "   validator (scripts/verify-loki-logs.py) that CI uses. --after-ns"
echo "   \$run_start_ns (captured in section B, before anything started)"
echo "   requires each service's evidence to be newer than that, so a"
echo "   stale entry left over in the persistent loki_data volume from an"
echo "   earlier run cannot satisfy this check on its own --"

loki_logs_ok=false
for i in $(seq 1 20); do
  if python3 scripts/verify-loki-logs.py --loki-url http://127.0.0.1:3100 --since-seconds 1800 --after-ns "$run_start_ns"; then
    loki_logs_ok=true
    break
  fi
  echo "  attempt $i/20: real, fresh logs for all four services not yet queryable from Loki"
  sleep 3
done
[ "$loki_logs_ok" = true ] || fail "scripts/verify-loki-logs.py never confirmed real, fresh logs from all four application services in Loki"

# --------------------------------------------------------------------
# M. Observability: Loki log persistence across a graceful restart
# --------------------------------------------------------------------
section "M. Observability: Loki log persistence across a graceful restart"

echo "-- proving one exact, already-ingested log entry survives a graceful"
echo "   Loki restart using the same loki_data volume — not just that the"
echo "   named volume exists, and not just that SOME entry matching a"
echo "   substring exists (inventory-service's startup line is identical"
echo "   text on every restart, so a substring match alone could be"
echo "   satisfied by a different occurrence of the same message — this"
echo "   captures and later re-checks one specific (service, full message,"
echo "   original nanosecond timestamp) triple). Alloy is stopped first so"
echo "   it cannot resend the entry after Loki comes back; inventory-service"
echo "   is used as the source because it logs exactly once per container"
echo "   lifetime, at startup, making its most recent line a stable,"
echo "   known-good fixture for this check --"

inventory_startup_line="inventory-service listening on"
persist_capture_ok=false
inventory_capture=""
for i in $(seq 1 20); do
  if inventory_capture="$(python3 scripts/verify-loki-logs.py --loki-url http://127.0.0.1:3100 \
       --capture-exact --service inventory-service --line-contains "$inventory_startup_line" --since-seconds 1800)"
  then
    persist_capture_ok=true
    break
  fi
  inventory_capture=""
  echo "  attempt $i/20: inventory-service startup log not yet found in Loki"
  sleep 3
done
[ "$persist_capture_ok" = true ] || fail "inventory-service startup log line was never found in Loki before the restart test"
echo "  captured exact entry: $inventory_capture"

echo ""
echo "-- stopping alloy (so it cannot resend/reship anything), then"
echo "   gracefully restarting loki (same loki_data volume, not removed) --"
docker compose stop alloy >/dev/null
docker compose restart loki >/dev/null

loki_restart_ready=false
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:3100/ready >/dev/null 2>&1; then
    loki_restart_ready=true
    break
  fi
  echo "  [loki] attempt $i/20: /ready not ready yet after restart"
  sleep 3
done
[ "$loki_restart_ready" = true ] || fail "Loki /ready never responded after restart"
echo "  Loki /ready OK after restart"

echo ""
echo "-- re-querying Loki (Alloy still stopped) for that exact same"
echo "   captured (service, full message, timestamp) triple, to confirm it"
echo "   survived the restart via loki_data — not because Alloy resent it,"
echo "   and not a false match against some other occurrence of the same"
echo "   recurring message text --"
persist_after_restart_ok=false
for i in $(seq 1 20); do
  if python3 scripts/verify-loki-logs.py --loki-url http://127.0.0.1:3100 \
       --verify-exact "$inventory_capture" --since-seconds 1800
  then
    persist_after_restart_ok=true
    break
  fi
  echo "  attempt $i/20: exact inventory-service startup log entry not yet retrievable after restart"
  sleep 3
done
[ "$persist_after_restart_ok" = true ] || fail "the exact captured inventory-service startup log entry (same timestamp, same full message) did not survive the graceful Loki restart (loki_data volume), or Alloy (still stopped) was somehow required for it to reappear"
echo "  Loki log persistence across restart confirmed (exact captured inventory-service entry survived; Alloy was stopped throughout)"

echo ""
echo "-- restarting alloy and confirming its pipeline becomes healthy again --"
docker compose start alloy >/dev/null

alloy_restart_healthy=false
for i in $(seq 1 20); do
  if components_body="$(curl -fsS http://127.0.0.1:12345/api/v0/web/components 2>/dev/null)" \
      && echo "$components_body" | jq -e '
          (length >= 4) and (all(.[]; .health.state == "healthy"))
        ' >/dev/null 2>&1
  then
    alloy_restart_healthy=true
    break
  fi
  echo "  [alloy] attempt $i/20: components not all healthy yet after restart"
  sleep 3
done
[ "$alloy_restart_healthy" = true ] || fail "Alloy components never all reported healthy again after restart"
echo "  Alloy components all healthy again after restart"

echo ""
echo "-- capturing a nanosecond timestamp immediately BEFORE triggering one"
echo "   more real checkout (portable: Python's time.time_ns(), not"
echo "   \`date +%s%N\`, whose %N is GNU-only and silently broken on macOS/"
echo "   BSD date), then requiring payment-service's and"
echo "   notification-service's (which log per-request) evidence to be"
echo "   strictly newer than that instant — not merely present somewhere"
echo "   in a several-minute lookback window, which a stale pre-restart"
echo "   entry could also satisfy — to prove log collection actually"
echo "   resumed after the Alloy restart, not just that the alloy"
echo "   container is running --"
resume_check_ns="$(python3 -c 'import time; print(time.time_ns())')"
curl -fsS -X POST http://127.0.0.1:8080/checkouts \
  -H 'Content-Type: application/json' \
  -d '{"sku":"sku_keyboard_001","quantity":1,"amount_cents":2599,"currency":"USD","recipient":"customer@example.com"}' \
  >/dev/null || fail "POST /checkouts (post-Alloy-restart regression trigger) failed"

resumed_collection_ok=false
for i in $(seq 1 20); do
  if python3 scripts/verify-loki-logs.py --loki-url http://127.0.0.1:3100 \
       --services payment-service,notification-service --after-ns "$resume_check_ns" --since-seconds 600
  then
    resumed_collection_ok=true
    break
  fi
  echo "  attempt $i/20: fresh post-restart logs from payment-service/notification-service not yet in Loki"
  sleep 3
done
[ "$resumed_collection_ok" = true ] || fail "log collection did not resume after the Alloy restart (no payment-service/notification-service log entry newer than the pre-request timestamp reached Loki)"
echo "  log collection resumed after Alloy restart (fresh payment-service and notification-service logs, newer than the pre-request timestamp, confirmed in Loki)"

# --------------------------------------------------------------------
# N. Observability: Grafana dashboards (Phase 2B.3)
# --------------------------------------------------------------------
section "N. Observability: Grafana dashboards"

echo "-- verifying the three provisioned dashboards (Application Health,"
echo "   Centralized Logging, Observability Infrastructure) through"
echo "   Grafana's real authenticated API: correct panels, correct"
echo "   datasource references, valid template variables, and that a"
echo "   curated set of the dashboards' own PromQL/LogQL queries execute"
echo "   successfully with real data when re-run directly against"
echo "   Prometheus/Loki (not just that the dashboard JSON exists) --"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-local_dev_only_change_me}"

dashboards_ok=false
for i in $(seq 1 20); do
  if python3 scripts/verify-grafana-dashboards.py \
       --grafana-url http://127.0.0.1:3000 \
       --user "$GRAFANA_ADMIN_USER" --password "$GRAFANA_ADMIN_PASSWORD" \
       --prometheus-url http://127.0.0.1:9090 \
       --loki-url http://127.0.0.1:3100
  then
    dashboards_ok=true
    break
  fi
  echo "  attempt $i/20: Grafana dashboards not yet fully verifiable"
  sleep 3
done
[ "$dashboards_ok" = true ] || fail "scripts/verify-grafana-dashboards.py never confirmed all three provisioned dashboards (structure, datasources, variables, and live underlying queries)"

# --------------------------------------------------------------------
# O. Container/log sanity
# --------------------------------------------------------------------
section "O. Container/log sanity"

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
echo ""
echo "-- tempo logs (last 50 lines) --"
docker compose logs --tail=50 tempo
echo ""
echo "-- loki logs (last 50 lines) --"
docker compose logs --tail=50 loki
echo ""
echo "-- alloy logs (last 50 lines) --"
docker compose logs --tail=50 alloy

echo ""
echo "-- checking for persistent (non-transient) Collector->Tempo export"
echo "   errors — brief connection-refused/retry warnings during the"
echo "   restart above are expected and already tolerated; only flag an"
echo "   export failure still recurring in the most recent log lines --"
if docker compose logs --tail=20 otel-collector 2>&1 | grep -q 'otlp_grpc/tempo'; then
  if docker compose logs --tail=20 otel-collector 2>&1 | grep 'otlp_grpc/tempo' | grep -qi 'error\|fail\|refused'; then
    fail "otel-collector is still reporting Collector->Tempo export errors in its most recent logs"
  fi
fi
echo "  no persistent Collector->Tempo export errors in the most recent logs"

echo ""
echo "-- checking for persistent (non-transient) Alloy->Loki log-shipping"
echo "   errors — brief connection-refused/retry warnings around the Loki"
echo "   restart above are expected and already tolerated; only flag an"
echo "   error still recurring in the most recent log lines --"
if docker compose logs --tail=20 alloy 2>&1 | grep -qi 'error\|fail\|refused'; then
  fail "alloy is still reporting log-shipping errors in its most recent logs"
fi
echo "  no persistent Alloy->Loki log-shipping errors in the most recent logs"

# --------------------------------------------------------------------
# P. Persistence after cleanup
# --------------------------------------------------------------------
section "P. Persistence after cleanup"

echo "-- docker compose down (preserving volumes) --"
docker compose down
# Teardown already happened above; disable the trap so it doesn't run
# (and log a confusing duplicate teardown) on normal exit.
trap - EXIT

echo ""
echo "-- resolving the actual named volumes to check from Docker Compose's"
echo "   own resolved configuration, rather than a hard-coded"
echo "   'autonomous-reliability-platform_*' prefix — alloy now runs with"
echo "   whatever COMPOSE_PROJECT_NAME this invocation actually resolves"
echo "   to (see observability/alloy/config.alloy), so the volume names"
echo "   this check looks for must track the same effective project,"
echo "   not an assumed literal one --"
compose_project_name="$(docker compose config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])')"
[ -n "$compose_project_name" ] || fail "could not resolve the effective Compose project name from 'docker compose config'"
echo "  resolved Compose project name: $compose_project_name"

for logical_vol in postgres_data prometheus_data grafana_data tempo_data loki_data alloy_data; do
  match="$(docker volume ls \
    --filter "label=com.docker.compose.project=$compose_project_name" \
    --filter "label=com.docker.compose.volume=$logical_vol" \
    --format '{{.Name}}')"
  [ -n "$match" ] || fail "expected named volume missing after teardown: project=$compose_project_name logical_name=$logical_vol"
  echo "  volume present: $match (project=$compose_project_name, logical name=$logical_vol)"
done

section "SUCCESS"
echo "Phase 2A.1-2B.3 observability verification passed."
