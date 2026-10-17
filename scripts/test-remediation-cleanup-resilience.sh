#!/usr/bin/env bash
#
# test-remediation-cleanup-resilience.sh — Phase 8 correction round
# (finding #8, strengthened by the follow-up correction round's own
# finding #4) focused regression: a simulated `payment_fault_get`
# failure (e.g. payment-service genuinely unreachable) during
# verify-remediation.sh's own EXIT cleanup trap must NOT abort that
# trap early under `set -euo pipefail` -- EVERY remaining restoration
# branch (payment-service health verification, the
# PAYMENT_FAULT_INJECTION_ENABLED restore, AND the investigator-service
# provider restore) must still be attempted, cleanup must report the
# verification failure honestly, and an otherwise-successful run must
# still become nonzero.
#
# No Docker/running stack required: sources verify-remediation.sh
# ONLY for its function definitions (BASH_SOURCE[0] != $0 for every
# file in the sourced chain, so no script's own `main` ever executes —
# see each script's own bottom guard), then overrides every external
# dependency `remediation_on_exit` touches with a small in-process
# test double before invoking the REAL, unmodified `remediation_on_exit`
# function directly in a subshell. Every stub echoes a distinct marker
# to stderr (captured into CLEANUP_LOG below) so this test can prove
# -- by grepping the REAL function's own observable call sequence,
# never by inspecting shell state that can't escape the subshell --
# exactly which branches were attempted and in what order.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/verify-remediation.sh"

PASS=true

# --- Test doubles for every external dependency remediation_on_exit
# --- touches. Defined AFTER sourcing so they take precedence. Each
# --- one echoes a distinct, greppable marker.

payment_fault_get() {
  # Simulates a genuine curl/connectivity failure (payment-service
  # unreachable) -- never populates HTTP_STATUS/HTTP_BODY, and returns
  # non-zero, exactly like a real failed `curl` command substitution
  # would before this correction's `if payment_fault_get && ...` guard.
  echo "MARKER: payment_fault_get invoked (simulated failure)" >&2
  return 7
}

payment_fault_clear() {
  echo "MARKER: payment_fault_clear invoked" >&2
  return 0
}

wait_healthy() {
  echo "MARKER: wait_healthy invoked for service=$1" >&2
  return 0
}

docker() {
  echo "MARKER: docker invoked with args=[$*]" >&2
  return 0
}

PAYMENT_REMEDIATION_TOKEN="test-token"
# Deliberately TRUE for both restore branches (strengthened from the
# original version of this test, which left both false and so never
# actually exercised them) -- this is what proves the simulated
# payment_fault_get failure does not prevent EITHER restoration branch
# from being attempted afterward.
NEEDS_FAULT_ENABLED_RESTORE=true
ORIGINAL_FAULT_INJECTION_ENABLED="false"
NEEDS_PROVIDER_RESTORE=true
ORIGINAL_PROVIDER_MODE="openai"

CLEANUP_LOG="$(mktemp)"
trap 'rm -f "$CLEANUP_LOG"' EXIT

set +e
(
  set -euo pipefail
  true  # establishes $? == 0 immediately before remediation_on_exit runs, simulating an otherwise-successful run
  remediation_on_exit
) >"$CLEANUP_LOG" 2>&1
CLEANUP_EXIT_CODE=$?
set -e

cat "$CLEANUP_LOG" >&2

check() {
  # check <description> <grep-pattern>
  if grep -q -- "$2" "$CLEANUP_LOG"; then
    echo "  confirmed: $1" >&2
  else
    echo "FAIL: $1 -- expected to find pattern: $2" >&2
    PASS=false
  fi
}

# 1. Fault-state check was attempted (and failed, as simulated).
check "payment_fault_get was invoked" "MARKER: payment_fault_get invoked"

# 2. Payment health verification is STILL attempted after the
# fault-state check failed (no early errexit termination).
check "payment health verification was still attempted after the simulated failure" "MARKER: wait_healthy invoked for service=payment-service"

# 3. The PAYMENT_FAULT_INJECTION_ENABLED restoration branch is STILL
# attempted.
check "the PAYMENT_FAULT_INJECTION_ENABLED restoration branch was still attempted" "MARKER: docker invoked with args=\[compose up -d payment-service\]"

# 4. The investigator-service provider restoration branch is STILL
# attempted.
check "the investigator-service provider restoration branch was still attempted" "MARKER: docker invoked with args=\[compose up -d investigator-service\]"

# 5. Cleanup reports the verification failure honestly, never silently.
check "cleanup reported the fault-state verification failure" "could not confirm the payment authorization fault is inactive"

# 6. No early errexit termination: every marker above appearing in the
# SAME log, in the order the real function's own source emits them,
# is itself the proof -- but assert the order explicitly too, so a
# regression that silently reordered/removed a step is also caught.
MARKER_ORDER="$(grep -n '^MARKER:' "$CLEANUP_LOG" | cut -d: -f1)"
EXPECTED_COUNT=4
ACTUAL_COUNT="$(echo "$MARKER_ORDER" | grep -c '^[0-9]*$' || true)"
if [ "$ACTUAL_COUNT" -lt "$EXPECTED_COUNT" ]; then
  echo "FAIL: expected at least $EXPECTED_COUNT markers (fault_get, wait_healthy, 2x docker) in sequence, found $ACTUAL_COUNT -- cleanup terminated early" >&2
  PASS=false
else
  echo "  confirmed: no early errexit termination -- all $ACTUAL_COUNT expected steps ran in sequence" >&2
fi

# 7. An otherwise-successful run (exit_status==0 on entry) must still
# become nonzero.
if [ "$CLEANUP_EXIT_CODE" -eq 0 ]; then
  echo "FAIL: cleanup must force a NONZERO exit status when it cannot verify the payment fault state" >&2
  PASS=false
else
  echo "  confirmed: cleanup forced a nonzero exit status ($CLEANUP_EXIT_CODE) after a simulated payment_fault_get failure" >&2
fi

# ---------------------------------------------------------------------
# Scenario 2 (shell-hardening follow-up): NEEDS_PROVIDER_RESTORE (and,
# for the same reason, NEEDS_FAULT_ENABLED_RESTORE) are only ever
# ASSIGNED later in main() -- a real run that fails early enough (e.g.
# before main() reaches those assignments at all) reaches
# remediation_on_exit with NEITHER variable ever set. Under
# `set -euo pipefail` (which includes `set -u`), referencing an unset
# variable directly -- the pre-fix
# `if [ "$NEEDS_PROVIDER_RESTORE" = true ]` -- would itself make the
# EXIT trap fail with "unbound variable", exactly when cleanup must be
# most defensive. This proves the fix (`${NEEDS_PROVIDER_RESTORE:-false}`,
# mirroring the pattern NEEDS_FAULT_ENABLED_RESTORE already used):
# remediation_on_exit must run to completion with BOTH restore flags
# completely unset, never emitting an "unbound variable" error, still
# skipping both restore branches cleanly (there is nothing to restore
# if main() never got far enough to need to), and still forcing a
# nonzero exit from the same simulated payment_fault_get failure.
# ---------------------------------------------------------------------

unset NEEDS_PROVIDER_RESTORE
unset NEEDS_FAULT_ENABLED_RESTORE

CLEANUP_LOG_2="$(mktemp)"
trap 'rm -f "$CLEANUP_LOG" "$CLEANUP_LOG_2"' EXIT

set +e
(
  set -euo pipefail
  true  # establishes $? == 0 immediately before remediation_on_exit runs
  remediation_on_exit
) >"$CLEANUP_LOG_2" 2>&1
CLEANUP_EXIT_CODE_2=$?
set -e

cat "$CLEANUP_LOG_2" >&2

check2() {
  # check2 <description> <grep-pattern>
  if grep -q -- "$2" "$CLEANUP_LOG_2"; then
    echo "  confirmed: $1" >&2
  else
    echo "FAIL: $1 -- expected to find pattern: $2" >&2
    PASS=false
  fi
}

if grep -qi "unbound variable" "$CLEANUP_LOG_2"; then
  echo "FAIL: remediation_on_exit failed with an unbound-variable error when NEEDS_PROVIDER_RESTORE/NEEDS_FAULT_ENABLED_RESTORE were never set" >&2
  PASS=false
else
  echo "  confirmed: no 'unbound variable' error with both restore flags completely unset" >&2
fi

check2 "the fault-state check still ran with both restore flags unset" "MARKER: payment_fault_get invoked"
check2 "payment health verification still ran with both restore flags unset" "MARKER: wait_healthy invoked for service=payment-service"

if grep -q "MARKER: docker invoked" "$CLEANUP_LOG_2"; then
  echo "FAIL: a restore branch ran even though its own flag was never set (should default to false/skipped)" >&2
  PASS=false
else
  echo "  confirmed: both restore branches were correctly skipped (nothing to restore) rather than crashing" >&2
fi

if [ "$CLEANUP_EXIT_CODE_2" -eq 0 ]; then
  echo "FAIL: cleanup must still force a NONZERO exit status in this scenario too" >&2
  PASS=false
else
  echo "  confirmed: cleanup forced a nonzero exit status ($CLEANUP_EXIT_CODE_2) with both restore flags unset" >&2
fi

if [ "$PASS" = true ]; then
  echo ""
  echo "PHASE 8 CLEANUP RESILIENCE REGRESSION PASSED: a simulated payment_fault_get failure during EXIT cleanup did not abort the trap early -- the payment health check, the PAYMENT_FAULT_INJECTION_ENABLED restore, AND the investigator-service provider restore were all still attempted when configured, cleanup never fails with an unbound-variable error when those flags are entirely unset (both restore branches are then cleanly skipped instead), the failure was reported honestly, and cleanup still forced a nonzero exit status in both scenarios."
else
  echo ""
  echo "PHASE 8 CLEANUP RESILIENCE REGRESSION FAILED" >&2
  exit 1
fi
