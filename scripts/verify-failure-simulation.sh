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

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
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

echo ""
echo "PHASE 4 FAILURE-SIMULATION ACCEPTANCE VERIFIED: payment-outage proved the complete real chain (outage -> failed checkouts -> Prometheus CheckoutServerErrors firing -> real Alertmanager webhook -> persisted incident -> restoration -> recovery -> automatic resolution -> correctly-attributed audit trail); inventory-outage proved its own deterministic failure (correct dependency identified, payment completed, notification short-circuited) and recovery."
