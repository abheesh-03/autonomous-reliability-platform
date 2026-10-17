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
# CI cross-phase stabilization audit (post-run-#37, extended after the
# targeted real-stack validation below): inventory-outage's own real
# checkout traffic can independently drive TWO separate real Prometheus
# rules to firing from the SAME underlying requests -- CheckoutServerErrors
# (no `by(...)` clause, same fixed label set payment-outage already
# exercises -- see docs/architecture/phase-4-failure-simulation.md) AND
# CheckoutHighLatency (checkout-service POST /checkouts p95 latency
# above 1s). This was empirically confirmed, not theoretical: a targeted
# real-stack run observed BOTH alerts fire and resolve with distinct
# fingerprints during a single inventory-outage scenario. Section 3
# below independently tracks and converges EACH alert's own full
# Alertmanager-webhook-to-control-plane lifecycle -- never merely that
# Prometheus/Alertmanager's OWN state looks clean, which audit run #37
# proved is not sufficient (Alertmanager's own internal "no active
# alert" view can legitimately precede its own webhook HTTP delivery
# actually committing downstream). Converging CheckoutServerErrors alone
# is NOT sufficient: CheckoutHighLatency could still be firing, or its
# own resolved webhook could land later, reintroducing exactly the
# cross-phase race this section exists to close. Section 3 additionally
# requires a bounded DATABASE STABILITY proof (reliability.incidents/
# incident_events observed unchanged across several consecutive
# samples) AFTER both alerts have independently converged, before
# Phase 4 is ever allowed to print its final PASS line.
#
# All actual scenario logic — safety allowlisting, fault injection,
# assertions, restoration, reporting — lives in
# scripts/simulate-failure.sh; this script only sequences the two
# runs and confirms the prerequisites (webhook secret, control-plane
# readiness) that the full-acceptance run depends on, PLUS this
# phase's own post-inventory-outage convergence/stability proof. No
# incident or audit row is ever deleted by either run.
#
# Intended to run AFTER `make verify-alert-ingestion` (the existing
# Phase 2B.4/3C-3E Collector-outage gate) in both CI and local use, so
# it cannot interfere with that gate's own preconditions.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
readonly CHECKOUT_SERVER_ERRORS_TITLE="checkout-service is returning HTTP 5xx errors"
readonly CHECKOUT_HIGH_LATENCY_TITLE="checkout-service POST /checkouts p95 latency above 1s"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# Two independent temp files (one per independently-converged alert --
# never shared, so two different fingerprints/titles can never collide
# in the same evidence file) need cleanup in this script (every Docker
# service stop/start is scoped inside scripts/simulate-failure.sh's own
# EXIT trap, not this one's). Captures the ORIGINAL exit status FIRST
# and explicitly re-exits with it at the end -- an EXIT trap's own
# final exit status otherwise silently REPLACES the real one (the
# classic bash gotcha every other EXIT trap in this repository already
# guards against): without this, a successful run with both files still
# empty (the neither-alert-fired path, where neither is ever set) would
# have this trap's own `[ -n "" ] && ...` evaluate to false and
# silently turn a genuine PASS into a nonzero exit.
CSE_IDS_FILE=""
CHL_IDS_FILE=""
cleanup() {
  local exit_status=$?
  [ -n "$CSE_IDS_FILE" ] && rm -f "$CSE_IDS_FILE"
  [ -n "$CHL_IDS_FILE" ] && rm -f "$CHL_IDS_FILE"
  exit "$exit_status"
}
trap cleanup EXIT

psql_exec() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

# Same md5(string_agg(row_to_json(...))) convention
# scripts/verify-agent-runtime.sh's own correction-round finding #8
# already established -- deterministic ordering (ORDER BY id) +
# canonical PostgreSQL JSON representation, never a naive text dump.
incidents_fingerprint() {
  psql_exec -c "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '|' ORDER BY t.id), '')) FROM reliability.incidents t;"
}

incident_events_fingerprint() {
  psql_exec -c "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '|' ORDER BY t.id), '')) FROM reliability.incident_events t;"
}

# alert_recovered <alert_name> / alert_firing <alert_name>
#
# Thin, non-duplicated wrappers around the existing, authoritative
# scripts/verify-alerting.py "recovered"/"firing" subcommands --
# parameterized by alert name so the SAME two calls serve both
# CheckoutServerErrors and CheckoutHighLatency, never a second,
# duplicated parse of either Prometheus's or Alertmanager's own
# responses.
alert_recovered() {
  local alert_name="$1"
  python3 "$SCRIPT_DIR/verify-alerting.py" recovered \
    --prometheus-url "$PROMETHEUS_URL" \
    --alertmanager-url "$ALERTMANAGER_URL" \
    --alert "$alert_name"
}

alert_firing() {
  local alert_name="$1"
  python3 "$SCRIPT_DIR/verify-alerting.py" firing \
    --prometheus-url "$PROMETHEUS_URL" \
    --alertmanager-url "$ALERTMANAGER_URL" \
    --alert "$alert_name" >/dev/null 2>&1
}

# wait_for_alerts_clean [max_attempts] [sleep_seconds]
#
# Bounded, condition-based polling (never a fixed sleep) that watches
# CheckoutServerErrors AND CheckoutHighLatency TOGETHER each attempt --
# a single shared bounded budget, never duplicated polling cadence --
# but tracks each alert's own firing/clean state INDEPENDENTLY. Returns
# 0 the first time BOTH alerts are simultaneously confirmed clean
# (Prometheus rule state == inactive, its own alerts list empty, AND
# Alertmanager has no active unresolved match); returns 1 if that never
# happens within max_attempts. Along the way, independently sets the
# global CSE_FIRING_OBSERVED / CHL_FIRING_OBSERVED to true the first
# time each alert's own "firing" check independently confirms it
# genuinely reached firing in BOTH Prometheus and Alertmanager -- once
# an alert's own flag is set, its own firing check is skipped on later
# attempts (no wasted polling), but its own recovered check keeps being
# evaluated every attempt until BOTH alerts are clean. Extracted as its
# own function (rather than inlined) so
# scripts/test-failure-simulation-settling.sh can exercise this exact
# polling/attempt-counting logic with a stubbed `python3`, without
# sleeping for real or needing a running stack.
CSE_FIRING_OBSERVED=false
CHL_FIRING_OBSERVED=false
wait_for_alerts_clean() {
  local max_attempts="${1:-90}" sleep_seconds="${2:-5}"
  local attempt cse_clean chl_clean
  for attempt in $(seq 1 "$max_attempts"); do
    cse_clean=false
    chl_clean=false
    alert_recovered CheckoutServerErrors && cse_clean=true
    alert_recovered CheckoutHighLatency && chl_clean=true

    if [ "$cse_clean" = true ] && [ "$chl_clean" = true ]; then
      return 0
    fi

    if [ "$CSE_FIRING_OBSERVED" = false ] && alert_firing CheckoutServerErrors; then
      CSE_FIRING_OBSERVED=true
      echo "  CheckoutServerErrors observed FIRING (confirmed in both Prometheus and Alertmanager) at attempt $attempt/$max_attempts -- a real incident lifecycle will be required before handoff"
    fi
    if [ "$CHL_FIRING_OBSERVED" = false ] && alert_firing CheckoutHighLatency; then
      CHL_FIRING_OBSERVED=true
      echo "  CheckoutHighLatency observed FIRING (confirmed in both Prometheus and Alertmanager) at attempt $attempt/$max_attempts -- a real incident lifecycle will be required before handoff"
    fi
    echo "  attempt $attempt/$max_attempts: CheckoutServerErrors clean=$cse_clean, CheckoutHighLatency clean=$chl_clean -- not both clean yet"
    sleep "$sleep_seconds"
  done
  return 1
}

# wait_for_db_stability [required_stable_samples] [interval_seconds] [max_attempts]
#
# Deliberately NOT a fixed sleep: requires the SAME two global content
# fingerprints (reliability.incidents / reliability.incident_events) to
# be observed UNCHANGED across required_stable_samples CONSECUTIVE
# observations, interval_seconds apart. Any observed change resets the
# counter to zero and adopts the new values as the latest baseline --
# defense-in-depth against a late in-flight webhook delivery (CI
# cross-phase stabilization audit finding: Alertmanager's own internal
# "no active alert" state can legitimately be observed BEFORE its own
# webhook HTTP delivery to control-plane has completed/committed).
# This is never a substitute for confirm-resolved's own authoritative
# checks (status/resolved_at/audit-trail/attribution) -- it only
# proves the GLOBAL state has genuinely settled, for whichever
# occurrence(s) were involved, before the next phase is allowed to
# snapshot it as a quiescent baseline.
wait_for_db_stability() {
  local required_stable="${1:-3}" interval_seconds="${2:-15}" max_attempts="${3:-32}"
  local attempt stable_samples=0
  local previous_incidents_fp previous_events_fp current_incidents_fp current_events_fp

  previous_incidents_fp="$(incidents_fingerprint)"
  previous_events_fp="$(incident_events_fingerprint)"

  for attempt in $(seq 1 "$max_attempts"); do
    sleep "$interval_seconds"
    current_incidents_fp="$(incidents_fingerprint)"
    current_events_fp="$(incident_events_fingerprint)"
    if [ "$current_incidents_fp" = "$previous_incidents_fp" ] && [ "$current_events_fp" = "$previous_events_fp" ]; then
      stable_samples=$((stable_samples + 1))
      echo "  DB stability observation $attempt/$max_attempts: unchanged ($stable_samples/$required_stable consecutive stable samples)"
      if [ "$stable_samples" -ge "$required_stable" ]; then
        return 0
      fi
    else
      echo "  DB stability observation $attempt/$max_attempts: a global content fingerprint CHANGED -- resetting the stability counter (a write is still in flight)"
      stable_samples=0
      previous_incidents_fp="$current_incidents_fp"
      previous_events_fp="$current_events_fp"
    fi
  done
  return 1
}

# converge_alert_incident <title> <since> <ids_file>
#
# Generalized, alert-agnostic incident-capture-and-resolve sequence --
# ONE implementation shared by BOTH CheckoutServerErrors and
# CheckoutHighLatency, parameterized by the alert's own exact incident
# title, the shared inventory-outage freshness floor, and a
# caller-allocated (mktemp) ids file so two different alerts'
# fingerprints/titles can never collide in the same evidence file.
# Calls `fail` (which `exit`s) on any bounded-budget exhaustion --
# never returns a failure code of its own.
converge_alert_incident() {
  local title="$1" since="$2" ids_file="$3"

  # Step 1/2: capture the fresh, inventory-window incident via the
  # status-agnostic incident-after helper -- NEVER incident-from-alert,
  # which requires the alert to still be ACTIVE in Prometheus/
  # Alertmanager at read time (too fragile here: by this point we
  # already know the alert is clean/inactive, so the incident itself
  # may already be fully resolved too).
  local capture_ok=false i
  for i in $(seq 1 20); do
    if python3 "$SCRIPT_DIR/verify-ingestion.py" incident-after \
         --title "$title" --since "$since" \
         --control-plane-url "$CONTROL_PLANE_URL" --ids-out "$ids_file"
    then
      capture_ok=true
      break
    fi
    echo "  attempt $i/20: the fresh inventory-outage-triggered incident for '$title' is not yet confirmed via incident-after"
    sleep 3
  done
  [ "$capture_ok" = true ] || fail "could not capture exactly one fresh incident for title '$title' in inventory-outage's own freshness window ($since)"

  # Step 3: Prometheus/Alertmanager recovery was already confirmed by
  # the caller's own wait_for_alerts_clean call that also detected
  # firing -- never polled a second time here.

  # Step 4: the existing, authoritative confirm-resolved remains the
  # ONE place that checks status==resolved, resolved_at, the genuine
  # created+resolving audit events, actor_type attribution, fingerprint
  # provenance, and event ordering -- never reimplemented here.
  local resolution_ok=false
  for i in $(seq 1 20); do
    if python3 "$SCRIPT_DIR/verify-ingestion.py" confirm-resolved \
         --ids-file "$ids_file" --control-plane-url "$CONTROL_PLANE_URL" --since "$since"
    then
      resolution_ok=true
      break
    fi
    echo "  attempt $i/20: the fresh inventory-outage incident for '$title' is not yet confirmed resolved (with a genuine audit trail)"
    sleep 3
  done
  [ "$resolution_ok" = true ] || fail "the fresh inventory-outage-triggered incident for title '$title' never resolved with a genuine, correctly-attributed audit trail"
}

# confirm_inventory_outage_convergence <inventory_outage_since>
#
# The entire post-inventory-outage convergence/stability sequence
# (sections 3 and 4), wrapped as ONE function so
# scripts/test-failure-simulation-settling.sh can extract and exercise
# this EXACT real logic (never a reimplementation) with every external
# dependency (verify-alerting.py, verify-ingestion.py, psql_exec,
# sleep) stubbed, without a running stack and without any real
# sleeping. Enforces the required handoff order: converge
# CheckoutServerErrors fully, THEN converge CheckoutHighLatency fully,
# THEN global DB stability -- Phase 4 may only PASS after all three.
# Calls `fail` (which `exit`s) on any bounded-budget exhaustion --
# never returns a failure code of its own.
confirm_inventory_outage_convergence() {
  local inventory_outage_since="$1"

  section "3. Confirm shared CheckoutServerErrors/CheckoutHighLatency state and control-plane audit convergence after inventory-outage"
  # Bounded, condition-based polling (never a fixed sleep); the 90 x 5s
  # budget mirrors simulate-failure.sh's own documented real-decay
  # precedent for these alerts. This SAME call also independently
  # tracks whether inventory-outage's own real traffic made EITHER
  # rule reach firing at all (see wait_for_alerts_clean's own
  # docstring).
  if ! wait_for_alerts_clean 90 5; then
    fail "CheckoutServerErrors and/or CheckoutHighLatency did not return to a clean inactive state after the inventory-outage scenario"
  fi
  echo "  CheckoutServerErrors and CheckoutHighLatency both confirmed clean (Prometheus inactive, Alertmanager no active alert) after inventory-outage"

  if [ "$CSE_FIRING_OBSERVED" = true ]; then
    echo "  CheckoutServerErrors reached FIRING during inventory-outage -- confirming its own incident's control-plane lifecycle fully converges"
    CSE_IDS_FILE="$(mktemp)"
    converge_alert_incident "$CHECKOUT_SERVER_ERRORS_TITLE" "$inventory_outage_since" "$CSE_IDS_FILE"
    echo "  confirmed: the fresh inventory-outage-triggered CheckoutServerErrors incident fully converged (resolved, genuine audit trail)"
  else
    # CheckoutServerErrors never reached firing -- no incident lifecycle
    # was ever created for inventory-outage's own traffic, so none is
    # required here. Never fabricated, and incident-after is never even
    # called on this path.
    echo "  CheckoutServerErrors never reached FIRING during inventory-outage (pending -> inactive only, or never left inactive) -- no incident lifecycle required"
  fi

  if [ "$CHL_FIRING_OBSERVED" = true ]; then
    echo "  CheckoutHighLatency reached FIRING during inventory-outage -- confirming its own incident's control-plane lifecycle fully converges"
    CHL_IDS_FILE="$(mktemp)"
    converge_alert_incident "$CHECKOUT_HIGH_LATENCY_TITLE" "$inventory_outage_since" "$CHL_IDS_FILE"
    echo "  confirmed: the fresh inventory-outage-triggered CheckoutHighLatency incident fully converged (resolved, genuine audit trail)"
  else
    echo "  CheckoutHighLatency never reached FIRING during inventory-outage (pending -> inactive only, or never left inactive) -- no incident lifecycle required"
  fi

  section "4. Final database stability window before handoff"
  # Required on BOTH paths (A5): defense-in-depth against any remaining
  # in-flight delivery (or an unexpected recurrence) neither the alert-
  # state checks above nor confirm-resolved's own single read can catch
  # by themselves. Deliberately a repeated-observation proof, never a
  # single blind sleep -- see wait_for_db_stability's own docstring.
  if wait_for_db_stability 3 15 32; then
    echo "  confirmed: reliability.incidents and reliability.incident_events held three consecutive unchanged observations (~45s of demonstrated quiescence)"
  else
    fail "reliability.incidents/incident_events never settled to three consecutive unchanged observations within the bounded stability budget -- a write may still be in flight"
  fi
}

# --- END OF FUNCTION DEFINITIONS --- (marker line
# scripts/test-failure-simulation-settling.sh's own extraction relies
# on; everything below this point is this script's own top-level,
# side-effecting flow, never meant to be sourced/extracted in
# isolation.)

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

# Captured BEFORE inventory-outage even starts -- this freshness floor
# belongs ONLY to inventory-outage's own potential occurrence, never
# to payment-outage's (which already has its own, earlier SINCE,
# entirely internal to simulate-failure.sh).
INVENTORY_OUTAGE_SINCE="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
echo "  inventory-outage freshness floor captured: $INVENTORY_OUTAGE_SINCE"

section "2. Scenario: inventory-outage (deterministic failure/recovery only -- no second full-alert simulation)"
"$SCRIPT_DIR/simulate-failure.sh" inventory-outage

confirm_inventory_outage_convergence "$INVENTORY_OUTAGE_SINCE"

echo ""
echo "PHASE 4 FAILURE-SIMULATION ACCEPTANCE VERIFIED: payment-outage proved the complete real chain (outage -> failed checkouts -> Prometheus CheckoutServerErrors firing -> real Alertmanager webhook -> persisted incident -> restoration -> recovery -> automatic resolution -> correctly-attributed audit trail); inventory-outage proved its own deterministic failure (correct dependency identified, payment completed, notification short-circuited) and recovery, and -- whether or not its own real traffic additionally drove CheckoutServerErrors and/or CheckoutHighLatency to firing -- EACH alert's own full control-plane audit convergence (if any) and a final, repeatedly-observed database stability window were both confirmed before handoff, so later phases (including Phase 8's own strict baseline requirement) start from a genuinely settled, clean shared state."
