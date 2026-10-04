#!/usr/bin/env bash
#
# test-verify-investigator-restore.sh — Focused tests for
# scripts/verify-investigator.sh's on_exit provider-restoration logic
# (Phase 5 correction round #2, issue 4). Does NOT require Docker,
# Compose, or any running service: `source`s verify-investigator.sh
# (which, per its own guard at the bottom, defines functions only and
# runs nothing when sourced) with `docker`, `wait_healthy`, and
# `investigator_provider_mode` stubbed, then invokes on_exit directly
# -- the same convention scripts/simulate-failure.sh /
# scripts/test-simulate-failure.sh already establish for this
# repository.
#
# The bug this guards against: restoring by merely `unset`-ing the
# override env var and trusting ambient environment/.env resolution to
# land back on the same effective provider mode. The fix instead
# explicitly re-exports the CAPTURED original mode before restarting.
# Each case below proves the EXPLICIT re-export happened by capturing
# $INVESTIGATOR_LLM_PROVIDER's value at the exact moment the stubbed
# `docker compose up` is invoked inside on_exit -- not by trusting
# on_exit's own success/failure reporting alone.
#
# This intentionally does NOT exercise a real Docker Compose restart
# or real investigator-service health -- that is
# scripts/verify-investigator.sh's own job (`make verify-investigator`),
# against a real running stack.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TARGET="$SCRIPT_DIR/verify-investigator.sh"

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

# run_on_exit <capture_file> <original_mode> <restored_mode_reported> <ambient_provider_before>
# Sources $TARGET in a fresh subshell, stubs docker/wait_healthy/
# investigator_provider_mode, optionally pre-seeds
# INVESTIGATOR_LLM_PROVIDER to simulate an ambient/.env value that
# disagrees with the captured original mode, then calls on_exit
# directly. Prints on_exit's exit status on stdout; writes whatever
# INVESTIGATOR_LLM_PROVIDER was set to at the moment `docker compose
# up` ran into <capture_file>.
run_on_exit() {
  local capture_file="$1" original_mode="$2" restored_mode_reported="$3" ambient_before="${4:-}"
  rm -f "$capture_file"
  (
    source "$TARGET"
    docker() {
      if [ "$1" = "compose" ] && [ "$2" = "up" ]; then
        echo "${INVESTIGATOR_LLM_PROVIDER:-<unset>}" > "$capture_file"
      fi
      return 0
    }
    wait_healthy() { return 0; }
    investigator_provider_mode() { echo "$restored_mode_reported"; }
    [ -n "$ambient_before" ] && export INVESTIGATOR_LLM_PROVIDER="$ambient_before"
    ORIGINAL_PROVIDER_MODE="$original_mode"
    NEEDS_PROVIDER_RESTORE=true
    on_exit
  ) >/tmp/test-vi-restore-out.$$ 2>&1
  echo $?
  rm -f /tmp/test-vi-restore-out.$$
}

echo "=== on_exit explicitly re-exports the captured original provider mode ==="

# Case: restoring from original mode "openai".
capture="/tmp/test-vi-capture-openai.$$"
status="$(run_on_exit "$capture" "openai" "openai")"
captured="$(cat "$capture" 2>/dev/null || echo '<missing>')"
rm -f "$capture"
if [ "$status" -eq 0 ] && [ "$captured" = "openai" ]; then
  ok "restores from original mode 'openai': explicitly re-exported before restart, confirmed after"
else
  bad "restoring to 'openai' failed (exit=$status captured='$captured')"
fi

# Case: restoring from original mode "stub".
capture="/tmp/test-vi-capture-stub.$$"
status="$(run_on_exit "$capture" "stub" "stub")"
captured="$(cat "$capture" 2>/dev/null || echo '<missing>')"
rm -f "$capture"
if [ "$status" -eq 0 ] && [ "$captured" = "stub" ]; then
  ok "restores from original mode 'stub': explicitly re-exported before restart, confirmed after"
else
  bad "restoring to 'stub' failed (exit=$status captured='$captured')"
fi

# Case: environment/.env precedence mismatch -- the ambient
# INVESTIGATOR_LLM_PROVIDER (as if left over from .env or a prior
# export) disagrees with the real captured original mode. The fix
# must force the CAPTURED value regardless of what ambient resolution
# would otherwise have produced -- this is exactly the scenario a bare
# `unset` would get wrong (it would silently leave the mismatched
# ambient value in place instead of the real original mode).
capture="/tmp/test-vi-capture-mismatch.$$"
status="$(run_on_exit "$capture" "stub" "stub" "openai")"
captured="$(cat "$capture" 2>/dev/null || echo '<missing>')"
rm -f "$capture"
if [ "$status" -eq 0 ] && [ "$captured" = "stub" ]; then
  ok "explicit re-export overrides an ambient/.env-mismatched INVESTIGATOR_LLM_PROVIDER ('openai') with the captured original mode ('stub')"
else
  bad "environment/.env precedence mismatch case failed (exit=$status captured='$captured', expected 'stub')"
fi

# Case: on_exit still fails loudly (nonzero) when the restored mode
# can never be confirmed -- the restoration-verification logic itself
# must remain unchanged by the issue 4 fix.
capture="/tmp/test-vi-capture-unconfirmed.$$"
status="$(run_on_exit "$capture" "openai" "stub")"
captured="$(cat "$capture" 2>/dev/null || echo '<missing>')"
rm -f "$capture"
if [ "$status" -ne 0 ] && [ "$captured" = "openai" ]; then
  ok "on_exit still fails nonzero when the post-restart mode doesn't match the captured original (restoration-verification preserved)"
else
  bad "on_exit did not fail as expected when restoration could not be confirmed (exit=$status captured='$captured')"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
