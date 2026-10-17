#!/usr/bin/env bash
#
# verify-failure-simulation.sh — Phase 4 real acceptance: runs both
# controlled failure scenarios against the real, running Compose
# stack via scripts/simulate-failure.sh.
#
# - payment-outage is run WITH --full-acceptance: this is the one,
#   single expensive full-alert-lifecycle simulation for this phase
#   (real Prometheus CheckoutServerErrors firing -> real Alertmanager
#   webhook -> persisted incident -> restoration -> real recovery ->
#   genuine automatic resolution -> correctly-attributed audit trail).
# - inventory-outage is run WITHOUT --full-acceptance: its own
#   deterministic failure/recovery assertions (safe 502 identifying
#   inventory-service, payment genuinely completing, notification
#   never being called) do not require a second expensive full-alert
#   simulation, per this phase's own scope.
#
# All actual scenario logic — safety allowlisting, fault injection,
# assertions, restoration, reporting — lives in
# scripts/simulate-failure.sh; this script only sequences the two
# runs and confirms the prerequisites (webhook secret, control-plane
# readiness) that the full-acceptance run depends on. No incident or
# audit row is ever deleted by either run.
#
# Intended to run AFTER `make verify-alert-ingestion` (the existing
# Phase 2B.4/3C-3E Collector-outage gate) in both CI and local use, so
# it cannot interfere with that gate's own preconditions.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# wait_for_checkout_server_errors_clean [max_attempts] [sleep_seconds]
#
# Bounded, condition-based polling (never a fixed sleep) via the
# existing, authoritative scripts/verify-alerting.py "recovered"
# subcommand -- never a second, duplicated parsing of Prometheus/
# Alertmanager's own responses. Returns 0 the first time that helper
# confirms CheckoutServerErrors is fully clean (Prometheus rule state
# == inactive, its own alerts list empty, AND Alertmanager has no
# active unresolved match); returns 1 if it never does within
# max_attempts. Extracted as its own function (rather than inlined)
# so scripts/test-failure-simulation-settling.sh can exercise this
# exact polling/attempt-counting logic with a stubbed `python3`,
# without sleeping for real or needing a running stack.
wait_for_checkout_server_errors_clean() {
  local max_attempts="${1:-90}" sleep_seconds="${2:-5}"
  local attempt
  for attempt in $(seq 1 "$max_attempts"); do
    if python3 "$SCRIPT_DIR/verify-alerting.py" recovered \
         --prometheus-url "$PROMETHEUS_URL" \
         --alertmanager-url "$ALERTMANAGER_URL" \
         --alert CheckoutServerErrors
    then
      return 0
    fi
    echo "  attempt $attempt/$max_attempts: CheckoutServerErrors has not naturally returned to a clean inactive state yet"
    sleep "$sleep_seconds"
  done
  return 1
}

section "0. Prepare secrets; confirm postgres + control-plane ready"
./scripts/init-webhook-secret.sh
docker compose up -d control-plane >/dev/null

cp_ready=false
for i in $(seq 1 20); do
  status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/health/ready" || echo 000)"
  [ "$status" = "200" ] && cp_ready=true && break
  echo "  attempt $i/20: control-plane GET /health/ready -> $status"
  sleep 3
done
[ "$cp_ready" = true ] || fail "control-plane readiness never reached 200 before the failure-simulation acceptance test began"
echo "  control-plane ready"

section "1. Scenario: payment-outage (full acceptance -- the one expensive full-alert simulation)"
"$SCRIPT_DIR/simulate-failure.sh" payment-outage --full-acceptance

section "2. Scenario: inventory-outage (deterministic failure/recovery only -- no second full-alert simulation)"
"$SCRIPT_DIR/simulate-failure.sh" inventory-outage

section "3. Confirm shared CheckoutServerErrors state is clean after inventory-outage"
# inventory-outage's own real checkout request(s) genuinely fail
# through checkout-service (a real HTTP 5xx, by design -- see
# simulate-failure.sh's own assertions above), which feeds the SAME
# shared CheckoutServerErrors Prometheus rule payment-outage already
# exercised. That rule's expression is a 5-minute rate() window with a
# 2-minute `for:` -- a single recent failing request can leave it
# "pending" (or even "firing") for several real minutes afterward, long
# after inventory-outage's own deterministic assertions have already
# passed. Phase 8 (scripts/verify-remediation.sh) deliberately REQUIRES
# this same shared alert to be genuinely "inactive" before it ever
# starts, so this phase must not declare itself complete -- and hand
# off to whatever runs next -- while leaving that shared alert dirty.
# Bounded, condition-based polling (never a fixed sleep); the 90 x 5s
# budget mirrors simulate-failure.sh's own documented real-decay
# precedent for this exact alert.
if wait_for_checkout_server_errors_clean 90 5; then
  echo "  CheckoutServerErrors confirmed clean after inventory-outage"
else
  fail "CheckoutServerErrors did not return to a clean inactive state after the inventory-outage scenario"
fi

echo ""
echo "PHASE 4 FAILURE-SIMULATION ACCEPTANCE VERIFIED: payment-outage proved the complete real chain (outage -> failed checkouts -> Prometheus CheckoutServerErrors firing -> real Alertmanager webhook -> persisted incident -> restoration -> recovery -> automatic resolution -> correctly-attributed audit trail); inventory-outage proved its own deterministic failure (correct dependency identified, payment completed, notification short-circuited) and recovery; the shared CheckoutServerErrors alert was confirmed to have naturally returned to a clean inactive state afterward, so later phases (including Phase 8's own strict baseline requirement) start from clean shared alerting state."
