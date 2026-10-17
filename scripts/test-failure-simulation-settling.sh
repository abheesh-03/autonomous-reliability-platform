#!/usr/bin/env bash
#
# test-failure-simulation-settling.sh — Focused, no-Docker regression
# for scripts/verify-failure-simulation.sh's post-inventory-outage
# convergence/stability logic (CI cross-phase stabilization audit,
# extended to the two-alert CheckoutServerErrors + CheckoutHighLatency
# correction):
#
#   confirm_inventory_outage_convergence()
#     -> wait_for_alerts_clean() (tracks CSE_FIRING_OBSERVED, CHL_FIRING_OBSERVED independently)
#     -> [if CSE fired] converge_alert_incident(CheckoutServerErrors title, CSE_IDS_FILE)
#     -> [if CHL fired] converge_alert_incident(CheckoutHighLatency title, CHL_IDS_FILE)
#     -> wait_for_db_stability() (always, all paths)
#
# Extracts the REAL function bodies directly out of
# verify-failure-simulation.sh (never a reimplementation/duplicate of
# their polling logic) -- that script is not safe to `source` as a
# whole (it has no bottom `main()`/BASH_SOURCE guard and runs real
# `docker compose`/`curl` calls immediately at its own top level), but
# everything from `set -euo pipefail` through its own explicit
# "END OF FUNCTION DEFINITIONS" marker comment is pure function/
# variable definitions with no side effects, safe to `eval` here.
#
# Stubs `python3` (dispatching on which script + subcommand is being
# invoked, AND on the real `--alert`/`--title`/`--ids-file` arguments
# -- never on call order alone, since the two alerts' own polling is
# interleaved within the same wait_for_alerts_clean loop), `incidents_fingerprint`/
# `incident_events_fingerprint` (test-only overrides, defined AFTER
# the real extraction so they take precedence), and `sleep` (never
# actually waits). No Docker, no real network, no real sleeping.
#
# Alert dispatch keys:
#   - verify-alerting.py recovered/firing: dispatched on the real
#     `--alert` value (CheckoutServerErrors / CheckoutHighLatency).
#   - verify-ingestion.py incident-after: dispatched on the real
#     `--title` value (compared against the production script's own
#     $CHECKOUT_SERVER_ERRORS_TITLE / $CHECKOUT_HIGH_LATENCY_TITLE
#     constants, inherited from the real eval'd extraction -- never a
#     second, hardcoded copy of either string).
#   - verify-ingestion.py confirm-resolved: dispatched on the real
#     `--ids-file` value, compared against the production script's own
#     $CSE_IDS_FILE / $CHL_IDS_FILE globals (confirm-resolved itself
#     carries no --title) -- this also structurally proves the two
#     alerts' evidence files are never mixed, since a call with an
#     ids-file matching neither is treated as a test failure.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TARGET="$SCRIPT_DIR/verify-failure-simulation.sh"

PASS=0
FAIL=0

ok() {
  PASS=$((PASS + 1))
  echo "  ok   - $1"
}

bad() {
  FAIL=$((FAIL + 1))
  echo "  FAIL - $1"
}

# Extract from the first real settings assignment (CONTROL_PLANE_URL)
# through the explicit marker comment -- function/variable definitions
# only, no top-level side effects. Deliberately starts AFTER (never
# includes) the production script's own `SCRIPT_DIR=.../${BASH_SOURCE[0]}`
# derivation: `BASH_SOURCE` reflects THIS test script's own call stack
# once eval'd here, not the production script's, and under `set -u`
# can be unbound entirely in some invocation contexts -- this test
# relies on the SAME-named $SCRIPT_DIR this test script's own top
# already set correctly (both files live in the same `scripts/`
# directory), inherited as-is into the subshell below.
FUNCTION_SOURCE="$(sed -n '/^CONTROL_PLANE_URL=/,/^# --- END OF FUNCTION DEFINITIONS/p' "$TARGET")"
if [ -z "$FUNCTION_SOURCE" ]; then
  echo "FAIL - could not extract the function-definitions block from $TARGET -- has its marker comment been renamed/removed?" >&2
  exit 1
fi

# The real CheckoutHighLatency title constant, read directly from the
# production script (never a second, hardcoded copy) -- used only by
# this outer (non-eval'd) scope's own log assertions below; the
# eval'd subshells already get the authoritative
# $CHECKOUT_HIGH_LATENCY_TITLE themselves via FUNCTION_SOURCE.
CHL_TITLE_FOR_TEST="$(sed -n 's/^readonly CHECKOUT_HIGH_LATENCY_TITLE="\(.*\)"$/\1/p' "$TARGET")"
if [ -z "$CHL_TITLE_FOR_TEST" ]; then
  echo "FAIL - could not read CHECKOUT_HIGH_LATENCY_TITLE from $TARGET" >&2
  exit 1
fi

# run_case <name> <cse_recovered_seq> <chl_recovered_seq> <cse_firing_seq> <chl_firing_seq> \
#          <cse_incident_after_seq> <chl_incident_after_seq> \
#          <cse_confirm_resolved_seq> <chl_confirm_resolved_seq> \
#          <incidents_fp_seq> <events_fp_seq>
#
# Each *_seq is a comma-separated list of exit codes (0=success,
# 1=failure), one per expected call to that exact stub; a call beyond
# the end of its own list is itself a test failure (never silently
# tolerated). Runs confirm_inventory_outage_convergence in a fresh
# subshell (its own `fail` calls `exit`, so isolation is required) and
# captures combined stdout+stderr plus the real exit code.
run_case() {
  local name="$1"
  local cse_recovered_seq="$2" chl_recovered_seq="$3"
  local cse_firing_seq="$4" chl_firing_seq="$5"
  local cse_incident_after_seq="$6" chl_incident_after_seq="$7"
  local cse_confirm_resolved_seq="$8" chl_confirm_resolved_seq="$9"
  local incidents_fp_seq="${10}" events_fp_seq="${11}"
  local log
  log="$(mktemp)"

  (
    set -euo pipefail
    eval "$FUNCTION_SOURCE"

    # never actually sleeps -- proves polling/attempt-counting
    # behavior, never real wall-clock timing.
    sleep() { :; }

    IFS=',' read -r -a CSE_RECOVERED_SEQ <<<"$cse_recovered_seq"
    IFS=',' read -r -a CHL_RECOVERED_SEQ <<<"$chl_recovered_seq"
    IFS=',' read -r -a CSE_FIRING_SEQ <<<"$cse_firing_seq"
    IFS=',' read -r -a CHL_FIRING_SEQ <<<"$chl_firing_seq"
    IFS=',' read -r -a CSE_INCIDENT_AFTER_SEQ <<<"$cse_incident_after_seq"
    IFS=',' read -r -a CHL_INCIDENT_AFTER_SEQ <<<"$chl_incident_after_seq"
    IFS=',' read -r -a CSE_CONFIRM_RESOLVED_SEQ <<<"$cse_confirm_resolved_seq"
    IFS=',' read -r -a CHL_CONFIRM_RESOLVED_SEQ <<<"$chl_confirm_resolved_seq"
    IFS=',' read -r -a INCIDENTS_FP_SEQ <<<"$incidents_fp_seq"
    IFS=',' read -r -a EVENTS_FP_SEQ <<<"$events_fp_seq"

    CSE_RECOVERED_CALLS=0
    CHL_RECOVERED_CALLS=0
    CSE_FIRING_CALLS=0
    CHL_FIRING_CALLS=0
    CSE_INCIDENT_AFTER_CALLS=0
    CHL_INCIDENT_AFTER_CALLS=0
    CSE_CONFIRM_RESOLVED_CALLS=0
    CHL_CONFIRM_RESOLVED_CALLS=0
    INCIDENTS_FP_CALLS=0
    EVENTS_FP_CALLS=0

    # Deliberately NOT using `local -n` namerefs (bash 4.3+ only) --
    # this repository's own local dev shell is macOS's stock bash 3.2,
    # so every stub below addresses its own fixed global array/counter
    # by name directly. Verbose, but portable to the same bash version
    # every other script in this repository already targets.
    python3() {
      local script="$1" subcmd="$2"
      shift 2
      local alert="" title="" ids_file_arg="" idx
      while [ $# -gt 0 ]; do
        case "$1" in
          --alert) alert="$2"; shift 2 ;;
          --title) title="$2"; shift 2 ;;
          --ids-file) ids_file_arg="$2"; shift 2 ;;
          --ids-out) ids_file_arg="$2"; shift 2 ;;
          *) shift ;;
        esac
      done

      case "$script" in
        */verify-alerting.py)
          case "$subcmd" in
            recovered)
              case "$alert" in
                CheckoutServerErrors)
                  idx=$CSE_RECOVERED_CALLS
                  CSE_RECOVERED_CALLS=$((CSE_RECOVERED_CALLS + 1))
                  if [ "$idx" -ge "${#CSE_RECOVERED_SEQ[@]}" ]; then
                    echo "STUB OVERRUN: CSE recovered called too many times" >&2
                    return 1
                  fi
                  return "${CSE_RECOVERED_SEQ[$idx]}"
                  ;;
                CheckoutHighLatency)
                  idx=$CHL_RECOVERED_CALLS
                  CHL_RECOVERED_CALLS=$((CHL_RECOVERED_CALLS + 1))
                  if [ "$idx" -ge "${#CHL_RECOVERED_SEQ[@]}" ]; then
                    echo "STUB OVERRUN: CHL recovered called too many times" >&2
                    return 1
                  fi
                  return "${CHL_RECOVERED_SEQ[$idx]}"
                  ;;
                *) echo "unexpected --alert for recovered: $alert" >&2; return 1 ;;
              esac
              ;;
            firing)
              case "$alert" in
                CheckoutServerErrors)
                  idx=$CSE_FIRING_CALLS
                  CSE_FIRING_CALLS=$((CSE_FIRING_CALLS + 1))
                  if [ "$idx" -ge "${#CSE_FIRING_SEQ[@]}" ]; then
                    echo "STUB OVERRUN: CSE firing called too many times" >&2
                    return 1
                  fi
                  return "${CSE_FIRING_SEQ[$idx]}"
                  ;;
                CheckoutHighLatency)
                  idx=$CHL_FIRING_CALLS
                  CHL_FIRING_CALLS=$((CHL_FIRING_CALLS + 1))
                  if [ "$idx" -ge "${#CHL_FIRING_SEQ[@]}" ]; then
                    echo "STUB OVERRUN: CHL firing called too many times" >&2
                    return 1
                  fi
                  return "${CHL_FIRING_SEQ[$idx]}"
                  ;;
                *) echo "unexpected --alert for firing: $alert" >&2; return 1 ;;
              esac
              ;;
            *) echo "unexpected verify-alerting.py subcommand: $subcmd" >&2; return 1 ;;
          esac
          ;;
        */verify-ingestion.py)
          case "$subcmd" in
            incident-after)
              if [ "$title" = "$CHECKOUT_SERVER_ERRORS_TITLE" ]; then
                idx=$CSE_INCIDENT_AFTER_CALLS
                CSE_INCIDENT_AFTER_CALLS=$((CSE_INCIDENT_AFTER_CALLS + 1))
                if [ "$idx" -ge "${#CSE_INCIDENT_AFTER_SEQ[@]}" ]; then
                  echo "STUB OVERRUN: CSE incident-after called too many times" >&2
                  return 1
                fi
                return "${CSE_INCIDENT_AFTER_SEQ[$idx]}"
              elif [ "$title" = "$CHECKOUT_HIGH_LATENCY_TITLE" ]; then
                idx=$CHL_INCIDENT_AFTER_CALLS
                CHL_INCIDENT_AFTER_CALLS=$((CHL_INCIDENT_AFTER_CALLS + 1))
                if [ "$idx" -ge "${#CHL_INCIDENT_AFTER_SEQ[@]}" ]; then
                  echo "STUB OVERRUN: CHL incident-after called too many times" >&2
                  return 1
                fi
                return "${CHL_INCIDENT_AFTER_SEQ[$idx]}"
              else
                echo "unexpected --title for incident-after: $title" >&2
                return 1
              fi
              ;;
            confirm-resolved)
              if [ "$ids_file_arg" = "$CSE_IDS_FILE" ]; then
                idx=$CSE_CONFIRM_RESOLVED_CALLS
                CSE_CONFIRM_RESOLVED_CALLS=$((CSE_CONFIRM_RESOLVED_CALLS + 1))
                if [ "$idx" -ge "${#CSE_CONFIRM_RESOLVED_SEQ[@]}" ]; then
                  echo "STUB OVERRUN: CSE confirm-resolved called too many times" >&2
                  return 1
                fi
                return "${CSE_CONFIRM_RESOLVED_SEQ[$idx]}"
              elif [ "$ids_file_arg" = "$CHL_IDS_FILE" ]; then
                idx=$CHL_CONFIRM_RESOLVED_CALLS
                CHL_CONFIRM_RESOLVED_CALLS=$((CHL_CONFIRM_RESOLVED_CALLS + 1))
                if [ "$idx" -ge "${#CHL_CONFIRM_RESOLVED_SEQ[@]}" ]; then
                  echo "STUB OVERRUN: CHL confirm-resolved called too many times" >&2
                  return 1
                fi
                return "${CHL_CONFIRM_RESOLVED_SEQ[$idx]}"
              else
                echo "unexpected --ids-file for confirm-resolved (matches neither CSE_IDS_FILE nor CHL_IDS_FILE -- evidence files may have been mixed): $ids_file_arg" >&2
                return 1
              fi
              ;;
            *) echo "unexpected verify-ingestion.py subcommand: $subcmd" >&2; return 1 ;;
          esac
          ;;
        *) echo "unexpected python3 invocation: $script $subcmd $*" >&2; return 1 ;;
      esac
    }

    # Test-only overrides for the two fingerprint functions --
    # defined AFTER the real eval above, so these take precedence.
    # Each consumes one entry from its own sequence array, returning a
    # VALUE (the fingerprint string) rather than an exit code.
    #
    # The PRODUCTION code always calls these via command substitution
    # (`current_incidents_fp="$(incidents_fingerprint)"`) to capture
    # their stdout as a value -- command substitution always forks a
    # subshell, so an ordinary in-memory counter increment inside the
    # function would be silently discarded on every single call (the
    # parent's own copy of the counter variable never advances). A
    # tiny counter FILE is what actually survives across that
    # subshell boundary; `INCIDENTS_FP_SEQ`/`EVENTS_FP_SEQ` themselves
    # are read-only here, so the subshell's own inherited copy of
    # those arrays is fine to read directly.
    INCIDENTS_FP_COUNTER_FILE="$(mktemp)"
    echo 0 >"$INCIDENTS_FP_COUNTER_FILE"
    EVENTS_FP_COUNTER_FILE="$(mktemp)"
    echo 0 >"$EVENTS_FP_COUNTER_FILE"
    # Redefines the production `cleanup` (already `trap`-registered by
    # the real extracted code above, re-resolved by name at trap-fire
    # time, so this redefinition is picked up correctly) to ALSO
    # remove these two test-only counter files, while still preserving
    # the real cleanup's own exit-status-preservation behavior and its
    # own two (now per-alert) evidence-file cleanup.
    cleanup() {
      local exit_status=$?
      [ -n "$CSE_IDS_FILE" ] && rm -f "$CSE_IDS_FILE"
      [ -n "$CHL_IDS_FILE" ] && rm -f "$CHL_IDS_FILE"
      rm -f "$INCIDENTS_FP_COUNTER_FILE" "$EVENTS_FP_COUNTER_FILE"
      exit "$exit_status"
    }
    incidents_fingerprint() {
      local idx
      idx="$(cat "$INCIDENTS_FP_COUNTER_FILE")"
      echo $((idx + 1)) >"$INCIDENTS_FP_COUNTER_FILE"
      if [ "$idx" -ge "${#INCIDENTS_FP_SEQ[@]}" ]; then
        echo "OVERRUN-incidents_fp-$idx"
        return
      fi
      echo "${INCIDENTS_FP_SEQ[$idx]}"
    }
    incident_events_fingerprint() {
      local idx
      idx="$(cat "$EVENTS_FP_COUNTER_FILE")"
      echo $((idx + 1)) >"$EVENTS_FP_COUNTER_FILE"
      if [ "$idx" -ge "${#EVENTS_FP_SEQ[@]}" ]; then
        echo "OVERRUN-events_fp-$idx"
        return
      fi
      echo "${EVENTS_FP_SEQ[$idx]}"
    }

    confirm_inventory_outage_convergence "2026-01-01T00:00:00+00:00"
    echo "FINAL_COUNTS cse_recovered=$CSE_RECOVERED_CALLS chl_recovered=$CHL_RECOVERED_CALLS cse_firing=$CSE_FIRING_CALLS chl_firing=$CHL_FIRING_CALLS cse_incident_after=$CSE_INCIDENT_AFTER_CALLS chl_incident_after=$CHL_INCIDENT_AFTER_CALLS cse_confirm_resolved=$CSE_CONFIRM_RESOLVED_CALLS chl_confirm_resolved=$CHL_CONFIRM_RESOLVED_CALLS incidents_fp=$INCIDENTS_FP_CALLS events_fp=$EVENTS_FP_CALLS"
  ) >"$log" 2>&1
  CASE_EXIT_CODE=$?
  CASE_LOG="$log"
}

# ---------------------------------------------------------------------
# CASE A: neither alert ever fires -- both recover (stay clean)
# immediately.
# Expected: no incident lifecycle required for either alert
# (incident-after/confirm-resolved never called for either), DB
# stability required and achieved, overall success.
# ---------------------------------------------------------------------
run_case "caseA" "0" "0" "" "" "" "" "" "" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -eq 0 ] && grep -q "cse_incident_after=0 chl_incident_after=0 cse_confirm_resolved=0 chl_confirm_resolved=0" "$CASE_LOG"; then
  ok "CASE A (neither alert fires): both recover immediately, no incident lifecycle required, succeeded"
else
  bad "CASE A failed (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE B: only CheckoutServerErrors fires (CheckoutHighLatency never
# leaves clean/inactive).
# Expected: CSE's own incident is captured and confirmed resolved;
# CHL's incident lifecycle is never invoked; DB stability required
# afterward; overall success.
# ---------------------------------------------------------------------
run_case "caseB" "1,0" "0,0" "0" "1" "0" "" "0" "" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -eq 0 ] \
   && grep -q "cse_incident_after=1 chl_incident_after=0 cse_confirm_resolved=1 chl_confirm_resolved=0" "$CASE_LOG"
then
  ok "CASE B (only CheckoutServerErrors fires): its own incident converged, CheckoutHighLatency's incident lifecycle never invoked, succeeded"
else
  bad "CASE B failed (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE C: only CheckoutHighLatency fires (CheckoutServerErrors never
# leaves clean/inactive) -- the symmetric counterpart to CASE B.
# ---------------------------------------------------------------------
run_case "caseC" "0,0" "1,0" "1" "0" "" "0" "" "0" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -eq 0 ] \
   && grep -q "cse_incident_after=0 chl_incident_after=1 cse_confirm_resolved=0 chl_confirm_resolved=1" "$CASE_LOG"
then
  ok "CASE C (only CheckoutHighLatency fires): its own incident converged, CheckoutServerErrors's incident lifecycle never invoked, succeeded"
else
  bad "CASE C failed (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE D: both alerts fire. Expected: TWO independent fresh incidents
# captured (one per alert, in separate evidence files -- the stub's
# own confirm-resolved dispatch structurally proves this by routing on
# $CSE_IDS_FILE/$CHL_IDS_FILE), BOTH confirm-resolved succeed, then DB
# stability, then overall success.
# ---------------------------------------------------------------------
run_case "caseD" "1,0" "1,0" "0" "0" "0" "0" "0" "0" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -eq 0 ] \
   && grep -q "cse_incident_after=1 chl_incident_after=1 cse_confirm_resolved=1 chl_confirm_resolved=1" "$CASE_LOG"
then
  ok "CASE D (both alerts fire): two independent incidents captured and confirmed resolved (never mixed), succeeded"
else
  bad "CASE D failed (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE E: CheckoutServerErrors fires and converges (recovers), but
# CheckoutHighLatency fires and NEVER recovers.
# Expected: wait_for_alerts_clean itself exhausts its bounded budget
# (90 attempts) -- Phase 4 FAILS before converge_alert_incident is
# ever invoked for EITHER alert (the required order gates all incident
# convergence behind BOTH alerts being simultaneously clean).
# ---------------------------------------------------------------------
cse_recovered_eventually="1,$(printf '0,%.0s' $(seq 1 89) | sed 's/,$//')"
chl_recovered_never="$(printf '1,%.0s' $(seq 1 90) | sed 's/,$//')"
run_case "caseE" "$cse_recovered_eventually" "$chl_recovered_never" "0" "0" "" "" "" "" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -ne 0 ] \
   && ! grep -q "FINAL_COUNTS" "$CASE_LOG" \
   && grep -q "CheckoutServerErrors and/or CheckoutHighLatency did not return to a clean inactive state" "$CASE_LOG"
then
  ok "CASE E (CSE converges, CHL remains firing): Phase 4 fails in wait_for_alerts_clean, before any incident/DB-stability work"
else
  bad "CASE E failed to behave as expected (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE F: both alerts fire and both recover; CheckoutServerErrors's own
# incident fully converges, but CheckoutHighLatency's incident NEVER
# resolves.
# Expected: CSE's own incident-after+confirm-resolved both succeed
# (exactly once each); CHL's incident-after succeeds but its own
# confirm-resolved exhausts its bounded budget (20 attempts); Phase 4
# FAILS; DB stability is never reached.
# ---------------------------------------------------------------------
chl_confirm_resolved_always_fail="$(printf '1,%.0s' $(seq 1 20) | sed 's/,$//')"
run_case "caseF" "1,0" "1,0" "0" "0" "0" "0" "0" "$chl_confirm_resolved_always_fail" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -ne 0 ] \
   && grep -q "confirmed: the fresh inventory-outage-triggered CheckoutServerErrors incident fully converged" "$CASE_LOG" \
   && grep -q "attempt 20/20: the fresh inventory-outage incident for '$CHL_TITLE_FOR_TEST' is not yet confirmed resolved" "$CASE_LOG" 2>/dev/null \
   && ! grep -q "4. Final database stability" "$CASE_LOG"
then
  ok "CASE F (CHL recovers but its incident never resolves): CSE fully converged first, CHL's own confirm-resolved budget exhausted, Phase 4 fails, DB stability never reached"
else
  bad "CASE F failed to behave as expected (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# CASE G: both alerts fire and both fully converge (two independent
# resolved incidents), but the global DB fingerprint NEVER stabilizes
# for three consecutive samples.
# Expected: bounded failure in wait_for_db_stability (its own budget is
# exhausted), never a false success, even though both alerts'
# incidents individually converged correctly.
# ---------------------------------------------------------------------
never_stable_values="$(python3 -c "print(','.join(f'v{i}' for i in range(33)))")"
never_stable_events="$(python3 -c "print(','.join(['x'] * 33))")"
run_case "caseG" "1,0" "1,0" "0" "0" "0" "0" "0" "0" "$never_stable_values" "$never_stable_events"
if [ "$CASE_EXIT_CODE" -ne 0 ] \
   && grep -q "confirmed: the fresh inventory-outage-triggered CheckoutServerErrors incident fully converged" "$CASE_LOG" \
   && grep -q "confirmed: the fresh inventory-outage-triggered CheckoutHighLatency incident fully converged" "$CASE_LOG" \
   && grep -q "never settled to three consecutive unchanged observations" "$CASE_LOG"
then
  ok "CASE G (both converge, DB keeps mutating): both incidents converged correctly, but bounded failure in the DB stability window, never a false success"
else
  bad "CASE G failed to behave as expected (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

# ---------------------------------------------------------------------
# Regression: persistent alert, neither ever recovers (the original
# settling-gate regression, preserved under the two-alert model).
# Expected: bounded failure, as today -- never reaches the firing/
# incident/DB-stability logic at all.
# ---------------------------------------------------------------------
recovered_always_fail="$(printf '1,%.0s' $(seq 1 90) | sed 's/,$//')"
firing_always_fail="$(printf '1,%.0s' $(seq 1 90) | sed 's/,$//')"
run_case "caseRegression" "$recovered_always_fail" "$recovered_always_fail" "$firing_always_fail" "$firing_always_fail" "" "" "" "" "a,a,a,a" "x,x,x,x"
if [ "$CASE_EXIT_CODE" -ne 0 ] && ! grep -q "FINAL_COUNTS" "$CASE_LOG"
then
  ok "CASE Regression (both alerts persistent, neither recovers): bounded failure as today, never reached incident/DB-stability logic"
else
  bad "CASE Regression failed to behave as expected (exit=$CASE_EXIT_CODE); log follows:"
  cat "$CASE_LOG" >&2
fi
rm -f "$CASE_LOG"

echo ""
echo "test-failure-simulation-settling.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
