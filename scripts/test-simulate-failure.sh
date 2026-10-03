#!/usr/bin/env bash
#
# test-simulate-failure.sh — Focused tests for scripts/simulate-failure.sh's
# scenario-selection, safety-check, failure-handling, and
# restoration-behavior logic. Does NOT require Docker, Compose, or any
# running service: every case here either exercises an argument-
# parsing/safety refusal that happens before any Docker/network call
# (run as a real subprocess, asserting exit code + stderr), or
# exercises restore_target()/on_exit() in isolation after `source`-ing
# simulate-failure.sh (which, per its own guard at the bottom, defines
# functions only and runs nothing when sourced) with `docker` and
# `wait_healthy` stubbed.
#
# This intentionally does NOT exercise the real Docker Compose fault
# injection, HTTP assertions, or the Prometheus/Alertmanager/incident
# chain — that is scripts/verify-failure-simulation.sh's job
# (`make verify-failure-simulation`), against a real running stack.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TARGET="$SCRIPT_DIR/simulate-failure.sh"

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

# expect_refused <description> <expected-stderr-substring> <args...>
# Runs simulate-failure.sh as a real subprocess with the given args
# and asserts it exits non-zero with a stderr message containing the
# expected substring, WITHOUT ever reaching a docker/curl call (every
# case below is refused during argument parsing/the allowlist check,
# which runs before section 1).
expect_refused() {
  local desc="$1" expect="$2"
  shift 2
  local out status
  out="$(bash "$TARGET" "$@" 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    bad "$desc: expected non-zero exit, got 0 (output: $out)"
    return
  fi
  if ! grep -qF "$expect" <<<"$out"; then
    bad "$desc: expected stderr to contain '$expect', got: $out"
    return
  fi
  ok "$desc"
}

echo "=== Scenario selection / safety checks (real subprocess, no Docker reached) ==="

expect_refused "no scenario given" "usage:"
expect_refused "unknown scenario refused" "unsupported/unsafe scenario" bogus-scenario
expect_refused "postgres is never an acceptable scenario name" "unsupported/unsafe scenario" postgres
expect_refused "otel-collector is not a Phase 4 scenario" "unsupported/unsafe scenario" otel-collector
expect_refused "--full-acceptance refused for inventory-outage" "only supported for payment-outage" inventory-outage --full-acceptance
expect_refused "unrecognized flag refused" "unrecognized argument" payment-outage --bogus-flag
expect_refused "unrecognized flag refused (inventory)" "unrecognized argument" inventory-outage --delete-everything

echo ""
echo "=== Static ordering check (stop-command failure/partial-stop safety) ==="

# The review's core fix: NEEDS_RESTORE must be set true BEFORE the
# stop command is even issued, not after it returns — otherwise a
# stop that fails partway through, or is interrupted mid-command,
# would leave the EXIT trap believing nothing needs restoring. This
# checks the actual source ordering, since a partial/failed `docker
# compose stop` cannot be reproduced without a real Docker daemon.
stop_line="$(grep -n 'docker compose -f "\$REPO_ROOT/docker-compose.yml" stop' "$TARGET" | head -1 | cut -d: -f1)"
flag_line="$(grep -n '^  NEEDS_RESTORE=true$' "$TARGET" | head -1 | cut -d: -f1)"
if [ -n "$stop_line" ] && [ -n "$flag_line" ] && [ "$flag_line" -lt "$stop_line" ]; then
  ok "NEEDS_RESTORE=true is set before the stop command is issued (line $flag_line < line $stop_line)"
else
  bad "NEEDS_RESTORE=true does not precede the stop command (flag_line=${flag_line:-<missing>} stop_line=${stop_line:-<missing>})"
fi

echo ""
echo "=== Restoration behavior (sourced; docker/wait_healthy stubbed, no real Docker) ==="

# Sourcing is safe: simulate-failure.sh only defines functions/vars at
# source time (its `main` only runs when executed directly, guarded by
# the BASH_SOURCE check at the bottom of the file).
# shellcheck source=/dev/null
source "$TARGET"
# simulate-failure.sh's own top-level `set -euo pipefail` just applied
# to THIS shell too, since `source` runs in the caller's context --
# turn errexit back off so one failing assertion below doesn't abort
# the rest of this test suite (pipefail/nounset are harmless to keep).
set +e

DOCKER_CALLS=()
docker() { DOCKER_CALLS+=("$*"); return 0; }
wait_healthy() { return 0; }

# Case: a stop that was merely ATTEMPTED (NEEDS_RESTORE=true set
# before the stop command, exactly as main() now does — see the
# static check above) is cleaned up, regardless of whether the stop
# command itself fully succeeded. This is the partial/failed-stop
# scenario: this test never simulates a separate "stop succeeded"
# signal, because the real script intentionally has none — attempted
# is sufficient to require cleanup.
TARGET_SERVICE="payment-service"
NEEDS_RESTORE=true
IDS_FILE=""
DOCKER_CALLS=()
restore_target
if [ "$NEEDS_RESTORE" = false ] && printf '%s\n' "${DOCKER_CALLS[@]:-}" | grep -q "start payment-service"; then
  ok "restore_target starts an attempted-stop target and clears NEEDS_RESTORE once verified healthy"
else
  bad "restore_target did not restore+verify an attempted-stop target (NEEDS_RESTORE=$NEEDS_RESTORE calls: ${DOCKER_CALLS[*]:-<none>})"
fi

# Case: idempotency — calling it again after a VERIFIED success must
# not re-issue a start.
calls_before=${#DOCKER_CALLS[@]}
restore_target
if [ "${#DOCKER_CALLS[@]}" -eq "$calls_before" ]; then
  ok "restore_target is idempotent after a verified success (second call issues no further docker commands)"
else
  bad "restore_target issued additional docker command(s) on a second call after success (calls: ${DOCKER_CALLS[*]:-<none>})"
fi

# Case: the normal-success path (target already verified-restored
# inline by section 7, NEEDS_RESTORE reset to false before the trap
# ever fires) must result in a no-op — never an unnecessary restart.
TARGET_SERVICE="inventory-service"
NEEDS_RESTORE=false
IDS_FILE=""
DOCKER_CALLS=()
restore_target
if [ "${#DOCKER_CALLS[@]}" -eq 0 ]; then
  ok "restore_target is a no-op when the target was never left stopped"
else
  bad "restore_target issued a docker command even though NEEDS_RESTORE was false (calls: ${DOCKER_CALLS[*]:-<none>})"
fi

# Case: an ids file is always cleaned up, even on an otherwise-no-op
# restore (covers the Ctrl+C-during-full-acceptance-wait path).
tmp_ids="$(mktemp)"
TARGET_SERVICE="payment-service"
NEEDS_RESTORE=false
IDS_FILE="$tmp_ids"
restore_target
if [ ! -e "$tmp_ids" ]; then
  ok "restore_target removes a leftover --ids-out temp file"
else
  bad "restore_target left $tmp_ids behind"
  rm -f "$tmp_ids"
fi

# Case: UNSUCCESSFUL restoration — this is the exact bug the review
# caught. restore_target must return failure (nonzero) and must NOT
# clear NEEDS_RESTORE just because a start/health-poll was attempted;
# the dependency is genuinely still down.
wait_healthy() { return 1; }
TARGET_SERVICE="payment-service"
NEEDS_RESTORE=true
IDS_FILE=""
DOCKER_CALLS=()
if restore_target; then
  bad "restore_target reported success even though wait_healthy never confirmed healthy"
elif [ "$NEEDS_RESTORE" = true ]; then
  ok "restore_target returns failure and leaves NEEDS_RESTORE=true when health can never be verified"
else
  bad "restore_target returned failure but incorrectly cleared NEEDS_RESTORE anyway"
fi

# Case: unlike the old RESTORE_DONE-style flag, a FAILED restoration
# must be retried on a subsequent call, never silently skipped.
calls_after_first_failure=${#DOCKER_CALLS[@]}
restore_target
if [ "${#DOCKER_CALLS[@]}" -gt "$calls_after_first_failure" ]; then
  ok "a failed restoration is retried on a subsequent call, not skipped"
else
  bad "a failed restoration was not retried on a subsequent call (calls stayed at $calls_after_first_failure)"
fi
wait_healthy() { return 0; }

echo ""
echo "=== on_exit behavior (exit-code propagation, no recursive cleanup) ==="

# Case: on_exit must force a nonzero exit if restoration cannot be
# verified healthy, even though the scenario otherwise reached a clean
# exit — "PASS"/a 0 exit must never be reported while a dependency is
# left down.
bash -c '
  source "'"$TARGET"'"
  docker() { return 0; }
  wait_healthy() { return 1; }
  TARGET_SERVICE="payment-service"
  NEEDS_RESTORE=true
  IDS_FILE=""
  true
  on_exit
' >/tmp/test-sim-onexit-1.$$ 2>&1
status1=$?
rm -f /tmp/test-sim-onexit-1.$$
if [ "$status1" -ne 0 ]; then
  ok "on_exit forces a nonzero exit when restoration cannot be verified, even after an otherwise-clean run"
else
  bad "on_exit returned 0 despite restoration never being verified healthy"
fi

# Case: if the scenario was already failing with a specific nonzero
# status, on_exit must preserve that exact status rather than
# overwrite it with a generic 1, even when restoration also fails.
# `set +e` after sourcing is required here: simulate-failure.sh's own
# `set -euo pipefail` is still active in this `bash -c` subshell (a
# consequence of `source`), and without disabling it, `( exit 7 )`
# would trigger errexit and terminate the subshell BEFORE `on_exit` is
# ever reached -- the test would then "pass" only because $? happened
# to already be 7 from errexit's own abort, not because on_exit itself
# preserved anything. Asserting on_exit's own cleanup-failure output
# (not just the final exit code) is what actually proves on_exit ran.
bash -c '
  source "'"$TARGET"'"
  set +e
  docker() { return 0; }
  wait_healthy() { return 1; }
  TARGET_SERVICE="payment-service"
  NEEDS_RESTORE=true
  IDS_FILE=""
  ( exit 7 )
  on_exit
' >/tmp/test-sim-onexit-2.$$ 2>&1
status2=$?
output2="$(cat /tmp/test-sim-onexit-2.$$ 2>/dev/null)"
rm -f /tmp/test-sim-onexit-2.$$
if [ "$status2" -eq 7 ] && grep -qF "FAIL: cleanup could not verify payment-service healthy" <<<"$output2"; then
  ok "on_exit actually ran its failed-restoration path and preserved the original nonzero exit status (7)"
else
  bad "on_exit did not behave as expected (status=$status2, expected 7; output: $output2)"
fi

# Case: when restoration succeeds, on_exit preserves a clean (0) exit.
bash -c '
  source "'"$TARGET"'"
  docker() { return 0; }
  wait_healthy() { return 0; }
  TARGET_SERVICE="payment-service"
  NEEDS_RESTORE=true
  IDS_FILE=""
  true
  on_exit
' >/tmp/test-sim-onexit-3.$$ 2>&1
status3=$?
rm -f /tmp/test-sim-onexit-3.$$
if [ "$status3" -eq 0 ]; then
  ok "on_exit exits 0 when restoration succeeds and the scenario otherwise succeeded"
else
  bad "on_exit did not exit 0 despite successful restoration (got $status3)"
fi

# Case: fail() exits non-zero and writes to stderr, never stdout —
# every scenario step above relies on this to abort loudly.
fail_out="$( { fail "synthetic failure for testing" > /tmp/test-sim-fail-stdout.$$ ; } 2>&1 )"
fail_status=$?
fail_stdout="$(cat /tmp/test-sim-fail-stdout.$$ 2>/dev/null)"
rm -f /tmp/test-sim-fail-stdout.$$
if [ "$fail_status" -ne 0 ] && [ -z "$fail_stdout" ] && grep -qF "FAIL: synthetic failure for testing" <<<"$fail_out"; then
  ok "fail() exits non-zero and writes only to stderr"
else
  bad "fail() did not behave as expected (status=$fail_status stdout='$fail_stdout' stderr/combined='$fail_out')"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
