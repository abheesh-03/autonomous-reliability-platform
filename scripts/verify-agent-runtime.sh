#!/usr/bin/env bash
#
# verify-agent-runtime.sh — Phase 7 real-evidence acceptance: durable
# LangGraph agent-run orchestration against the real stack.
#
# Deliberately placed AFTER make verify-rag (Phase 6) in both the
# Makefile and CI ordering: reuses the exact same real, already-
# persisted, resolved CheckoutServerErrors incident those gates already
# produced/verified, and the same PHASE5_FRESHNESS_CHECKPOINT mechanism
# (captured once, before Phase 4) -- no new incident, no new
# freshness-proof mechanism.
#
# Sources scripts/verify-rag.sh for its reusable helpers (which itself
# sources scripts/verify-investigator.sh) -- section/fail/cp_get/
# fetch_all_events_canonical/wait_healthy/investigator_provider_mode/
# on_exit/psql_exec -- rather than duplicating them. Sourcing only
# defines functions and top-level defaults (both scripts guard their
# own `main` at the bottom), so this never re-runs Phase 5/6's own
# acceptance flow or finds a different incident.
#
# Forces investigator-service into INVESTIGATOR_LLM_PROVIDER=stub for
# this run (same capture/force/restore-and-verify machinery as Phase
# 5/6, reused via sourcing) -- no paid LLM API key is required.
#
# This is a durable READ-ONLY orchestration gate (Phase 7 is read-only
# orchestration only -- see docs/architecture/phase-7-durable-agent-runtime.md):
# proves the agent run reaches a real persisted `completed` state, that
# a transient dependency outage mid-flight leaves it safely resumable
# through the PUBLIC API (not just at the graph/checkpoint level),
# that restarting agent-runtime-service mid-flight does not lose it,
# that a completed run can never be made to execute again, and that
# NONE of this ever mutates reliability.incidents /
# reliability.incident_events -- both by row count AND by a real,
# deterministic full-content fingerprint, never just the one selected
# incident's own byte-for-byte comparison.
#
# Phase 7 correction round: create_agent_run (POST /api/v1/agent-runs)
# now SEEDS a durable run only -- it performs no external call and
# does not execute the graph. POST .../resume is what actually
# executes/continues it (see docs/architecture/phase-7-durable-agent-runtime.md
# and api/agent_runs.py's own module docstring for why). This script
# reflects that: it creates, then resumes.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/verify-rag.sh"

AGENT_RUNTIME_URL="${AGENT_RUNTIME_URL:-http://127.0.0.1:8003}"

agent_runtime_post() {
  # agent_runtime_post <path> <json-body>
  curl -s --connect-timeout 2 --max-time 60 -w '\n%{http_code}' -X POST "$AGENT_RUNTIME_URL$1" \
    -H "Content-Type: application/json" -d "$2"
}

agent_runtime_get() {
  # agent_runtime_get <path>
  curl -s --connect-timeout 2 --max-time 15 -w '\n%{http_code}' "$AGENT_RUNTIME_URL$1"
}

# Post-commit fix (GitHub Actions run #33): a single, immediate
# /health/ready check is too strict now that CheckpointStore owns a
# real, reconnecting connection pool -- a pool recovering from even a
# brief prior disruption (this script's own earlier
# `docker compose restart agent-runtime-service` in section 9, or any
# other real transient PostgreSQL hiccup) may legitimately need a
# moment to report ready again, exactly as proven by
# test_checkpoint_pool_recovery.py. Bounded retry (never unbounded --
# a permanently broken database must still fail CI, not hang it):
# up to 20 attempts, 2s apart (~40s), each requiring a REAL 200 with
# status=ready, checkpoint_store.reachable=true, AND the dedicated
# agent_runtime identity -- never merely /health/live, which proves
# nothing about the checkpoint database at all.
wait_agent_runtime_ready() {
  local attempts=20
  local body
  for i in $(seq 1 "$attempts"); do
    body="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' "$AGENT_RUNTIME_URL/health/ready")"
    status="$(echo "$body" | tail -1)"
    json="$(echo "$body" | sed '$d')"
    if [ "$status" = "200" ] && echo "$json" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['status'] == 'ready', body
assert body['checkpoint_store']['reachable'] is True, body
identity = body['checkpoint_store']['identity']
assert identity is not None, 'expected a live identity block in /health/ready'
assert identity['current_user'] == 'agent_runtime', identity
assert identity['current_schema'] == 'agent_runtime', identity
assert identity['search_path'] == 'agent_runtime', identity
" 2>/dev/null; then
      echo "$json"
      return 0
    fi
    echo "  attempt $i/$attempts: /health/ready not yet confirmed ready (http=$status)" >&2
    sleep 2
  done
  return 1
}

# Real, deterministic, full-content fingerprints (Phase 7 correction
# round, finding #8) -- never just a row count. Canonical PostgreSQL
# JSON representation (row_to_json) of every row, deterministically
# ordered by primary key, concatenated and hashed. A mutation to ANY
# row of either table (not just the one selected incident) changes
# this value -- this is what "global fingerprint" actually means,
# where the row-count checks alone could miss a row-for-row swap.
incidents_fingerprint() {
  psql_exec -c "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '|' ORDER BY t.id), '')) FROM reliability.incidents t;"
}

incident_events_fingerprint() {
  psql_exec -c "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '|' ORDER BY t.id), '')) FROM reliability.incident_events t;"
}

main() {
cd "$REPO_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

trap on_exit EXIT

section "0. Confirm control-plane, investigator-service, retrieval-service, and agent-runtime-service are healthy"
wait_healthy control-plane 20 || fail "control-plane is not healthy"
wait_healthy investigator-service 20 || fail "investigator-service is not healthy"
wait_healthy retrieval-service 20 || fail "retrieval-service is not healthy"
wait_healthy agent-runtime-service 20 || fail "agent-runtime-service is not healthy"

section "1. Verify agent-runtime-service readiness AND its own live checkpoint-connection identity (bounded retry)"
ready_body="$(wait_agent_runtime_ready)" || fail "/health/ready never confirmed ready (status=ready, checkpoint_store.reachable=true, agent_runtime identity) within the bounded retry window -- never merely /health/live, which proves nothing about the checkpoint database"
echo "  /health/ready: $ready_body"
echo "  confirmed: the live service's own checkpoint connection is current_user=agent_runtime current_schema=agent_runtime"

section "2. Verify the dedicated agent_runtime role/schema exist and are usable"
role_exists="$(psql_exec -c "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_runtime');")"
[ "$role_exists" = "t" ] || fail "the dedicated 'agent_runtime' PostgreSQL role does not exist -- run 'make db-up' (which provisions it via scripts/init-agent-runtime-db.sh)"
schema_exists="$(psql_exec -c "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'agent_runtime');")"
[ "$schema_exists" = "t" ] || fail "the dedicated 'agent_runtime' PostgreSQL schema does not exist"
checkpoints_table_exists="$(psql_exec -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'agent_runtime' AND table_name = 'checkpoints');")"
[ "$checkpoints_table_exists" = "t" ] || fail "agent_runtime.checkpoints does not exist -- has agent-runtime-service ever started and called checkpointer.setup()?"
echo "  agent_runtime role/schema exist; agent_runtime.checkpoints is present"

section "3. Prove the agent_runtime role CANNOT access reliability.* application tables (real PostgreSQL, fail closed)"
[ -n "${AGENT_RUNTIME_DB_PASSWORD:-}" ] || fail "AGENT_RUNTIME_DB_PASSWORD is not set in .env -- cannot connect as the agent_runtime role to prove its privilege boundary"
agent_runtime_psql() {
  docker compose exec -T -e PGPASSWORD="$AGENT_RUNTIME_DB_PASSWORD" postgres \
    psql -t -A -U agent_runtime -d "$POSTGRES_DB" "$@" 2>&1
}
if own_schema_output="$(agent_runtime_psql -c "SELECT 1 FROM agent_runtime.checkpoints LIMIT 1;")"; then
  echo "  confirmed: agent_runtime CAN query its own agent_runtime.checkpoints (exit 0)"
else
  echo "$own_schema_output"
  fail "the agent_runtime role could not query its OWN agent_runtime.checkpoints table"
fi
if denied_output="$(agent_runtime_psql -c "SELECT * FROM reliability.incidents LIMIT 1;")"; then
  fail "SECURITY BOUNDARY VIOLATION: the agent_runtime role was able to SELECT from reliability.incidents: $denied_output"
fi
echo "$denied_output" | grep -qi "permission denied" || fail "expected a 'permission denied' error denying agent_runtime access to reliability.incidents, got: $denied_output"
echo "  confirmed: agent_runtime role is DENIED (permission denied) on reliability.incidents"
if denied_output2="$(agent_runtime_psql -c "SELECT * FROM reliability.retrieval_chunks LIMIT 1;")"; then
  fail "SECURITY BOUNDARY VIOLATION: the agent_runtime role was able to SELECT from reliability.retrieval_chunks: $denied_output2"
fi
echo "$denied_output2" | grep -qi "permission denied" || fail "expected a 'permission denied' error denying agent_runtime access to reliability.retrieval_chunks, got: $denied_output2"
echo "  confirmed: agent_runtime role is DENIED (permission denied) on reliability.retrieval_chunks"
# Phase 7 correction round (finding #13): the architecture doc claims
# denial of INSERT/UPDATE/DELETE on reliability.incident_events, but
# only UPDATE/DELETE were ever live-verified here -- added for real
# completeness (the real pytest suite's own INSERT test is the
# authoritative, CI-enforced proof; this is the same proof re-run
# live against this exact running stack).
if denied_output3="$(agent_runtime_psql -c "INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, new_status) VALUES ('00000000-0000-0000-0000-000000000000', 'created', 'alertmanager', 'open');")"; then
  fail "SECURITY BOUNDARY VIOLATION: the agent_runtime role was able to INSERT into reliability.incident_events: $denied_output3"
fi
echo "$denied_output3" | grep -qi "permission denied" || fail "expected a 'permission denied' error denying agent_runtime INSERT on reliability.incident_events, got: $denied_output3"
echo "  confirmed: agent_runtime role is DENIED (permission denied) on INSERT INTO reliability.incident_events"

section "4. Snapshot the real current incident, complete audit history, and global content fingerprints (BEFORE any agent run)"
if [ -n "$PHASE5_FRESHNESS_CHECKPOINT" ]; then
  echo "  freshness checkpoint: $PHASE5_FRESHNESS_CHECKPOINT (reusing the same checkpoint Phase 5/6 already validated)"
else
  echo "  WARNING: PHASE5_FRESHNESS_CHECKPOINT is not set -- proceeding in HISTORICAL/LOCAL MODE." >&2
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
  [ -n "$INCIDENT_ID" ] || fail "no resolved CheckoutServerErrors incident found with first_seen_at after $PHASE5_FRESHNESS_CHECKPOINT"
else
  [ -n "$INCIDENT_ID" ] || fail "no existing resolved CheckoutServerErrors incident found at all -- run 'make verify-failure-simulation' first"
fi
echo "  reusing real incident: $INCIDENT_ID"

cp_get "/api/v1/incidents/$INCIDENT_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$INCIDENT_ID returned $HTTP_STATUS"
INCIDENT_BEFORE="$HTTP_BODY"
EVENTS_BEFORE="$(fetch_all_events_canonical "$INCIDENT_ID")"
echo "  before: events_total=$(echo "$EVENTS_BEFORE" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))") (fully paginated)"

INCIDENTS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.incidents;")"
INCIDENT_EVENTS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.incident_events;")"
INCIDENTS_FINGERPRINT_BEFORE="$(incidents_fingerprint)"
INCIDENT_EVENTS_FINGERPRINT_BEFORE="$(incident_events_fingerprint)"
echo "  before: reliability.incidents=$INCIDENTS_COUNT_BEFORE (fingerprint=$INCIDENTS_FINGERPRINT_BEFORE)"
echo "  before: reliability.incident_events=$INCIDENT_EVENTS_COUNT_BEFORE (fingerprint=$INCIDENT_EVENTS_FINGERPRINT_BEFORE)"

section "5. Force investigator-service into the deterministic stub LLM provider for this run"
ORIGINAL_PROVIDER_MODE="$(investigator_provider_mode)"
[ -n "$ORIGINAL_PROVIDER_MODE" ] || fail "could not determine investigator-service's original provider mode via /health/ready"
echo "  original provider mode (to be restored afterward): $ORIGINAL_PROVIDER_MODE"
export INVESTIGATOR_LLM_PROVIDER=stub
NEEDS_PROVIDER_RESTORE=true
docker compose up -d investigator-service >/dev/null
wait_healthy investigator-service 20 || fail "investigator-service is not healthy after forcing stub mode"

section "6. Create a durable agent run (POST /api/v1/agent-runs) -- SEEDS ONLY, no external call yet"
create_response="$(agent_runtime_post "/api/v1/agent-runs" "{\"incident_id\": \"$INCIDENT_ID\"}")"
CREATE_STATUS="$(echo "$create_response" | tail -1)"
CREATE_BODY="$(echo "$create_response" | sed '$d')"
[ "$CREATE_STATUS" = "201" ] || fail "POST /api/v1/agent-runs returned $CREATE_STATUS: $CREATE_BODY"

RUN_ID="$(echo "$CREATE_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['run_id'])")"
echo "  created durable agent run: run_id=$RUN_ID"

echo "$CREATE_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)

assert body['run_id'] == body['thread_id'], 'thread_id must equal run_id (Phase 7 §AGENT RUN IDENTITY)'
assert body['incident_id'] == '$INCIDENT_ID', body['incident_id']
# Phase 7 correction round (finding #2): create no longer executes the
# graph -- the caller receives a durable, resumable run_id BEFORE any
# fallible external graph work begins.
assert body['status'] == 'running', body['status']
assert body['current_node'] == 'start', body['current_node']
assert body['resumable'] is True, 'a freshly seeded run must be resumable'
assert body['completed_nodes'] == [], body['completed_nodes']
assert body['incident_snapshot'] is None
assert body['investigation_report'] is None
print(f\"  status={body['status']} current_node={body['current_node']} resumable={body['resumable']}\")
"
echo "  confirmed: create performed NO control-plane/investigator-service call (seed only)"

section "7. GET the just-created run and confirm it matches exactly (safe, normalized view)"
get_response="$(agent_runtime_get "/api/v1/agent-runs/$RUN_ID")"
GET_STATUS="$(echo "$get_response" | tail -1)"
GET_BODY="$(echo "$get_response" | sed '$d')"
[ "$GET_STATUS" = "200" ] || fail "GET /api/v1/agent-runs/$RUN_ID returned $GET_STATUS: $GET_BODY"
[ "$GET_BODY" = "$CREATE_BODY" ] || fail "GET /api/v1/agent-runs/$RUN_ID did not match the create response byte-for-byte"
echo "  confirmed: GET matches the create response byte-for-byte"

section "8. Public-API resumability through a REAL transient dependency outage (Phase 7 correction round, finding #9)"
echo "  stopping investigator-service to simulate a real transient dependency outage"
docker compose stop investigator-service >/dev/null

transient_resume="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
TRANSIENT_STATUS="$(echo "$transient_resume" | tail -1)"
TRANSIENT_BODY="$(echo "$transient_resume" | sed '$d')"
[ "$TRANSIENT_STATUS" = "503" ] || fail "POST .../resume while investigator-service is down returned $TRANSIENT_STATUS, expected 503: $TRANSIENT_BODY"
echo "$TRANSIENT_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['detail'] == 'investigator-service is temporarily unavailable; this agent run remains resumable', body
"
echo "  confirmed: resume returned a safe 503 (never a raw exception, never a persisted 'failed' state)"

mid_flight="$(agent_runtime_get "/api/v1/agent-runs/$RUN_ID")"
[ "$(echo "$mid_flight" | tail -1)" = "200" ] || fail "GET after the transient failure did not return 200"
echo "$mid_flight" | sed '$d' | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['status'] == 'running', body['status']
assert body['resumable'] is True, 'must remain resumable after a transient dependency failure'
assert body['completed_nodes'] == ['load_incident'], body['completed_nodes']
assert body['incident_snapshot'] is not None, 'load_incident already succeeded and must be durably preserved'
assert body['investigation_report'] is None
"
echo "  confirmed: GET shows the run still running/resumable, load_incident's own result durably preserved"

section "9. Restart agent-runtime-service WHILE this run is still incomplete, and confirm it survives"
docker compose restart agent-runtime-service >/dev/null
wait_healthy agent-runtime-service 20 || fail "agent-runtime-service did not become healthy again after restart"

post_restart_mid_flight="$(agent_runtime_get "/api/v1/agent-runs/$RUN_ID")"
[ "$(echo "$post_restart_mid_flight" | tail -1)" = "200" ] || fail "GET after restarting agent-runtime-service (mid-flight) did not return 200"
[ "$(echo "$post_restart_mid_flight" | sed '$d')" = "$(echo "$mid_flight" | sed '$d')" ] || fail "incomplete run's state after restarting agent-runtime-service did not match its pre-restart state -- persistence was NOT durable across a process restart for an INCOMPLETE run"
echo "  confirmed: the still-incomplete run's exact state survived a real agent-runtime-service process restart"

section "10. Restore investigator-service and resume the SAME run_id to completion"
export INVESTIGATOR_LLM_PROVIDER=stub
docker compose up -d investigator-service >/dev/null
wait_healthy investigator-service 20 || fail "investigator-service is not healthy after restoring it"

resume_response="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
RESUME_STATUS="$(echo "$resume_response" | tail -1)"
RESUME_BODY="$(echo "$resume_response" | sed '$d')"
[ "$RESUME_STATUS" = "200" ] || fail "POST /api/v1/agent-runs/$RUN_ID/resume (after recovery) returned $RESUME_STATUS: $RESUME_BODY"

echo "$RESUME_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['status'] == 'completed', f\"expected completed, got status={body['status']!r} error_code={body.get('error_code')!r}\"
assert body['resumable'] is False
assert body['incident_snapshot'] is not None
assert body['investigation_report'] is not None
# The critical no-re-execution proof: load_incident's checkpoint was
# never re-committed by this resume -- it appears in completed_nodes
# EXACTLY once, even though this is the run's second resume call.
assert body['completed_nodes'].count('load_incident') == 1, body['completed_nodes']
assert body['completed_nodes'] == ['load_incident', 'run_investigation', 'evaluate_investigation', 'finalize'], body['completed_nodes']
assert body['result_quality'] in ('well_supported', 'inconclusive', 'partial'), body['result_quality']

raw = json.dumps(body)
assert 'api_key' not in raw.lower(), 'a credential-shaped field leaked into the agent run response'
assert 'authorization' not in raw.lower(), 'a credential-shaped field leaked into the agent run response'

rc = body['investigation_report']['retrieval_context']
assert rc['outcome'] in ('ok', 'no_data'), f\"expected real Phase 6 RAG retrieval to be reachable, got outcome={rc['outcome']!r}\"
for item in rc['knowledge'] + rc['historical_incidents']:
    assert item['context_id'] and item['context_id'][0] in ('K', 'H')
    assert item['source_key']
print(f\"  status={body['status']} result_quality={body['result_quality']} completed_nodes={body['completed_nodes']}\")
print(f\"  real RAG provenance: {len(rc['knowledge'])} knowledge, {len(rc['historical_incidents'])} historical (outcome={rc['outcome']})\")
"
section "11. Inspect safe execution history: multiple durable checkpoints, no raw blobs"
history_response="$(agent_runtime_get "/api/v1/agent-runs/$RUN_ID/history")"
HISTORY_STATUS="$(echo "$history_response" | tail -1)"
HISTORY_BODY="$(echo "$history_response" | sed '$d')"
[ "$HISTORY_STATUS" = "200" ] || fail "GET /api/v1/agent-runs/$RUN_ID/history returned $HISTORY_STATUS: $HISTORY_BODY"
echo "$HISTORY_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['run_id'] == '$RUN_ID'
entries = body['entries']
assert len(entries) >= 4, f'expected multiple real durable checkpoints (>= 4), got {len(entries)}'
nodes = [e['node'] for e in entries]
assert 'finalize' in nodes, nodes
steps = [e['step'] for e in entries]
assert steps == sorted(steps), 'history must be chronological'
raw = json.dumps(body)
assert 'api_key' not in raw.lower()
for e in entries:
    assert isinstance(e['checkpoint_id'], str) and e['checkpoint_id']
print(f'  {len(entries)} real durable checkpoint(s), nodes visited: {nodes}')
"

section "12. A completed run cannot be resumed (409), and repeating that is equally safe"
resume_after_complete="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
[ "$(echo "$resume_after_complete" | tail -1)" = "409" ] || fail "POST .../resume on a completed run returned $(echo "$resume_after_complete" | tail -1), expected 409"
resume_after_complete2="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
[ "$(echo "$resume_after_complete2" | tail -1)" = "409" ] || fail "repeating POST .../resume on a completed run returned $(echo "$resume_after_complete2" | tail -1), expected 409 again"
echo "  confirmed: resuming a completed run is rejected (409), repeatably and safely -- no remediation, no re-execution"

section "13. Unknown run_id is 404 for GET, history, and resume alike"
unknown_id="00000000-0000-0000-0000-000000000000"
unknown_get="$(agent_runtime_get "/api/v1/agent-runs/$unknown_id")"
[ "$(echo "$unknown_get" | tail -1)" = "404" ] || fail "GET of an unknown run_id did not return 404"
unknown_history="$(agent_runtime_get "/api/v1/agent-runs/$unknown_id/history")"
[ "$(echo "$unknown_history" | tail -1)" = "404" ] || fail "history of an unknown run_id did not return 404"
unknown_resume="$(agent_runtime_post "/api/v1/agent-runs/$unknown_id/resume" "{}")"
[ "$(echo "$unknown_resume" | tail -1)" = "404" ] || fail "resume of an unknown run_id did not return 404"
echo "  confirmed: unknown run_id is 404 across GET/history/resume"

section "14. Compare the current incident and FULL paginated audit history before/after; prove byte-for-byte unchanged"
cp_get "/api/v1/incidents/$INCIDENT_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$INCIDENT_ID (after) returned $HTTP_STATUS"
INCIDENT_AFTER="$HTTP_BODY"
[ "$INCIDENT_AFTER" = "$INCIDENT_BEFORE" ] || fail "incident row changed after the full agent-run flow -- before: $INCIDENT_BEFORE -- after: $INCIDENT_AFTER"

EVENTS_AFTER="$(fetch_all_events_canonical "$INCIDENT_ID")"
[ "$EVENTS_AFTER" = "$EVENTS_BEFORE" ] || fail "complete, fully-paginated audit event list changed after the full agent-run flow"
echo "  confirmed byte-for-byte unchanged: incident row and complete, fully-paginated audit event list"

section "15. Verify global incident/audit CONTENT FINGERPRINTS are unchanged (Phase 7 correction round, finding #8)"
INCIDENTS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.incidents;")"
INCIDENT_EVENTS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.incident_events;")"
INCIDENTS_FINGERPRINT_AFTER="$(incidents_fingerprint)"
INCIDENT_EVENTS_FINGERPRINT_AFTER="$(incident_events_fingerprint)"
echo "  after:  reliability.incidents=$INCIDENTS_COUNT_AFTER (fingerprint=$INCIDENTS_FINGERPRINT_AFTER)"
echo "  after:  reliability.incident_events=$INCIDENT_EVENTS_COUNT_AFTER (fingerprint=$INCIDENT_EVENTS_FINGERPRINT_AFTER)"

[ "$INCIDENTS_COUNT_AFTER" = "$INCIDENTS_COUNT_BEFORE" ] || fail "reliability.incidents row count changed from this run's own activity (before=$INCIDENTS_COUNT_BEFORE after=$INCIDENTS_COUNT_AFTER)"
[ "$INCIDENT_EVENTS_COUNT_AFTER" = "$INCIDENT_EVENTS_COUNT_BEFORE" ] || fail "reliability.incident_events row count changed from this run's own activity (before=$INCIDENT_EVENTS_COUNT_BEFORE after=$INCIDENT_EVENTS_COUNT_AFTER)"

# The content fingerprint is the REAL, stronger guarantee (finding #8):
# a mutation to some OTHER row -- never touching the one selected
# incident, and never changing either table's row count -- would still
# change this value. Deterministic ordering (ORDER BY id) + canonical
# PostgreSQL JSON representation (row_to_json), never a naive text dump.
[ "$INCIDENTS_FINGERPRINT_AFTER" = "$INCIDENTS_FINGERPRINT_BEFORE" ] || fail "reliability.incidents GLOBAL CONTENT FINGERPRINT changed (before=$INCIDENTS_FINGERPRINT_BEFORE after=$INCIDENTS_FINGERPRINT_AFTER) -- some row changed even though the row count did not"
[ "$INCIDENT_EVENTS_FINGERPRINT_AFTER" = "$INCIDENT_EVENTS_FINGERPRINT_BEFORE" ] || fail "reliability.incident_events GLOBAL CONTENT FINGERPRINT changed (before=$INCIDENT_EVENTS_FINGERPRINT_BEFORE after=$INCIDENT_EVENTS_FINGERPRINT_AFTER) -- some row changed even though the row count did not"
echo "  confirmed: reliability.incidents and reliability.incident_events are UNCHANGED by both row count AND full-content fingerprint -- no remediation occurred, anywhere"

echo ""
if [ -n "$PHASE5_FRESHNESS_CHECKPOINT" ]; then
  echo "PHASE 7 AGENT RUNTIME ACCEPTANCE VERIFIED (freshness-proven): a real, durable LangGraph agent run (run_id=$RUN_ID) was created against a real, freshness-proven CheckoutServerErrors incident (seed only, no execution yet, per the create/resume split), survived a REAL transient investigator-service outage through the PUBLIC API (safe 503, remained resumable, never a persisted failure), survived a real agent-runtime-service process restart WHILE STILL INCOMPLETE, then resumed to completion through the real control-plane and investigator-service (with real Phase 6 RAG provenance) without re-executing its already-durable load_incident step, reached a real persisted 'completed' state with multiple durable checkpoints, permanently refuses to re-execute (409, repeatably), and left the incident row, its complete audit trail, and BOTH tables' global row counts AND full-content fingerprints byte-for-byte/exactly unchanged throughout -- proving a durable, least-privileged, read-only orchestration layer with no remediation capability, whose live checkpoint connection is independently confirmed to be the dedicated agent_runtime role/schema."
else
  echo "PHASE 7 AGENT RUNTIME ACCEPTANCE VERIFIED (historical/local mode -- freshness NOT proven, see section 4 above)."
fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
