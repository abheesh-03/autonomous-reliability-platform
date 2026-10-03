#!/usr/bin/env bash
#
# simulate-failure.sh — Phase 4 controlled failure-injection scenario
# runner.
#
# Deliberately causes a REAL application failure against this
# repository's own Docker Compose checkout application (never a
# synthetic incident: no direct SQL insert into reliability.incidents,
# no fake POST to Alertmanager), observes the real symptom, verifies
# the expected safe behavior, restores the environment, and (for
# payment-outage --full-acceptance) proves the complete existing
# Phase 2/3 platform reacts to it — real Prometheus alert -> real
# Alertmanager webhook -> persisted incident -> real recovery ->
# genuine automatic resolution -> correctly-attributed audit trail.
#
# Usage:
#   scripts/simulate-failure.sh payment-outage [--full-acceptance]
#   scripts/simulate-failure.sh inventory-outage
#
# Safety (see docs/architecture/phase-4-failure-simulation.md for the
# full rationale):
#   - SCENARIO must be exactly one of the two names allowlisted below
#     in the `case` statement — anything else is refused before any
#     Docker or network action is taken. There is no code path that
#     derives a Compose service name from arbitrary user input; the
#     allowlist IS the only mapping.
#   - Only payment-service or inventory-service is ever stopped.
#     postgres, and every other Compose service, is never touched —
#     enforced both by the allowlist above and a redundant explicit
#     guard below.
#   - --full-acceptance is only accepted for payment-outage.
#   - NEEDS_RESTORE is set true BEFORE the stop command is even issued
#     (not after it returns), so a stop that fails partway through, or
#     is interrupted mid-command, is still treated as needing cleanup —
#     `docker compose start` on a container that was never actually
#     stopped (or is left in a half-stopped state) is a safe, idempotent
#     no-op/recovery either way.
#   - Exactly ONE place ever calls restore_target: the single EXIT trap.
#     INT/TERM handlers only set the right conventional exit code and
#     `exit` — that exit itself triggers the EXIT trap, so cleanup never
#     runs twice (no recursive cleanup) and INT/TERM are never silently
#     swallowed. NEEDS_RESTORE is cleared ONLY after `wait_healthy`
#     actually confirms the dependency healthy again — a restoration
#     that cannot be verified healthy is reported as a failure (a
#     nonzero exit status is forced even if the scenario itself had
#     otherwise succeeded) and is never papered over as success.
#   - SIGKILL (`kill -9`) and power loss cannot be trapped by any shell
#     script — this is a real, honestly-acknowledged limit of this
#     mechanism, not a guarantee this script makes. If that happens
#     while a dependency is stopped, it stays stopped until a human
#     runs `docker compose start <service>` manually.
#   - No volume is ever touched; no incident or audit row is ever
#     deleted by this script.
#   - Nothing in this script requires or prints a Bearer token or any
#     other secret — every endpoint it calls is either unauthenticated
#     (checkout-service, Prometheus, Alertmanager) or read-only
#     against control-plane's existing unauthenticated GET API, via
#     the existing scripts/verify-ingestion.py.
#
# This file defines functions only; the actual scenario only runs when
# this file is executed directly (guarded at the very bottom), so
# scripts/test-simulate-failure.sh can `source` it to unit-test the
# argument-parsing/safety/restoration logic without touching Docker.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

CHECKOUT_URL="${CHECKOUT_URL:-http://127.0.0.1:8080}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"

# Deliberately NOT environment-overridable: payment-outage's full
# acceptance must always exercise this exact, specific real alert rule
# -- never an unrelated one an environment variable could accidentally
# redirect it to.
readonly PAYMENT_OUTAGE_ALERT_NAME="CheckoutServerErrors"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# --- State shared with the restore trap -------------------------------
SCENARIO=""
TARGET_SERVICE=""
FULL_ACCEPTANCE=false
# True from the moment a stop is ABOUT to be attempted until a restore
# has been VERIFIED healthy -- never merely "attempted". See the EXIT
# trap below.
NEEDS_RESTORE=false
IDS_FILE=""

# wait_healthy <compose-service> [attempts]
# Polls this repository's own Docker-level healthcheck for the named
# Compose service (the same `docker inspect --format={{.State.Health.Status}}`
# convention CI already uses) until it reports "healthy", or returns 1
# after the bounded attempt budget. Never assumes health from a bare
# "start" having been issued.
wait_healthy() {
  local service="$1" attempts="${2:-20}"
  local i cid health
  for i in $(seq 1 "$attempts"); do
    cid="$(docker compose -f "$REPO_ROOT/docker-compose.yml" ps -q "$service" 2>/dev/null || true)"
    health="$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
    if [ "$health" = "healthy" ]; then
      return 0
    fi
    echo "  attempt $i/$attempts: $service health=${health:-<no container>}"
    sleep 3
  done
  return 1
}

# do_checkout
# Issues one real POST /checkouts request. Never uses curl's -f, since
# a 502 is an expected, asserted-on outcome here, not a transport
# error. Sets the globals CHECKOUT_STATUS / CHECKOUT_BODY.
do_checkout() {
  local tmp status
  tmp="$(mktemp)"
  status="$(curl -sS -o "$tmp" -w '%{http_code}' --connect-timeout 5 --max-time 15 -X POST "$CHECKOUT_URL/checkouts" \
    -H "Content-Type: application/json" \
    -d '{"sku":"sku_keyboard_001","quantity":1,"amount_cents":2599,"currency":"USD","recipient":"customer@example.com"}' \
    2>/dev/null || echo "000")"
  CHECKOUT_STATUS="$status"
  CHECKOUT_BODY="$(cat "$tmp" 2>/dev/null || true)"
  rm -f "$tmp"
}

# assert_checkout_failed_with <expected_service>
# Asserts the CURRENT CHECKOUT_STATUS/CHECKOUT_BODY (set by the most
# recent do_checkout) are EXACTLY the safe downstream_failure contract
# for the given service. Used both for one-off checks and for every
# single attempt of payment-outage's sustained-traffic loop, so a
# response that unexpectedly stops matching (the dependency recovering
# mid-outage, or failing a different way) aborts immediately rather
# than being silently logged as if it were still proof of the outage.
assert_checkout_failed_with() {
  local expected_service="$1"
  [ "$CHECKOUT_STATUS" = "502" ] || fail "expected HTTP 502 from $expected_service, got $CHECKOUT_STATUS (body=$CHECKOUT_BODY)"
  echo "$CHECKOUT_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
assert b == {'error': 'downstream_failure', 'service': '$expected_service', 'message': 'Downstream service request failed'}, b
" || fail "response body did not match the expected safe downstream_failure contract for $expected_service (body=$CHECKOUT_BODY)"
}

# prom_count <service_name> <http_route>
# Sums the real Prometheus HTTP-request counter for one service/route,
# exactly the before/after pattern scripts/verify-alert-lifecycle.sh's
# own telemetry-resumption check already uses. Bounded like every other
# network call this script makes.
prom_count() {
  curl -fsS --connect-timeout 5 --max-time 15 -G "$PROMETHEUS_URL/api/v1/query" \
    --data-urlencode "query=http_server_request_duration_seconds_count{service_name=\"$1\",http_route=\"$2\"}" \
  | python3 -c '
import json, sys
result = json.load(sys.stdin)["data"]["result"]
print(sum(float(r["value"][1]) for r in result) if result else 0)
'
}

# wait_for_metric_increase <service_name> <http_route> <baseline> [attempts]
# Polls prom_count until it is strictly greater than baseline (bounded
# by OTel's 5s export interval + Prometheus's 15s scrape interval in
# this stack), printing the new value on success.
wait_for_metric_increase() {
  local service="$1" route="$2" baseline="$3" attempts="${4:-20}"
  local i current
  for i in $(seq 1 "$attempts"); do
    current="$(prom_count "$service" "$route")"
    if python3 -c "import sys; sys.exit(0 if float('$current') > float('$baseline') else 1)"; then
      echo "$current"
      return 0
    fi
    sleep 3
  done
  return 1
}

# restore_target
# The ONE place this script ever starts a stopped dependency back up.
# Idempotent: a second call after NEEDS_RESTORE has already been
# cleared (because health was actually verified) is a cheap no-op.
# Deliberately does NOT clear NEEDS_RESTORE until wait_healthy actually
# confirms the dependency healthy again -- a failed restoration leaves
# NEEDS_RESTORE=true and returns 1, so callers (here: on_exit) can
# detect and report it rather than silently treating "we issued start"
# as "the dependency is back". Never trusts docker compose start's own
# exit code as proof of anything.
restore_target() {
  [ -n "$IDS_FILE" ] && rm -f "$IDS_FILE" 2>/dev/null
  if [ "$NEEDS_RESTORE" = false ]; then
    return 0
  fi
  echo "" >&2
  echo "-- cleanup: restoring $TARGET_SERVICE --" >&2
  docker compose -f "$REPO_ROOT/docker-compose.yml" start "$TARGET_SERVICE" >/dev/null 2>&1 || true
  if wait_healthy "$TARGET_SERVICE" 20; then
    echo "-- cleanup: $TARGET_SERVICE confirmed healthy again --" >&2
    NEEDS_RESTORE=false
    return 0
  fi
  echo "-- cleanup: $TARGET_SERVICE did NOT confirm healthy after restart -- manual investigation required: run 'docker compose start $TARGET_SERVICE' and check 'docker compose ps' --" >&2
  return 1
}

# on_exit
# The single EXIT trap. Captures the ORIGINAL exit status before
# calling restore_target (whose own commands would otherwise clobber
# $?), then preserves that original status on the way back out --
# EXCEPT that a scenario which otherwise reached a clean 0 exit is
# forced to a nonzero one if restoration could not be verified, so
# "PASS"/a 0 exit is never reported while a dependency is left down.
# INT/TERM never call restore_target directly (see the traps below) --
# this is the only call site, so cleanup never runs twice.
on_exit() {
  local exit_status=$?
  if ! restore_target; then
    echo "FAIL: cleanup could not verify $TARGET_SERVICE healthy -- manual investigation required" >&2
    [ "$exit_status" -eq 0 ] && exit_status=1
  fi
  exit "$exit_status"
}

main() {
  cd "$REPO_ROOT"

  SCENARIO="${1:-}"
  shift || true
  for arg in "$@"; do
    case "$arg" in
      --full-acceptance) FULL_ACCEPTANCE=true ;;
      *) fail "unrecognized argument: $arg" ;;
    esac
  done

  # The allowlist: the ONLY mapping from a scenario name to a Compose
  # service this script will ever stop.
  case "$SCENARIO" in
    payment-outage)
      TARGET_SERVICE="payment-service"
      ;;
    inventory-outage)
      TARGET_SERVICE="inventory-service"
      ;;
    "")
      fail "usage: $0 <payment-outage|inventory-outage> [--full-acceptance]"
      ;;
    *)
      fail "unsupported/unsafe scenario '$SCENARIO' -- refused. Supported scenarios: payment-outage, inventory-outage"
      ;;
  esac

  if [ "$FULL_ACCEPTANCE" = true ] && [ "$SCENARIO" != "payment-outage" ]; then
    fail "--full-acceptance is only supported for payment-outage (see docs/architecture/phase-4-failure-simulation.md)"
  fi

  # Defensive, redundant guard on top of the allowlist above: this
  # script must never, under any code path, target postgres or any
  # other infrastructure service.
  case "$TARGET_SERVICE" in
    payment-service|inventory-service) ;;
    *) fail "internal error: resolved target '$TARGET_SERVICE' is not an allowlisted application service" ;;
  esac

  echo "Scenario selected: $SCENARIO (target service: $TARGET_SERVICE; full-acceptance: $FULL_ACCEPTANCE)"

  # Exactly one cleanup call site: the EXIT trap (on_exit). INT/TERM
  # only set the conventional exit code and exit -- that exit triggers
  # on_exit itself, so cleanup runs exactly once no matter which path
  # got here. (SIGKILL cannot be trapped at all -- see the header.)
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  section "1. Establish a healthy baseline"
  for svc in checkout-service payment-service inventory-service notification-service; do
    wait_healthy "$svc" 20 || fail "$svc did not reach healthy before the scenario could start"
  done
  echo "  all four application services healthy"

  do_checkout
  [ "$CHECKOUT_STATUS" = "200" ] || fail "baseline checkout failed before any fault was injected (status=$CHECKOUT_STATUS body=$CHECKOUT_BODY) -- environment is not healthy enough to run a failure scenario"
  echo "$CHECKOUT_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='COMPLETED', b"
  echo "  baseline checkout succeeded (status=COMPLETED) -- normal application behavior confirmed before fault injection"

  if [ "$FULL_ACCEPTANCE" = true ]; then
    section "1b. (Full acceptance) Confirm $PAYMENT_OUTAGE_ALERT_NAME is initially inactive; capture freshness timestamp"
    python3 "$SCRIPT_DIR/verify-alerting.py" state \
      --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" \
      --alert "$PAYMENT_OUTAGE_ALERT_NAME" --expect-state inactive \
      || fail "$PAYMENT_OUTAGE_ALERT_NAME must be inactive before fault injection -- a pre-existing pending/firing alert would make this run's own evidence ambiguous"
    # Captured BEFORE the fault is induced -- not merely before the
    # traffic-sustaining loop below -- so it is as conservative a floor
    # as possible for "genuinely created/resolved by THIS run", per
    # review correction #2.
    SINCE="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
    echo "  $PAYMENT_OUTAGE_ALERT_NAME confirmed inactive; freshness floor captured: $SINCE"
  fi

  section "2. Inject fault: stop $TARGET_SERVICE"
  # Set BEFORE issuing the stop, not after it returns: if the command
  # itself fails partway or the script is interrupted mid-command, a
  # stop was still attempted and cleanup must still run (docker compose
  # start on an unaffected/already-running container is a safe no-op).
  NEEDS_RESTORE=true
  docker compose -f "$REPO_ROOT/docker-compose.yml" stop "$TARGET_SERVICE" >/dev/null
  echo "  $TARGET_SERVICE stopped"

  if [ "$SCENARIO" = "payment-outage" ]; then
    section "3. Issue a real checkout request and verify the expected safe 502"
    do_checkout
    assert_checkout_failed_with payment-service
    OBSERVED_FAILURE="HTTP 502, service=payment-service (checkout-service correctly identified the failed dependency)"
    echo "  confirmed: checkout-service returned 502 identifying payment-service as the failed dependency"

    if [ "$FULL_ACCEPTANCE" = true ]; then
      section "4. (Full acceptance) Sustain real failing checkout traffic until Prometheus's $PAYMENT_OUTAGE_ALERT_NAME rule fires"
      firing_ok=false
      for i in $(seq 1 40); do
        do_checkout
        # Every single attempt must be a genuine, correctly-attributed
        # payment-service failure -- not just logged and tolerated.
        # If payment-service ever unexpectedly responded successfully
        # (or failed a different way) mid-outage, this aborts
        # immediately rather than silently continuing to poll for an
        # alert that this traffic may no longer be sustaining.
        assert_checkout_failed_with payment-service
        echo "  attempt $i/40: checkout correctly failed (502, service=payment-service) -- sustaining real 5xx traffic; checking $PAYMENT_OUTAGE_ALERT_NAME"
        if python3 "$SCRIPT_DIR/verify-alerting.py" firing \
             --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$PAYMENT_OUTAGE_ALERT_NAME"
        then
          firing_ok=true
          break
        fi
        sleep 5
      done
      [ "$firing_ok" = true ] || fail "$PAYMENT_OUTAGE_ALERT_NAME never reached firing in Prometheus + Alertmanager despite sustained real 5xx traffic"

      section "5. (Full acceptance) Confirm the real Alertmanager webhook created/updated a persisted incident"
      IDS_FILE="$(mktemp)"
      ingestion_ok=false
      for i in $(seq 1 20); do
        if python3 "$SCRIPT_DIR/verify-ingestion.py" incident-from-alert --alert "$PAYMENT_OUTAGE_ALERT_NAME" \
             --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" \
             --control-plane-url "$CONTROL_PLANE_URL" --since "$SINCE" --ids-out "$IDS_FILE"
        then
          ingestion_ok=true
          break
        fi
        echo "  attempt $i/20: incident not yet confirmed for $PAYMENT_OUTAGE_ALERT_NAME via the real webhook path"
        sleep 3
      done
      [ "$ingestion_ok" = true ] || fail "the real Alertmanager webhook never resulted in a confirmed, correctly-mapped incident for $PAYMENT_OUTAGE_ALERT_NAME"
      INCIDENT_EVIDENCE="$(tr '\n' ' ' <"$IDS_FILE")"
    fi
  else
    section "3. Snapshot payment/notification request counts before the fault"
    # The baseline checkout in step 1 already incremented these same
    # counters. Without this wait, that increment can still be
    # in-flight through the OTel export interval (5s) + Prometheus
    # scrape interval (15s) in this stack and arrive AFTER this
    # snapshot but BEFORE the post-fault check below, which would be
    # misread as notification having been called during the outage.
    # Settling here, once, keeps the snapshot a true "before" value.
    echo "  waiting for the baseline checkout's own metrics to fully settle in Prometheus first..."
    sleep 20
    PAYMENT_BEFORE="$(prom_count payment-service /payments/authorize)"
    NOTIFICATION_BEFORE="$(prom_count notification-service /notifications)"
    echo "  payment-service authorize count (before): $PAYMENT_BEFORE"
    echo "  notification-service notify count (before): $NOTIFICATION_BEFORE"

    section "4. Issue a real checkout request and verify the expected safe 502"
    do_checkout
    assert_checkout_failed_with inventory-service
    echo "  confirmed: checkout-service returned 502 identifying inventory-service as the failed dependency"

    section "5. Verify the payment step genuinely completed before the failure"
    PAYMENT_AFTER="$(wait_for_metric_increase payment-service /payments/authorize "$PAYMENT_BEFORE" 20)" \
      || fail "payment-service's request count never increased after the checkout attempt -- the payment step may not have genuinely completed before the inventory failure"
    echo "  confirmed: payment-service authorize count increased ($PAYMENT_BEFORE -> $PAYMENT_AFTER) -- the payment step genuinely completed before the failure"

    section "6. Verify orchestration short-circuited -- notification was never called"
    # Payment's own counter becoming visible (just confirmed above)
    # does NOT prove notification-service's own, independent exporter
    # has had its own full export+scrape cycle yet -- checking
    # notification immediately would risk a false negative (it was
    # actually called, but its own metric simply hasn't propagated
    # yet). Observe it repeatedly across a bounded window sized to this
    # stack's real OTel export interval (5s) + Prometheus scrape
    # interval (15s), asserting "still unchanged" on every observation,
    # not just the last one -- this proves notification stayed flat
    # for the whole window, not merely at one lucky instant.
    echo "  observing notification-service's counter across a full post-failure window (5 x 5s, covering the 5s export + 15s scrape cycle with margin)..."
    notification_flat=true
    NOTIFICATION_AFTER="$NOTIFICATION_BEFORE"
    for i in $(seq 1 5); do
      NOTIFICATION_AFTER="$(prom_count notification-service /notifications)"
      if ! python3 -c "import sys; sys.exit(0 if float('$NOTIFICATION_AFTER') == float('$NOTIFICATION_BEFORE') else 1)"; then
        notification_flat=false
        break
      fi
      echo "  observation $i/5: notification-service count still $NOTIFICATION_AFTER (unchanged)"
      sleep 5
    done
    [ "$notification_flat" = true ] || fail "notification-service's request count increased ($NOTIFICATION_BEFORE -> $NOTIFICATION_AFTER) during the post-failure observation window -- orchestration did not short-circuit before reaching notification"
    echo "  confirmed: notification-service was never called across a full post-failure observation window ($NOTIFICATION_BEFORE -> $NOTIFICATION_AFTER unchanged) -- orchestration correctly short-circuited. This proves notification stayed uncalled for that observation window, not for all time."

    OBSERVED_FAILURE="HTTP 502, service=inventory-service; payment completed ($PAYMENT_BEFORE -> $PAYMENT_AFTER); notification never called across a full observation window ($NOTIFICATION_BEFORE -> $NOTIFICATION_AFTER)"
  fi

  section "7. Restore $TARGET_SERVICE"
  docker compose -f "$REPO_ROOT/docker-compose.yml" start "$TARGET_SERVICE" >/dev/null
  wait_healthy "$TARGET_SERVICE" 20 || fail "$TARGET_SERVICE did not become healthy again after restart"
  # Cleared ONLY now that health has been actively verified -- never
  # merely because "start" was issued.
  NEEDS_RESTORE=false
  echo "  $TARGET_SERVICE restored and confirmed healthy"

  section "8. Verify a fresh checkout succeeds"
  do_checkout
  [ "$CHECKOUT_STATUS" = "200" ] || fail "fresh checkout after restoring $TARGET_SERVICE failed (status=$CHECKOUT_STATUS body=$CHECKOUT_BODY)"
  echo "$CHECKOUT_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='COMPLETED', b"
  echo "  fresh checkout succeeded (status=COMPLETED) after restoration"
  RECOVERY_SUMMARY="$TARGET_SERVICE restarted and confirmed healthy; fresh checkout COMPLETED"

  if [ "$FULL_ACCEPTANCE" = true ]; then
    section "9. (Full acceptance) Wait for Prometheus/Alertmanager to recover"
    echo "-- $PAYMENT_OUTAGE_ALERT_NAME's expression is a 5-minute rate() over real checkout traffic, not an"
    echo "   instantaneous gauge: it will not read exactly zero until roughly 5 minutes have"
    echo "   passed since the last real failing request above. This wait is expected to take"
    echo "   several minutes -- see docs/architecture/phase-4-failure-simulation.md. The"
    echo "   threshold itself is never altered to make this faster. --"
    recovered_ok=false
    for i in $(seq 1 90); do
      if python3 "$SCRIPT_DIR/verify-alerting.py" recovered \
           --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$PAYMENT_OUTAGE_ALERT_NAME"
      then
        recovered_ok=true
        break
      fi
      echo "  attempt $i/90: $PAYMENT_OUTAGE_ALERT_NAME not yet recovered"
      sleep 5
    done
    [ "$recovered_ok" = true ] || fail "$PAYMENT_OUTAGE_ALERT_NAME never recovered to inactive in Prometheus / resolved in Alertmanager"

    section "10. (Full acceptance) Confirm genuine automatic resolution with a correctly-attributed audit trail"
    resolution_ok=false
    for i in $(seq 1 20); do
      if python3 "$SCRIPT_DIR/verify-ingestion.py" confirm-resolved \
           --ids-file "$IDS_FILE" --control-plane-url "$CONTROL_PLANE_URL" --since "$SINCE"
      then
        resolution_ok=true
        break
      fi
      echo "  attempt $i/20: incident(s) not yet confirmed resolved (with a genuine audit trail)"
      sleep 3
    done
    [ "$resolution_ok" = true ] || fail "the real Alertmanager resolved webhook never resulted in the matching incident(s) resolving with a genuine audit trail"
    RECOVERY_SUMMARY="$RECOVERY_SUMMARY; $PAYMENT_OUTAGE_ALERT_NAME recovered; incident(s) resolved with correctly-attributed audit trail"
  fi

  section "SUMMARY"
  echo "  Scenario selected:      $SCENARIO (target: $TARGET_SERVICE; full-acceptance: $FULL_ACCEPTANCE)"
  echo "  Healthy baseline:       confirmed (all 4 application services healthy; baseline checkout COMPLETED)"
  echo "  Fault applied:          $TARGET_SERVICE stopped via docker compose"
  echo "  Observed failure:       $OBSERVED_FAILURE"
  echo "  Recovery performed:     $RECOVERY_SUMMARY"
  if [ "$FULL_ACCEPTANCE" = true ]; then
    echo "  Incident evidence:      ${INCIDENT_EVIDENCE:-<none>} (incident_id<TAB>fingerprint pairs, since=$SINCE)"
  fi
  echo "  Final verification result: PASS"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
