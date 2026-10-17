#!/usr/bin/env bash
#
# test-canonical-incident-selection.sh — Focused, no-Docker regression
# for scripts/verify-investigator.sh's centralized
# select_canonical_phase4_incident_id helper (CI cross-phase
# stabilization audit, Part B/D): proves the SAME real function
# verify-investigator.sh/verify-rag.sh/verify-agent-runtime.sh all now
# call deterministically selects payment-outage's own earlier incident
# over inventory-outage's own later one in freshness-proven (CI) mode,
# never a bare "most recent"/`matches[0]` pick that depends on list
# order.
#
# `source`s verify-investigator.sh directly at this script's own top
# level (which, per its own guard at the bottom, defines functions
# only and runs nothing when sourced -- the same convention
# scripts/test-verify-investigator-restore.sh already establishes) and
# exercises the real function body with synthetic JSON, never a
# reimplementation of its own selection logic. No subshell is needed:
# `source` never forks, so PASS/FAIL accumulate directly in this
# script's own shell.

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

# incidents_json <id> <first_seen_at> [<id> <first_seen_at> ...]
# Builds a minimal GET /api/v1/incidents-shaped JSON body with the
# real CheckoutServerErrors title on every item -- the only fields
# select_canonical_phase4_incident_id itself ever reads.
incidents_json() {
  python3 -c "
import json, sys
args = sys.argv[1:]
items = [
    {'id': args[i], 'title': 'checkout-service is returning HTTP 5xx errors', 'first_seen_at': args[i + 1]}
    for i in range(0, len(args), 2)
]
print(json.dumps({'items': items}))
" "$@"
}

# shellcheck disable=SC1090
source "$TARGET"

# ---------------------------------------------------------------------
# Main scenario: a stale incident before the checkpoint, PAYMENT at
# T1, INVENTORY at T2 (T2 > T1) -- deliberately listed with INVENTORY
# FIRST in JSON/list order, so a bare `matches[0]` would have picked
# the WRONG one. In freshness-proven mode, canonical selection must be
# PAYMENT (the earliest after the checkpoint), regardless of list
# order.
# ---------------------------------------------------------------------
PHASE5_FRESHNESS_CHECKPOINT="2026-01-01T00:00:00+00:00"
body="$(incidents_json \
  inventory-id "2026-01-01T00:05:00+00:00" \
  payment-id "2026-01-01T00:01:00+00:00" \
  stale-id "2025-01-01T00:00:00+00:00")"
result="$(select_canonical_phase4_incident_id "$body")"
if [ "$result" = "payment-id" ]; then
  ok "main scenario: selected payment-id (earliest after checkpoint), despite inventory-id sorting first in list order"
else
  bad "main scenario: expected payment-id, got [$result]"
fi

# ---------------------------------------------------------------------
# No matches at all after the checkpoint -> empty result (the real
# caller's own `[ -n "$INCIDENT_ID" ] || fail ...` turns this into a
# hard failure -- this test only proves the SELECTION itself returns
# nothing to silently pick).
# ---------------------------------------------------------------------
PHASE5_FRESHNESS_CHECKPOINT="2027-01-01T00:00:00+00:00"
body="$(incidents_json payment-id "2026-01-01T00:01:00+00:00")"
result="$(select_canonical_phase4_incident_id "$body")"
if [ -z "$result" ]; then
  ok "no matches after the checkpoint: selection returns empty (never fabricates a choice)"
else
  bad "no matches after the checkpoint: expected empty, got [$result]"
fi

# ---------------------------------------------------------------------
# Two incidents tie on the EXACT same earliest first_seen_at after the
# checkpoint -> AMBIGUOUS, never silently picks one.
# ---------------------------------------------------------------------
PHASE5_FRESHNESS_CHECKPOINT="2026-01-01T00:00:00+00:00"
body="$(incidents_json a "2026-01-01T00:01:00+00:00" b "2026-01-01T00:01:00+00:00")"
result="$(select_canonical_phase4_incident_id "$body")"
case "$result" in
  AMBIGUOUS:*)
    ok "tied earliest timestamps: correctly reported ambiguous ($result), never silently picked one"
    ;;
  *)
    bad "tied earliest timestamps: expected AMBIGUOUS:..., got [$result]"
    ;;
esac

# ---------------------------------------------------------------------
# Historical/local mode (PHASE5_FRESHNESS_CHECKPOINT unset/empty):
# preserves the ORIGINAL behavior exactly -- the list's own natural
# order (`matches[0]`), i.e. whichever item the API happened to return
# first (control-plane orders by last_seen_at DESC in practice, but
# this helper itself never re-sorts in this mode).
# ---------------------------------------------------------------------
PHASE5_FRESHNESS_CHECKPOINT=""
body="$(incidents_json inventory-id "2026-01-01T00:05:00+00:00" payment-id "2026-01-01T00:01:00+00:00")"
result="$(select_canonical_phase4_incident_id "$body")"
if [ "$result" = "inventory-id" ]; then
  ok "historical/local mode: preserved the original most-recent/list-order selection (inventory-id, listed first)"
else
  bad "historical/local mode: expected inventory-id (list order), got [$result]"
fi

echo ""
echo "test-canonical-incident-selection.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
