#!/usr/bin/env bash
#
# verify-investigator.sh — Phase 5 real-evidence acceptance.
#
# Deliberately placed AFTER make verify-failure-simulation (Phase 4)
# in both the Makefile and CI ordering: rather than causing another
# real 8-9 minute outage, this reuses a real, already-persisted,
# resolved CheckoutServerErrors incident that run already produced —
# the exact same real incident (and its exact, real audit trail) a
# human operator would investigate after the fact.
#
# Freshness proof (Phase 5 correction round #5):
#   - In GitHub CI, PHASE5_FRESHNESS_CHECKPOINT is set (by the CI
#     workflow, to a timestamp captured immediately BEFORE the Phase 4
#     step runs) and REQUIRED to be before the selected incident's own
#     first_seen_at — this proves the incident reused here was
#     genuinely produced by THIS run, not a stale incident left over
#     from an earlier one.
#   - Standalone/local, PHASE5_FRESHNESS_CHECKPOINT is normally unset:
#     this script then runs in explicit HISTORICAL/LOCAL mode, loudly
#     announced, reusing whatever matching incident already exists
#     without claiming freshness it cannot prove.
#
# Forces investigator-service into INVESTIGATOR_LLM_PROVIDER=stub for
# this run only. The ORIGINAL provider mode is captured BEFORE the
# override and verified actually restored afterward (never assumed) —
# see on_exit below. This is the ONE place in the whole repository
# that ever sets that variable, so this script exercises the real HTTP
# evidence-collection pipeline (control-plane + Prometheus + Loki +
# Tempo, all real) end-to-end without needing a real, paid LLM API
# key. See docs/architecture/phase-5-ai-investigator.md.
#
# Never deletes or mutates anything: proves the opposite — that a real
# investigation request leaves the incident row and its COMPLETE,
# fully-paginated audit trail byte-for-byte unchanged.

# This file defines functions only; the actual verification run only
# happens when this file is executed directly (guarded at the very
# bottom), so a future scripts/test-verify-investigator-restore.sh can
# `source` it to unit-test on_exit's provider-restoration logic
# without touching Docker or a real stack -- the same convention
# scripts/simulate-failure.sh / scripts/test-simulate-failure.sh
# already establish for this repository.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
INVESTIGATOR_URL="${INVESTIGATOR_URL:-http://127.0.0.1:8001}"
CHECKOUT_SERVER_ERRORS_TITLE="checkout-service is returning HTTP 5xx errors"
# Unset (empty) by default -- see the freshness-proof note above.
PHASE5_FRESHNESS_CHECKPOINT="${PHASE5_FRESHNESS_CHECKPOINT:-}"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

cp_get() {
  local path="$1" response curl_exit=0
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' "$CONTROL_PLANE_URL$path")" || curl_exit=$?
  if [ "$curl_exit" -ne 0 ]; then
    HTTP_STATUS="000"
    HTTP_BODY=""
    return 0
  fi
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

# fetch_all_events_canonical <incident_id>
# Fully paginates GET /api/v1/incidents/{id}/events (a SMALL page size,
# deliberately, to force real multi-page traversal even for this
# platform's normally-tiny real audit histories) and prints one
# canonical, deterministically-ordered JSON array -- not just
# limit=100&offset=0's first page -- for byte-for-byte before/after
# comparison. Fails closed on a duplicate id or an inconsistent total
# across pages, exactly like scripts/verify-ingestion.py's own
# fetch_all_events.
fetch_all_events_canonical() {
  local incident_id="$1"
  python3 -c "
import json, sys, urllib.request

base = '$CONTROL_PLANE_URL'
incident_id = '$incident_id'
page_size = 2
items = []
seen_ids = set()
offset = 0
expected_total = None
while True:
    url = f'{base}/api/v1/incidents/{incident_id}/events?limit={page_size}&offset={offset}'
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = json.loads(resp.read())
    total = body.get('total', 0)
    if expected_total is None:
        expected_total = total
    elif total != expected_total:
        print(f'FAIL: total changed across pages ({expected_total} -> {total})', file=sys.stderr)
        sys.exit(1)
    page_items = body.get('items', [])
    for ev in page_items:
        if ev['id'] in seen_ids:
            print(f'FAIL: duplicate event id {ev[\"id\"]} returned across pages', file=sys.stderr)
            sys.exit(1)
        seen_ids.add(ev['id'])
    items.extend(page_items)
    offset += page_size
    if not page_items or offset >= total:
        break
if len(items) != expected_total:
    print(f'FAIL: fetched {len(items)} events but total={expected_total}', file=sys.stderr)
    sys.exit(1)
items.sort(key=lambda e: e['id'])
print(json.dumps(items, sort_keys=True))
"
}

wait_healthy() {
  local service="$1" attempts="${2:-20}"
  local i cid health
  for i in $(seq 1 "$attempts"); do
    cid="$(docker compose ps -q "$service" 2>/dev/null || true)"
    health="$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
    [ "$health" = "healthy" ] && return 0
    echo "  attempt $i/$attempts: $service health=${health:-<no container>}"
    sleep 3
  done
  return 1
}

investigator_provider_mode() {
  curl -fsS --connect-timeout 2 --max-time 10 "$INVESTIGATOR_URL/health/ready" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['llm_provider']['provider'])" 2>/dev/null || echo ""
}

# --- Provider-restoration safety (Phase 5 correction round #6) ------
#
# Captured BEFORE any override; restored and ACTIVELY VERIFIED (never
# assumed) by the single on_exit trap below, which forces a nonzero
# exit if restoration cannot be confirmed -- never `|| true`-masked,
# and never reported as clean success on an unverified restore.
ORIGINAL_PROVIDER_MODE=""
NEEDS_PROVIDER_RESTORE=false

on_exit() {
  local exit_status=$?
  if [ "$NEEDS_PROVIDER_RESTORE" = true ]; then
    echo "" >&2
    echo "-- cleanup: restoring investigator-service to its original provider mode ('$ORIGINAL_PROVIDER_MODE') --" >&2
    # Phase 5 correction round #2 (issue 4): explicitly re-export the
    # CAPTURED original mode rather than unsetting the override and
    # trusting ambient environment/.env resolution to land back on the
    # same effective value -- an exported shell var takes Compose
    # precedence over .env, so merely unsetting it here does not
    # guarantee the original mode is what Compose actually resolves to
    # next (e.g. if .env itself defines a different default/override).
    export INVESTIGATOR_LLM_PROVIDER="$ORIGINAL_PROVIDER_MODE"
    if ! docker compose up -d investigator-service >&2; then
      echo "FAIL: cleanup could not restart investigator-service while restoring its provider mode -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
      exit "$exit_status"
    fi
    if ! wait_healthy investigator-service 20; then
      echo "FAIL: cleanup could not confirm investigator-service healthy after restoring its provider mode -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
      exit "$exit_status"
    fi
    restored_mode="$(investigator_provider_mode)"
    if [ "$restored_mode" = "$ORIGINAL_PROVIDER_MODE" ]; then
      echo "-- cleanup: confirmed investigator-service restored to provider='$restored_mode' and healthy --" >&2
    else
      echo "FAIL: cleanup could not confirm the provider mode was restored (expected '$ORIGINAL_PROVIDER_MODE', got '${restored_mode:-<unreachable>}') -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    fi
  fi
  exit "$exit_status"
}

main() {
cd "$REPO_ROOT"

# Exactly one cleanup call site: the EXIT trap (on_exit), registered
# only once main actually runs -- sourcing this file for tests must
# never register a trap in the TEST script's own shell.
trap on_exit EXIT

section "0. Confirm control-plane and investigator-service are healthy"
wait_healthy control-plane 20 || fail "control-plane is not healthy"
wait_healthy investigator-service 20 || fail "investigator-service is not healthy before this script has touched it"

ORIGINAL_PROVIDER_MODE="$(investigator_provider_mode)"
[ -n "$ORIGINAL_PROVIDER_MODE" ] || fail "could not determine investigator-service's original provider mode via /health/ready"
echo "  original provider mode (to be restored afterward): $ORIGINAL_PROVIDER_MODE"

echo "  forcing investigator-service into INVESTIGATOR_LLM_PROVIDER=stub for this run only"
export INVESTIGATOR_LLM_PROVIDER=stub
NEEDS_PROVIDER_RESTORE=true
docker compose up -d investigator-service >/dev/null
wait_healthy investigator-service 20 || fail "investigator-service is not healthy after forcing stub mode"

ready_body="$(curl -fsS --connect-timeout 2 --max-time 10 "$INVESTIGATOR_URL/health/ready")"
echo "  /health/ready: $ready_body"
echo "$ready_body" | python3 -c "
import json, sys
raw = sys.stdin.read()
body = json.loads(raw)
assert body['llm_provider']['configured'] is True, body
assert body['llm_provider']['provider'] == 'stub', body['llm_provider']
assert 'api_key' not in raw.lower(), 'a credential-shaped field leaked into /health/ready'
"

if [ -n "$PHASE5_FRESHNESS_CHECKPOINT" ]; then
  section "1. Find a resolved CheckoutServerErrors incident created AFTER the CI freshness checkpoint"
  echo "  freshness checkpoint: $PHASE5_FRESHNESS_CHECKPOINT (incidents at or before this are refused)"
else
  echo ""
  echo "=== 1. HISTORICAL/LOCAL MODE: PHASE5_FRESHNESS_CHECKPOINT is not set ===" >&2
  echo "  WARNING: proceeding without a freshness checkpoint. This run will reuse whatever" >&2
  echo "  resolved CheckoutServerErrors incident already exists (the most recent one), but" >&2
  echo "  this does NOT prove that incident was produced by a run in this session. Set" >&2
  echo "  PHASE5_FRESHNESS_CHECKPOINT=<ISO8601> (e.g. captured immediately before" >&2
  echo "  'make verify-failure-simulation') for a freshness-verified run, as CI does." >&2
fi

cp_get "/api/v1/incidents?source=alertmanager&status=resolved&limit=100&offset=0"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents returned $HTTP_STATUS: $HTTP_BODY"

INCIDENT_ID="$(echo "$HTTP_BODY" | python3 -c "
import json, sys
from datetime import datetime

body = json.load(sys.stdin)
matches = [i for i in body['items'] if i['title'] == '$CHECKOUT_SERVER_ERRORS_TITLE']
checkpoint = '$PHASE5_FRESHNESS_CHECKPOINT'
if checkpoint:
    cutoff = datetime.fromisoformat(checkpoint)
    matches = [i for i in matches if datetime.fromisoformat(i['first_seen_at']) > cutoff]
print(matches[0]['id'] if matches else '')
")"
if [ -n "$PHASE5_FRESHNESS_CHECKPOINT" ]; then
  [ -n "$INCIDENT_ID" ] || fail "no resolved CheckoutServerErrors incident found with first_seen_at after $PHASE5_FRESHNESS_CHECKPOINT -- did the Phase 4 step actually run and persist an incident in this job?"
else
  [ -n "$INCIDENT_ID" ] || fail "no existing resolved CheckoutServerErrors incident found at all — run 'make verify-failure-simulation' first (see docs/architecture/phase-5-ai-investigator.md), then rerun this script"
fi
echo "  reusing real incident: $INCIDENT_ID"

section "2. Capture BEFORE state directly from control-plane's own real API (complete, fully-paginated audit history)"
cp_get "/api/v1/incidents/$INCIDENT_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$INCIDENT_ID returned $HTTP_STATUS"
INCIDENT_BEFORE="$HTTP_BODY"
STATUS_BEFORE="$(echo "$INCIDENT_BEFORE" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")"
UPDATED_AT_BEFORE="$(echo "$INCIDENT_BEFORE" | python3 -c "import json,sys; print(json.load(sys.stdin)['updated_at'])")"

EVENTS_BEFORE="$(fetch_all_events_canonical "$INCIDENT_ID")"
EVENTS_TOTAL_BEFORE="$(echo "$EVENTS_BEFORE" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")"
echo "  before: status=$STATUS_BEFORE updated_at=$UPDATED_AT_BEFORE events_total=$EVENTS_TOTAL_BEFORE (fully paginated)"
[ "$EVENTS_TOTAL_BEFORE" -ge 2 ] || fail "expected at least 2 real audit events (created + resolving) for this incident, found $EVENTS_TOTAL_BEFORE"

section "3. Request one real investigation (deterministic stub provider)"
inv_response="$(curl -s --connect-timeout 2 --max-time 30 -w '\n%{http_code}' -X POST "$INVESTIGATOR_URL/api/v1/investigations" \
  -H "Content-Type: application/json" \
  -d "{\"incident_id\": \"$INCIDENT_ID\"}")"
INV_STATUS="$(echo "$inv_response" | tail -1)"
INV_BODY="$(echo "$inv_response" | sed '$d')"
[ "$INV_STATUS" = "200" ] || fail "POST /api/v1/investigations returned $INV_STATUS: $INV_BODY"

section "4. Validate the real, structured investigation report: identity, provenance, provider metadata, citations"
echo "$INV_BODY" | python3 -c "
import json, sys
raw = sys.stdin.read()
body = json.loads(raw)

# Identity
assert body['incident_id'] == '$INCIDENT_ID', body['incident_id']
assert body['incident_status_at_investigation'] == '$STATUS_BEFORE', body['incident_status_at_investigation']

# Provider metadata -- confirms stub mode was genuinely in effect for
# THIS request, and that no credential is ever present.
assert body['provider']['configured'] is True, body['provider']
assert body['provider']['provider'] == 'stub', body['provider']
assert 'api_key' not in raw.lower(), 'a credential-shaped field leaked into the investigation response'

assert len(body['summary']) > 0
assert len(body['evidence']) >= 1, 'expected at least the incident-core evidence item'

# Evidence provenance: every item traceable to a real, allowlisted source.
sources = {o['source'] for o in body['source_outcomes']}
assert sources == {'control_plane', 'prometheus', 'loki', 'tempo'}, sources
for item in body['evidence']:
    assert item['source'] in sources, item
for outcome in body['source_outcomes']:
    assert outcome['status'] in ('ok', 'partial', 'no_data', 'unavailable'), outcome

evidence_ids = {e['id'] for e in body['evidence']}
assert evidence_ids == {f'E{i}' for i in range(1, len(evidence_ids) + 1)}, evidence_ids

# The deterministic stub must have produced a real, E1-backed
# observation -- proving this run actually exercised the citation-
# validation path, not an empty-analysis trivial pass.
assert len(body['observations']) >= 1, 'expected at least one observation from the deterministic stub'
assert any('E1' in obs['evidence_ids'] for obs in body['observations']), 'expected an observation citing E1'

# Every citation anywhere in the response must reference a real,
# returned evidence id -- re-verified independently here, not just
# trusted from the service's own internal validation.
cited = set()
for obs in body['observations']:
    cited.update(obs['evidence_ids'])
for hyp in body['hypotheses']:
    cited.update(hyp['supporting_evidence_ids'])
    cited.update(hyp['conflicting_evidence_ids'])
fabricated = cited - evidence_ids
assert not fabricated, f'response cited evidence id(s) not present in its own evidence list: {fabricated}'

print(f\"  summary: {body['summary'][:100]}\")
print(f\"  {len(body['evidence'])} evidence item(s); source outcomes: \" + ', '.join(f\"{o['source']}={o['status']}\" for o in body['source_outcomes']))
print(f\"  {len(body['observations'])} observation(s), all citations verified against {len(evidence_ids)} real evidence id(s)\")
"

section "5. Confirm the investigation did NOT mutate the incident or its complete audit trail"
cp_get "/api/v1/incidents/$INCIDENT_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$INCIDENT_ID (after) returned $HTTP_STATUS"
INCIDENT_AFTER="$HTTP_BODY"
[ "$INCIDENT_AFTER" = "$INCIDENT_BEFORE" ] || fail "incident row changed after a read-only investigation request -- before: $INCIDENT_BEFORE -- after: $INCIDENT_AFTER"

EVENTS_AFTER="$(fetch_all_events_canonical "$INCIDENT_ID")"
[ "$EVENTS_AFTER" = "$EVENTS_BEFORE" ] || fail "complete, fully-paginated audit event list changed after a read-only investigation request -- before: $EVENTS_BEFORE -- after: $EVENTS_AFTER"
echo "  confirmed byte-for-byte unchanged: incident row and complete, fully-paginated audit event list"

echo ""
if [ -n "$PHASE5_FRESHNESS_CHECKPOINT" ]; then
  echo "PHASE 5 INVESTIGATOR ACCEPTANCE VERIFIED (freshness-proven): a real, resolved CheckoutServerErrors incident ($INCIDENT_ID), confirmed created after this run's own freshness checkpoint, was investigated end-to-end through the real control-plane/Prometheus/Loki/Tempo evidence pipeline and a deterministic stub provider, producing a structured, fully evidence-cited report, with the incident row and its complete audit trail confirmed byte-for-byte unchanged afterward."
else
  echo "PHASE 5 INVESTIGATOR ACCEPTANCE VERIFIED (historical/local mode -- freshness NOT proven, see section 1 above): a real, already-persisted, resolved CheckoutServerErrors incident ($INCIDENT_ID) was investigated end-to-end through the real control-plane/Prometheus/Loki/Tempo evidence pipeline and a deterministic stub provider, producing a structured, fully evidence-cited report, with the incident row and its complete audit trail confirmed byte-for-byte unchanged afterward."
fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
