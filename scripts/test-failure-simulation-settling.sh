#!/usr/bin/env bash
#
# test-failure-simulation-settling.sh — Focused, no-Docker regression
# for scripts/verify-failure-simulation.sh's new
# `wait_for_checkout_server_errors_clean` settling gate (added after
# the inventory-outage scenario, before Phase 4 declares acceptance):
# bounded, condition-based polling of the SAME shared CheckoutServerErrors
# alert scripts/verify-alerting.py's own "recovered" subcommand checks,
# never a fixed sleep.
#
# Extracts the REAL function body directly out of
# verify-failure-simulation.sh (never a reimplementation/duplicate of
# its polling logic) via `sed`, since that script is not safe to
# `source` as a whole -- unlike verify-remediation.sh/
# simulate-failure.sh, it has no bottom `main()`/BASH_SOURCE guard and
# runs real `docker compose`/`curl` calls immediately at its own top
# level. Stubs the `python3 .../verify-alerting.py recovered ...` call
# (the function's only external dependency) and `sleep` (so this test
# never actually waits), then drives the extracted function through
# three scenarios with a configurable, tiny attempt budget -- never
# minutes of real waiting.

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

# Extract ONLY the real wait_for_checkout_server_errors_clean function
# body (never the rest of the script, which has real side effects at
# its own top level) and define it in THIS process.
FUNCTION_SOURCE="$(sed -n '/^wait_for_checkout_server_errors_clean() {/,/^}/p' "$TARGET")"
if [ -z "$FUNCTION_SOURCE" ]; then
  echo "FAIL - could not extract wait_for_checkout_server_errors_clean from $TARGET -- has it been renamed/removed?" >&2
  exit 1
fi
eval "$FUNCTION_SOURCE"

# Dummy values -- never actually used for a real connection, since
# `python3` itself is stubbed below; only present so the function's
# own argument-construction doesn't reference an unset variable.
SCRIPT_DIR_FOR_FUNCTION="$SCRIPT_DIR"
PROMETHEUS_URL="http://127.0.0.1:9090"
ALERTMANAGER_URL="http://127.0.0.1:9093"
SCRIPT_DIR="$SCRIPT_DIR_FOR_FUNCTION"

# never actually sleeps -- this test proves the POLLING/attempt-
# counting behavior, never real wall-clock timing.
sleep() { :; }

# --- Scenario-sequenced `python3` stub -----------------------------
#
# Each test case sets PYTHON3_EXIT_SEQUENCE (a space-separated list of
# exit codes, one per expected call) before invoking the function under
# test; the stub consumes one entry per call and records how many
# times it was actually invoked in PYTHON3_CALL_COUNT.
PYTHON3_EXIT_SEQUENCE=()
PYTHON3_CALL_COUNT=0

python3() {
  local idx=$PYTHON3_CALL_COUNT
  PYTHON3_CALL_COUNT=$((PYTHON3_CALL_COUNT + 1))
  if [ "$idx" -ge "${#PYTHON3_EXIT_SEQUENCE[@]}" ]; then
    echo "  (stub) python3 called more times (${PYTHON3_CALL_COUNT}) than the configured sequence (${#PYTHON3_EXIT_SEQUENCE[@]}) provides for" >&2
    return 1
  fi
  return "${PYTHON3_EXIT_SEQUENCE[$idx]}"
}

# ---------------------------------------------------------------------
# CASE 1: pending, pending, inactive -- recovered-check fails twice
# (alert state pending both times, from this function's point of view
# simply "not yet confirmed clean"), succeeds on the third attempt.
# Expected: polling continues past the first two failures, succeeds
# only once the third (clean) result is seen, using exactly 3 calls.
# ---------------------------------------------------------------------
PYTHON3_EXIT_SEQUENCE=(1 1 0)
PYTHON3_CALL_COUNT=0
if wait_for_checkout_server_errors_clean 5 0; then
  if [ "$PYTHON3_CALL_COUNT" -eq 3 ]; then
    ok "case 1 (pending, pending, inactive): succeeded after exactly 3 attempts"
  else
    bad "case 1: succeeded but with $PYTHON3_CALL_COUNT calls, expected exactly 3"
  fi
else
  bad "case 1: expected success (eventual inactive), got failure"
fi

# ---------------------------------------------------------------------
# CASE 2: firing, pending, inactive -- same shape as case 1 from this
# function's own point of view (it only ever distinguishes "clean" vs
# "not yet clean", via verify-alerting.py's own exit code -- it never
# itself parses which Prometheus rule state produced that exit code),
# proving the EXACT same continue-until-clean behavior regardless of
# which underlying alert state the first failing attempts represent.
# ---------------------------------------------------------------------
PYTHON3_EXIT_SEQUENCE=(1 1 0)
PYTHON3_CALL_COUNT=0
if wait_for_checkout_server_errors_clean 5 0; then
  if [ "$PYTHON3_CALL_COUNT" -eq 3 ]; then
    ok "case 2 (firing, pending, inactive): succeeded after exactly 3 attempts"
  else
    bad "case 2: succeeded but with $PYTHON3_CALL_COUNT calls, expected exactly 3"
  fi
else
  bad "case 2: expected success (eventual inactive), got failure"
fi

# ---------------------------------------------------------------------
# CASE 3: never becomes inactive within the configured attempts.
# Expected: nonzero failure from the function itself, after EXACTLY
# the configured number of attempts (never fewer, never more -- no
# retry beyond the bound, and no silent early return).
# ---------------------------------------------------------------------
PYTHON3_EXIT_SEQUENCE=(1 1 1 1)
PYTHON3_CALL_COUNT=0
if wait_for_checkout_server_errors_clean 4 0; then
  bad "case 3: expected failure (never clean within budget), got success"
else
  if [ "$PYTHON3_CALL_COUNT" -eq 4 ]; then
    ok "case 3 (never clean): failed after exactly the configured 4 attempts, never fewer/more"
  else
    bad "case 3: failed but with $PYTHON3_CALL_COUNT calls, expected exactly 4"
  fi
fi

# Case 3's own consequence in the REAL script: a nonzero return from
# wait_for_checkout_server_errors_clean feeds directly into `fail`
# (which `exit 1`s immediately) -- the script's final "PHASE 4
# FAILURE-SIMULATION ACCEPTANCE VERIFIED" echo is textually AFTER that
# call and is therefore structurally unreachable on this path. Confirm
# that ordering directly against the real file (not just asserted in
# a comment), so a future edit that reordered these two can never
# silently regress unnoticed.
settling_gate_line="$(grep -n 'wait_for_checkout_server_errors_clean 90 5' "$TARGET" | head -1 | cut -d: -f1)"
pass_message_line="$(grep -n 'PHASE 4 FAILURE-SIMULATION ACCEPTANCE VERIFIED' "$TARGET" | head -1 | cut -d: -f1)"
if [ -n "$settling_gate_line" ] && [ -n "$pass_message_line" ] && [ "$settling_gate_line" -lt "$pass_message_line" ]; then
  ok "the settling gate's own call site appears BEFORE the final acceptance message in $TARGET"
else
  bad "the settling gate's own call site must appear BEFORE the final acceptance message in $TARGET (settling_gate_line=$settling_gate_line pass_message_line=$pass_message_line)"
fi

echo ""
echo "test-failure-simulation-settling.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
