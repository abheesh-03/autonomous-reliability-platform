#!/usr/bin/env bash
#
# verify-web-console.sh — Phase 9 Gate F/G acceptance: runs the real
# Playwright browser E2E (services/web-console/e2e/phase9-workflow.spec.ts)
# against the live local stack (docker compose) -- never a mocked
# backend.
#
# Sources scripts/verify-investigator.sh purely for its already-proven
# section/fail/wait_healthy/investigator_provider_mode/on_exit helpers
# (sourcing only defines functions -- its own `main` is guarded at the
# bottom, so this never re-runs Phase 5's own acceptance flow). Forces
# investigator-service into the SAME deterministic stub LLM provider
# scripts/verify-remediation.sh already uses for its own acceptance run
# (no real paid API key required, no non-determinism), and relies on
# that file's own `on_exit` trap to ALWAYS restore the original
# provider mode, verified (never assumed), regardless of where this
# script or the Playwright run itself fails.
#
# The Playwright spec itself (services/web-console/e2e/support/backend.ts)
# owns the real controlled payment-authorization fault
# injection/clearing and its own cleanup -- this script never touches
# that fault directly; its only job is the investigator-service
# provider-mode bracket and invoking `npm run e2e`.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/verify-investigator.sh"

# This script's own combined EXIT cleanup -- restores BOTH
# PAYMENT_FAULT_INJECTION_ENABLED and investigator-service's provider
# mode. Never calls the inherited `on_exit` directly (same reasoning
# as verify-remediation.sh's own remediation_on_exit: on_exit
# re-captures `$?` at ITS OWN entry, which would be this wrapper's own
# exit code by the time it ran, silently corrupting the real original
# exit status) -- instead replicates that same provider-restore logic
# inline, using the exact same shared state
# (ORIGINAL_PROVIDER_MODE/NEEDS_PROVIDER_RESTORE) verify-investigator.sh
# already maintains.
web_console_on_exit() {
  local exit_status=$?

  if [ "${NEEDS_FAULT_ENABLED_RESTORE:-false}" = true ]; then
    echo "" >&2
    echo "-- cleanup: restoring payment-service's PAYMENT_FAULT_INJECTION_ENABLED to its original value ('$ORIGINAL_FAULT_INJECTION_ENABLED') --" >&2
    export PAYMENT_FAULT_INJECTION_ENABLED="$ORIGINAL_FAULT_INJECTION_ENABLED"
    if ! docker compose up -d payment-service >&2; then
      echo "FAIL: cleanup could not restart payment-service while restoring PAYMENT_FAULT_INJECTION_ENABLED -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    elif ! wait_healthy payment-service 20; then
      echo "FAIL: cleanup could not confirm payment-service healthy after restoring PAYMENT_FAULT_INJECTION_ENABLED -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    fi
  fi

  if [ "${NEEDS_PROVIDER_RESTORE:-false}" = true ]; then
    echo "" >&2
    echo "-- cleanup: restoring investigator-service to its original provider mode ('$ORIGINAL_PROVIDER_MODE') --" >&2
    export INVESTIGATOR_LLM_PROVIDER="$ORIGINAL_PROVIDER_MODE"
    if ! docker compose up -d investigator-service >&2; then
      echo "FAIL: cleanup could not restart investigator-service while restoring its provider mode -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
      exit "$exit_status"
    fi
    if ! wait_healthy investigator-service 20; then
      echo "FAIL: cleanup could not confirm investigator-service healthy after restoring its provider mode -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    else
      restored_mode="$(investigator_provider_mode)"
      if [ "$restored_mode" = "$ORIGINAL_PROVIDER_MODE" ]; then
        echo "-- cleanup: confirmed investigator-service restored to provider='$restored_mode' and healthy --" >&2
      else
        echo "FAIL: cleanup could not confirm the provider mode was restored (expected '$ORIGINAL_PROVIDER_MODE', got '${restored_mode:-<unreachable>}') -- manual investigation required" >&2
        [ "$exit_status" -eq 0 ] && exit_status=1
      fi
    fi
  fi

  exit "$exit_status"
}

main() {
cd "$REPO_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

for tok in CONTROL_PLANE_LIFECYCLE_TOKEN CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN \
           PAYMENT_FAULT_INJECTION_TOKEN PAYMENT_REMEDIATION_TOKEN; do
  [ -n "${!tok:-}" ] || fail "$tok is not set in .env -- run 'make remediation-secret-init' (or 'make db-up') first"
done

# Supersedes verify-investigator.sh's own `trap on_exit EXIT`
# registration (only the LAST `trap ... EXIT` registration takes
# effect) -- web_console_on_exit performs that same provider
# restoration itself (see its own docstring) in addition to this
# script's own PAYMENT_FAULT_INJECTION_ENABLED restore.
trap web_console_on_exit EXIT

section "0. Confirm every involved service is healthy (starting web-console if it is not already running -- unlike the other six, no earlier CI/local step brings it up)"
docker compose up -d web-console >/dev/null
for svc in control-plane investigator-service agent-runtime-service tool-gateway payment-service checkout-service web-console; do
  wait_healthy "$svc" 20 || fail "$svc is not healthy"
done
echo "  all seven involved services healthy"

section "1. Force investigator-service into the deterministic stub LLM provider for this run"
ORIGINAL_PROVIDER_MODE="$(investigator_provider_mode)"
[ -n "$ORIGINAL_PROVIDER_MODE" ] || fail "could not determine investigator-service's original provider mode"
export INVESTIGATOR_LLM_PROVIDER=stub
NEEDS_PROVIDER_RESTORE=true
docker compose up -d investigator-service >/dev/null
wait_healthy investigator-service 20 || fail "investigator-service is not healthy after forcing stub mode"

section "1b. Force payment-service's PAYMENT_FAULT_INJECTION_ENABLED=true for this run only (mirrors scripts/verify-remediation.sh's own section 0b -- never on by default)"
ORIGINAL_FAULT_INJECTION_ENABLED="${PAYMENT_FAULT_INJECTION_ENABLED:-false}"
export PAYMENT_FAULT_INJECTION_ENABLED=true
NEEDS_FAULT_ENABLED_RESTORE=true
docker compose up -d payment-service >/dev/null
wait_healthy payment-service 20 || fail "payment-service is not healthy after enabling fault injection"

section "2. Run the real Playwright browser E2E against the live stack"
if [ -f "$HOME/.nvm/nvm.sh" ]; then
  # shellcheck disable=SC1091
  source "$HOME/.nvm/nvm.sh"
  nvm use 24 >/dev/null 2>&1 || true
fi
# Fail FAST here, never silently continue on whatever Node happens to
# be on PATH -- a failed/absent `nvm use 24` above (no nvm installed,
# Node 24 not installed under nvm, CI providing Node 24 via a
# different mechanism entirely) must not be masked by `|| true` alone.
# This checks the REAL resulting `node` on PATH, not nvm's own exit
# status, so it catches every cause of a wrong Node version uniformly.
node_major="$(node -e 'console.log(process.versions.node.split(".")[0])' 2>/dev/null || true)"
[ "$node_major" = "24" ] || fail "this script requires Node.js 24 on PATH, but found '${node_major:-<unavailable>}' -- install/select Node 24 (e.g. 'nvm install 24 && nvm use 24') before re-running"
# Run in a SUBSHELL so this script's own cwd stays at REPO_ROOT --
# on_exit's own `docker compose` calls require that, and must still
# work correctly even if the subshell below fails. Chromium-only
# (never the full multi-browser Playwright install): idempotent, a
# no-op download when already cached (local and CI alike), matching
# `npm ci` further up assuming `@playwright/test` itself is already
# an installed devDependency.
( cd services/web-console && npx playwright install --with-deps chromium && npm run e2e )

echo ""
echo "PHASE 9 GATE F ACCEPTANCE VERIFIED: the real browser-driven operator workflow (start investigation, run, approve, continue workflow, remediate, monitoring-resolved) passed against the live stack, with zero protected tokens ever exposed to the browser."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
