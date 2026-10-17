#!/usr/bin/env bash
#
# verify-remediation.sh — Phase 8 real-evidence acceptance: human-
# approved remediation, real LangGraph interrupt/resume, tool-gateway
# execution, and real recovery, against the real running stack.
#
# Deliberately creates its OWN fresh real incident (never reuses an
# already-resolved incident the way verify-agent-runtime.sh reuses
# Phase 4's -- Phase 8 is a MUTATING demo and must prove its own,
# freshness-provable chain end to end, from a real checkout failure
# through a real human decision to a real recovered checkout).
#
# Sources scripts/verify-agent-runtime.sh (which itself sources
# verify-rag.sh -> verify-investigator.sh) for section/fail/cp_get/
# wait_healthy/psql_exec/fetch_all_events_canonical/agent_runtime_get/
# agent_runtime_post/wait_agent_runtime_ready/investigator_provider_mode,
# and scripts/simulate-failure.sh for do_checkout/assert_checkout_failed_with
# (the SAME real checkout-service contract a payment-service failure
# produces, whether induced by stopping the container (Phase 4) or by
# this phase's own controlled authorization fault -- never duplicated
# here). Sourcing only defines functions/defaults (every sourced file
# guards its own `main` at the bottom), so this never re-runs an
# earlier phase's own acceptance flow.
#
# Uses the deterministic stub LLM provider (INVESTIGATOR_LLM_PROVIDER=stub,
# same capture/force/restore machinery already established) -- no paid
# API key required.
#
# EXIT cleanup (this script's OWN addition, never present in the
# sourced chain): ALWAYS attempts to clear the controlled payment
# fault and verify payment-service healthy, even when this script
# fails midway -- a failed acceptance run must never leave
# payment-service deliberately broken for whatever runs next.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/verify-agent-runtime.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/simulate-failure.sh"

PAYMENT_URL="${PAYMENT_URL:-http://127.0.0.1:8081}"
TOOL_GATEWAY_URL="${TOOL_GATEWAY_URL:-http://127.0.0.1:8004}"
readonly REMEDIATION_ALERT_NAME="CheckoutServerErrors"

# --- Small, Phase-8-specific HTTP helpers, matching cp_get's own
# shape (sets HTTP_STATUS/HTTP_BODY). -----------------------------------

tg_get() {
  local path="$1" response
  response="$(curl -s --connect-timeout 2 --max-time 15 -w '\n%{http_code}' -H "Authorization: Bearer ${TOOL_GATEWAY_EXECUTION_TOKEN:-}" "$TOOL_GATEWAY_URL$path")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

tg_post() {
  local path="$1" body="$2" response
  response="$(curl -s --connect-timeout 2 --max-time 30 -w '\n%{http_code}' -X POST "$TOOL_GATEWAY_URL$path" \
    -H "Authorization: Bearer ${TOOL_GATEWAY_EXECUTION_TOKEN:-}" -H "Content-Type: application/json" -d "$body")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

payment_fault_get() {
  local response
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -H "Authorization: Bearer ${PAYMENT_REMEDIATION_TOKEN:-}" "$PAYMENT_URL/internal/v1/faults/authorization")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

payment_fault_enable() {
  local response
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X POST -H "Authorization: Bearer ${PAYMENT_FAULT_INJECTION_TOKEN:-}" "$PAYMENT_URL/internal/v1/faults/authorization/enable")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

payment_fault_clear() {
  local response
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X POST -H "Authorization: Bearer ${PAYMENT_REMEDIATION_TOKEN:-}" "$PAYMENT_URL/internal/v1/faults/authorization/clear")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

cp_approver_post() {
  # cp_approver_post <path> <json-body>
  local response
  response="$(curl -s --connect-timeout 2 --max-time 15 -w '\n%{http_code}' -X POST "$CONTROL_PLANE_URL$1" \
    -H "Authorization: Bearer ${CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN:-}" -H "Content-Type: application/json" -d "$2")"
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

# Phase 8's own EXIT cleanup addition: always attempts to clear the
# controlled fault and confirm payment-service healthy, regardless of
# where this script fails. Separate from (and always runs BEFORE) the
# inherited investigator-provider-restore logic -- NOT by calling the
# inherited `on_exit` function directly (which re-captures `$?` at ITS
# OWN entry, which would be THIS cleanup's own exit code by the time
# it ran, silently corrupting the real original exit status); instead
# this replicates that same restoration logic inline, using the exact
# same shared state (ORIGINAL_PROVIDER_MODE/NEEDS_PROVIDER_RESTORE)
# the sourced chain already maintains.
remediation_on_exit() {
  local exit_status=$?

  echo "" >&2
  echo "-- cleanup: clearing the controlled payment authorization fault (if any) --" >&2
  if [ -n "${PAYMENT_REMEDIATION_TOKEN:-}" ]; then
    payment_fault_clear || true
    # Correction round (finding #8): this whole script runs under
    # `set -euo pipefail`. `payment_fault_get`'s own first statement is
    # `response="$(curl ...)"` -- an assignment whose ENTIRE exit
    # status is curl's own exit status; under errexit, a genuinely
    # unreachable payment-service (connection refused, timeout) would
    # otherwise abort this trap immediately, skipping every remaining
    # restoration step below (PAYMENT_FAULT_INJECTION_ENABLED restore,
    # investigator-service provider restore) and silently losing the
    # real original exit status. Calling it as an `if` CONDITION is the
    # standard, documented bash exemption: errexit is suspended for the
    # entire call tree beneath a command used as an if/while/until
    # test (or on the left of &&/||), so a failing curl inside it can
    # never abort this trap -- it only makes the `if` take its `else`
    # branch, exactly like every other guarded step in this function.
    if payment_fault_get && [ "$HTTP_STATUS" = "200" ] && echo "$HTTP_BODY" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['active'] is False else 1)" 2>/dev/null; then
      echo "  confirmed: payment authorization fault is inactive" >&2
    else
      echo "FAIL: cleanup could not confirm the payment authorization fault is inactive (status=${HTTP_STATUS:-unknown} body=${HTTP_BODY:-<unreachable>}) -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    fi
    if wait_healthy payment-service 20; then
      echo "  confirmed: payment-service is healthy" >&2
    else
      echo "FAIL: cleanup could not confirm payment-service healthy -- manual investigation required" >&2
      [ "$exit_status" -eq 0 ] && exit_status=1
    fi
  else
    echo "  (no PAYMENT_REMEDIATION_TOKEN configured -- nothing to clear)" >&2
  fi

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

for tok in CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN \
           CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN TOOL_GATEWAY_EXECUTION_TOKEN \
           PAYMENT_FAULT_INJECTION_TOKEN PAYMENT_REMEDIATION_TOKEN; do
  [ -n "${!tok:-}" ] || fail "$tok is not set in .env -- run 'make remediation-secret-init' (or 'make db-up') first"
done

# Replaces the inherited `trap on_exit EXIT` (sourcing verify-agent-runtime.sh
# already registered one) -- only the LAST `trap ... EXIT` registration
# takes effect, so this intentionally supersedes it; remediation_on_exit
# performs that same investigator-provider restoration itself (see its
# own docstring) in addition to this phase's own payment-fault cleanup.
trap remediation_on_exit EXIT

section "0. Confirm every involved service is healthy"
for svc in control-plane investigator-service agent-runtime-service tool-gateway payment-service checkout-service; do
  wait_healthy "$svc" 20 || fail "$svc is not healthy"
done
echo "  all six involved services healthy"

section "0b. Force payment-service's PAYMENT_FAULT_INJECTION_ENABLED=true for this run only (Compose/CI explicitly opts in; never on by default)"
ORIGINAL_FAULT_INJECTION_ENABLED="${PAYMENT_FAULT_INJECTION_ENABLED:-false}"
export PAYMENT_FAULT_INJECTION_ENABLED=true
NEEDS_FAULT_ENABLED_RESTORE=true
docker compose up -d payment-service >/dev/null
wait_healthy payment-service 20 || fail "payment-service is not healthy after enabling fault injection"

section "1. Confirm the controlled payment authorization fault is initially OFF"
payment_fault_get
[ "$HTTP_STATUS" = "200" ] || fail "GET /internal/v1/faults/authorization returned $HTTP_STATUS: $HTTP_BODY"
echo "$HTTP_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['active'] is False, b"
echo "  confirmed: payment authorization fault is inactive"

section "2. Confirm $REMEDIATION_ALERT_NAME is initially inactive (never reuse a pending/firing/decaying alert from an earlier run)"
python3 "$SCRIPT_DIR/verify-alerting.py" state \
  --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" \
  --alert "$REMEDIATION_ALERT_NAME" --expect-state inactive \
  || fail "$REMEDIATION_ALERT_NAME must be inactive before this run induces anything -- a pre-existing pending/firing/decaying alert would make this run's own evidence ambiguous"

section "3. Capture this run's freshness checkpoint and BEFORE row counts, then enable the controlled payment authorization fault"
SINCE="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
echo "  freshness floor captured: $SINCE"
INCIDENTS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.incidents;")"
INCIDENT_EVENTS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.incident_events;")"
REMEDIATION_PROPOSALS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_proposals;")"
REMEDIATION_EVENTS_COUNT_BEFORE="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_events;")"
echo "  before: incidents=$INCIDENTS_COUNT_BEFORE incident_events=$INCIDENT_EVENTS_COUNT_BEFORE remediation_proposals=$REMEDIATION_PROPOSALS_COUNT_BEFORE remediation_events=$REMEDIATION_EVENTS_COUNT_BEFORE"

# Bounded retry: payment-service was just recreated in section 0b --
# its OWN healthcheck reporting "healthy" does not guarantee
# checkout-service's own connection to it (a brand-new container has a
# brand-new network identity) has already settled. A genuinely broken
# environment still fails after this bounded window; a brief, real
# post-recreate settling delay does not.
baseline_ok=false
for i in $(seq 1 5); do
  do_checkout
  if [ "$CHECKOUT_STATUS" = "200" ]; then
    baseline_ok=true
    break
  fi
  echo "  attempt $i/5: baseline checkout not yet successful (status=$CHECKOUT_STATUS) -- settling after payment-service's own recreate"
  sleep 3
done
[ "$baseline_ok" = true ] || fail "baseline checkout failed BEFORE the fault was enabled (status=$CHECKOUT_STATUS body=$CHECKOUT_BODY)"
echo "$CHECKOUT_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='COMPLETED', b"
echo "  baseline checkout succeeded -- normal behavior confirmed before fault injection"

payment_fault_enable
[ "$HTTP_STATUS" = "200" ] || fail "POST /internal/v1/faults/authorization/enable returned $HTTP_STATUS: $HTTP_BODY"
echo "$HTTP_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['active'] is True, b"
echo "  confirmed: payment authorization fault is now active (using ONLY PAYMENT_FAULT_INJECTION_TOKEN)"

section "4/5/6. Issue real checkout requests, sustain real failing traffic until $REMEDIATION_ALERT_NAME genuinely fires"
do_checkout
assert_checkout_failed_with payment-service
echo "  confirmed: a real checkout request now genuinely fails through payment-service (502, downstream_failure)"

firing_ok=false
for i in $(seq 1 40); do
  do_checkout
  assert_checkout_failed_with payment-service
  echo "  attempt $i/40: checkout correctly failed (502, service=payment-service) -- checking $REMEDIATION_ALERT_NAME"
  if python3 "$SCRIPT_DIR/verify-alerting.py" firing \
       --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$REMEDIATION_ALERT_NAME"
  then
    firing_ok=true
    break
  fi
  sleep 5
done
[ "$firing_ok" = true ] || fail "$REMEDIATION_ALERT_NAME never reached firing despite sustained real 5xx traffic from the controlled payment fault"

section "7. Confirm the real Alertmanager webhook created a fresh incident after this run's freshness checkpoint"
IDS_FILE="$(mktemp)"
ingestion_ok=false
for i in $(seq 1 20); do
  if python3 "$SCRIPT_DIR/verify-ingestion.py" incident-from-alert --alert "$REMEDIATION_ALERT_NAME" \
       --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" \
       --control-plane-url "$CONTROL_PLANE_URL" --since "$SINCE" --ids-out "$IDS_FILE"
  then
    ingestion_ok=true
    break
  fi
  echo "  attempt $i/20: incident not yet confirmed via the real webhook path"
  sleep 3
done
[ "$ingestion_ok" = true ] || fail "the real Alertmanager webhook never resulted in a confirmed, correctly-mapped incident for $REMEDIATION_ALERT_NAME"
INCIDENT_ID="$(cut -f1 "$IDS_FILE" | head -1)"
[ -n "$INCIDENT_ID" ] || fail "could not read the confirmed incident id from $IDS_FILE"
REMEDIATION_FINGERPRINT="$(cut -f2 "$IDS_FILE" | head -1)"
[ -n "$REMEDIATION_FINGERPRINT" ] || fail "could not read the confirmed incident's real Alertmanager fingerprint from $IDS_FILE"
echo "  confirmed: fresh incident created by this run's own real alert: $INCIDENT_ID"

section "8. Human/operator transitions the fresh incident: open -> investigating"
lifecycle_response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/$INCIDENT_ID/status" \
  -H "Authorization: Bearer $CONTROL_PLANE_LIFECYCLE_TOKEN" -H "Content-Type: application/json" \
  -d '{"expected_status":"open","target_status":"investigating"}')"
[ "$(echo "$lifecycle_response" | tail -1)" = "200" ] || fail "PATCH .../status (open->investigating) returned $(echo "$lifecycle_response" | tail -1): $(echo "$lifecycle_response" | sed '$d')"
echo "  confirmed: incident $INCIDENT_ID is now 'investigating'"

section "9. Force investigator-service into the deterministic stub LLM provider for this run"
ORIGINAL_PROVIDER_MODE="$(investigator_provider_mode)"
[ -n "$ORIGINAL_PROVIDER_MODE" ] || fail "could not determine investigator-service's original provider mode"
export INVESTIGATOR_LLM_PROVIDER=stub
NEEDS_PROVIDER_RESTORE=true
docker compose up -d investigator-service >/dev/null
wait_healthy investigator-service 20 || fail "investigator-service is not healthy after forcing stub mode"

section "10. Start a new durable agent run for this incident, and resume it until it reaches the REAL approval interrupt"
create_response="$(agent_runtime_post "/api/v1/agent-runs" "{\"incident_id\": \"$INCIDENT_ID\"}")"
[ "$(echo "$create_response" | tail -1)" = "201" ] || fail "POST /api/v1/agent-runs returned $(echo "$create_response" | tail -1)"
RUN_ID="$(echo "$create_response" | sed '$d' | python3 -c "import json,sys; print(json.load(sys.stdin)['run_id'])")"
echo "  created durable agent run: run_id=$RUN_ID"

resume1="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
[ "$(echo "$resume1" | tail -1)" = "200" ] || fail "first resume returned $(echo "$resume1" | tail -1): $(echo "$resume1" | sed '$d')"
RESUME1_BODY="$(echo "$resume1" | sed '$d')"
echo "$RESUME1_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
assert b['status'] == 'waiting_for_approval', b['status']
assert b['remediation_status'] == 'pending_approval', b['remediation_status']
assert b['remediation_action_type'] == 'clear_payment_authorization_fault', b['remediation_action_type']
assert b['remediation_target'] == 'payment-service', b['remediation_target']
assert b['remediation_proposal_id'], 'expected a real remediation_proposal_id'
"
PROPOSAL_ID="$(echo "$RESUME1_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['remediation_proposal_id'])")"
echo "  confirmed: run is waiting_for_approval on a REAL proposal: $PROPOSAL_ID"

section "11. Prove the proposal exists in PostgreSQL via control-plane, with the correct action/target and audit event"
cp_get "/api/v1/remediation-proposals/$PROPOSAL_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/remediation-proposals/$PROPOSAL_ID returned $HTTP_STATUS"
echo "$HTTP_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
assert b['status'] == 'pending_approval', b['status']
assert b['action_type'] == 'clear_payment_authorization_fault', b['action_type']
assert b['target'] == 'payment-service', b['target']
assert b['incident_id'] == '$INCIDENT_ID', b['incident_id']
assert b['agent_run_id'] == '$RUN_ID', b['agent_run_id']
"
cp_get "/api/v1/remediation-proposals/$PROPOSAL_ID/events"
[ "$HTTP_STATUS" = "200" ] || fail "GET .../events returned $HTTP_STATUS"
echo "$HTTP_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
types = [e['event_type'] for e in b['items']]
assert types == ['proposed'], types
assert b['items'][0]['actor_type'] == 'agent', b['items'][0]
"
echo "  confirmed: real pending_approval proposal + 'proposed' audit event, visible from the same AgentRun safe view"

section "12. Attempt tool-gateway execution BEFORE approval -- MUST be rejected"
tg_post "/api/v1/remediation-actions/execute" "{\"proposal_id\":\"$PROPOSAL_ID\"}"
[ "$HTTP_STATUS" = "409" ] || fail "tool-gateway execute before approval returned $HTTP_STATUS, expected 409: $HTTP_BODY"
echo "  confirmed: tool-gateway refuses to execute an unapproved proposal (409): $HTTP_BODY"

section "13/14. Restart agent-runtime-service while waiting for approval; fetch the SAME run_id again"
docker compose restart agent-runtime-service >/dev/null
wait_healthy agent-runtime-service 20 || fail "agent-runtime-service did not become healthy again after restart"
post_restart="$(agent_runtime_get "/api/v1/agent-runs/$RUN_ID")"
[ "$(echo "$post_restart" | tail -1)" = "200" ] || fail "GET after restart did not return 200"
echo "$post_restart" | sed '$d' | python3 -c "
import json, sys
b = json.load(sys.stdin)
assert b['status'] == 'waiting_for_approval', b['status']
assert b['remediation_proposal_id'] == '$PROPOSAL_ID', b['remediation_proposal_id']
"
echo "  confirmed: SAME run_id still waits for the SAME proposal after a real agent-runtime-service restart"

section "15. Attempt normal agent resume BEFORE approval -- MUST return approval_pending / 409"
resume_before_approval="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
[ "$(echo "$resume_before_approval" | tail -1)" = "409" ] || fail "resume before approval returned $(echo "$resume_before_approval" | tail -1), expected 409"
echo "$resume_before_approval" | sed '$d' | python3 -c "import json,sys; b=json.load(sys.stdin); assert 'approval_pending' in b['detail'], b"
echo "  confirmed: resume before approval is refused (409 approval_pending)"

section "16. Simulate HUMAN APPROVAL via the control-plane approver endpoint"
cp_approver_post "/api/v1/remediation-proposals/$PROPOSAL_ID/decision" \
  '{"expected_status":"pending_approval","decision":"approve","comment":"verify-remediation.sh acceptance run"}'
[ "$HTTP_STATUS" = "200" ] || fail "decision (approve) returned $HTTP_STATUS: $HTTP_BODY"
echo "$HTTP_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='approved', b"

section "17. Independently prove: proposal approved, incident remediating, both audit events"
cp_get "/api/v1/incidents/$INCIDENT_ID"
[ "$HTTP_STATUS" = "200" ] || fail "GET incident returned $HTTP_STATUS"
echo "$HTTP_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='remediating', b['status']"
cp_get "/api/v1/remediation-proposals/$PROPOSAL_ID/events"
echo "$HTTP_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
types = [e['event_type'] for e in b['items']]
assert types == ['proposed', 'approved'], types
"
EVENTS_AFTER_APPROVAL="$(fetch_all_events_canonical "$INCIDENT_ID")"
echo "$EVENTS_AFTER_APPROVAL" | python3 -c "
import json, sys
events = json.load(sys.stdin)
transitions = [e for e in events if e['event_type']=='status_transition' and e['new_status']=='remediating']
assert len(transitions) == 1, transitions
assert transitions[0]['previous_status'] == 'investigating', transitions[0]
"
echo "  confirmed: proposal=approved, incident=remediating, both audit trails correctly recorded atomically"

section "18/19/20. Resume the SAME agent run -- tool-gateway executes, clears the fault, verifies, finalizes"
resume2="$(agent_runtime_post "/api/v1/agent-runs/$RUN_ID/resume" "{}")"
[ "$(echo "$resume2" | tail -1)" = "200" ] || fail "resume after approval returned $(echo "$resume2" | tail -1): $(echo "$resume2" | sed '$d')"
RESUME2_BODY="$(echo "$resume2" | sed '$d')"
echo "$RESUME2_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
assert b['status'] == 'completed', b
assert b['remediation_status'] == 'succeeded', b['remediation_status']
assert b['execution_result']['status'] == 'succeeded', b['execution_result']
# Phase 8 correction round (finding #2): verify_recovery independently
# re-proves all THREE facts itself (durable proposal status, the
# fault's own fresh precondition read, and payment-service's own fresh
# health read) -- never collapsed into a single boolean.
assert b['recovery_verification'] == {
    'proposal_succeeded': True,
    'fault_inactive': True,
    'target_healthy': True,
}, b['recovery_verification']
assert b['resumable'] is False
assert b['completed_nodes'] == ['load_incident','run_investigation','evaluate_investigation','propose_remediation','await_human_approval','execute_remediation','verify_recovery','finalize'], b['completed_nodes']
"
echo "  confirmed: SAME run completed, remediation_status=succeeded, real recovery independently verified"

section "21. Prove the action was not duplicated and the real payment fault is OFF"
payment_fault_get
[ "$HTTP_STATUS" = "200" ] || fail "GET fault status returned $HTTP_STATUS"
echo "$HTTP_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['active'] is False, b"
cp_get "/api/v1/remediation-proposals/$PROPOSAL_ID/events"
echo "$HTTP_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
types = [e['event_type'] for e in b['items']]
assert types == ['proposed', 'approved', 'execution_started', 'execution_succeeded'], types
assert len(types) == len(set(types)), 'duplicate remediation event types -- action or bookkeeping was duplicated'
"
echo "  confirmed: real payment fault is OFF; exactly one execution_started + one execution_succeeded event (no duplication)"

section "22. Issue a REAL fresh checkout -- MUST return 200 / COMPLETED"
do_checkout
[ "$CHECKOUT_STATUS" = "200" ] || fail "post-recovery checkout returned $CHECKOUT_STATUS (body=$CHECKOUT_BODY)"
echo "$CHECKOUT_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['status']=='COMPLETED', b"
echo "  confirmed: a real, fresh checkout now genuinely succeeds end to end"

section "23/24. Wait for $REMEDIATION_ALERT_NAME to naturally become inactive, then confirm the real resolved webhook"
echo "-- $REMEDIATION_ALERT_NAME's expression is a 5-minute rate() over real checkout traffic, not an"
echo "   instantaneous gauge: it will not read exactly zero until roughly 5 minutes have"
echo "   passed since the last real failing request above. This wait is expected to take"
echo "   several minutes -- same documented behavior as scripts/simulate-failure.sh's own"
echo "   payment-outage recovery wait for this exact alert. The threshold itself is never"
echo "   altered to make this faster. --"
recovered_ok=false
for i in $(seq 1 90); do
  if python3 "$SCRIPT_DIR/verify-alerting.py" recovered \
       --prometheus-url "$PROMETHEUS_URL" --alertmanager-url "$ALERTMANAGER_URL" --alert "$REMEDIATION_ALERT_NAME"
  then
    recovered_ok=true
    break
  fi
  echo "  attempt $i/90: $REMEDIATION_ALERT_NAME not yet recovered"
  sleep 5
done
[ "$recovered_ok" = true ] || fail "$REMEDIATION_ALERT_NAME never naturally recovered after the real remediation"

# Deliberately NOT scripts/verify-ingestion.py's own `confirm-resolved`
# subcommand: its internal verify_audit_trail() asserts NO 'operator'-
# attributed event exists anywhere in the incident's history -- a
# correct invariant for Phase 3D/3E's own pure-automatic Collector-
# outage acceptance (where no human ever touches the incident at all),
# but WRONG for Phase 8's own incident, which legitimately has real
# operator-attributed events (the human lifecycle transition in
# section 8, and the human approval's own incident transition in
# section 17). This inline check instead proves exactly what Phase 8
# itself requires: a genuine 'created' event correctly attributed to
# the real Alertmanager fingerprint, and the FINAL resolving
# status_transition genuinely attributed to 'alertmanager' (never
# fabricated/fake-resolved by this script itself) -- without assuming
# every other event in between is also alertmanager-only.
resolved_ok=false
for i in $(seq 1 20); do
  cp_get "/api/v1/incidents/$INCIDENT_ID"
  if [ "$HTTP_STATUS" = "200" ] && echo "$HTTP_BODY" | python3 -c "
import json, sys
b = json.load(sys.stdin)
sys.exit(0 if b['status'] == 'resolved' and b['resolved_at'] else 1)
" 2>/dev/null; then
    resolved_ok=true
    break
  fi
  echo "  attempt $i/20: incident not yet confirmed resolved via the real webhook path"
  sleep 3
done
[ "$resolved_ok" = true ] || fail "the SAME incident never genuinely transitioned remediating -> resolved via Alertmanager's own real resolved webhook"

FINAL_EVENTS_FOR_RESOLUTION_CHECK="$(fetch_all_events_canonical "$INCIDENT_ID")"
echo "$FINAL_EVENTS_FOR_RESOLUTION_CHECK" | python3 -c "
import json, sys

events = json.load(sys.stdin)
created = [e for e in events if e['event_type'] == 'created']
assert len(created) == 1, f'expected exactly 1 created event, found {len(created)}'
assert created[0]['actor_type'] == 'alertmanager', created[0]
assert created[0]['metadata'].get('source_fingerprint') == '$REMEDIATION_FINGERPRINT', created[0]

resolutions = [e for e in events if e['event_type'] == 'status_transition' and e['new_status'] == 'resolved']
assert len(resolutions) == 1, f'expected exactly 1 resolving status_transition event, found {len(resolutions)}'
assert resolutions[0]['actor_type'] == 'alertmanager', (
    f\"resolving event has actor_type={resolutions[0]['actor_type']!r}, expected 'alertmanager' -- \"
    'a human/operator action must never be fabricated for this real, automated resolution'
)
"
echo "  confirmed: the SAME incident naturally transitioned remediating -> resolved via the real Alertmanager webhook (never faked by this script); 'created' and the final resolving event are both genuinely alertmanager-attributed"

section "25. Prove the complete audit trail"
FINAL_EVENTS="$(fetch_all_events_canonical "$INCIDENT_ID")"
echo "$FINAL_EVENTS" | python3 -c "
import json, sys
events = json.load(sys.stdin)
new_statuses = [e['new_status'] for e in events if e['event_type'] in ('created', 'status_transition')]
assert new_statuses == ['open', 'investigating', 'remediating', 'resolved'], new_statuses
"
cp_get "/api/v1/remediation-proposals/$PROPOSAL_ID/events"
echo "$HTTP_BODY" | python3 -c "
import json, sys
types = [e['event_type'] for e in json.load(sys.stdin)['items']]
assert types == ['proposed', 'approved', 'execution_started', 'execution_succeeded'], types
"
echo "  confirmed full audit trail -- incident: created, investigating, remediating, resolved; remediation: proposed, approved, execution_started, execution_succeeded"

section "26/27. Prove historical data wasn't deleted and Phase 8 mutated ONLY its own scoped rows"
INCIDENTS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.incidents;")"
INCIDENT_EVENTS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.incident_events;")"
REMEDIATION_PROPOSALS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_proposals;")"
REMEDIATION_EVENTS_COUNT_AFTER="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_events;")"
echo "  after:  incidents=$INCIDENTS_COUNT_AFTER incident_events=$INCIDENT_EVENTS_COUNT_AFTER remediation_proposals=$REMEDIATION_PROPOSALS_COUNT_AFTER remediation_events=$REMEDIATION_EVENTS_COUNT_AFTER"
# Never fewer than before (Phase 8 never deletes -- both remediation
# tables are append-only/RESTRICT-only by construction; see
# database/migrations/V6__create_remediation_schema.sql): a lower
# AFTER count than BEFORE would mean something was deleted.
[ "$INCIDENTS_COUNT_AFTER" -ge "$INCIDENTS_COUNT_BEFORE" ] || fail "reliability.incidents row count DECREASED ($INCIDENTS_COUNT_BEFORE -> $INCIDENTS_COUNT_AFTER) -- historical data was deleted"
[ "$INCIDENT_EVENTS_COUNT_AFTER" -ge "$INCIDENT_EVENTS_COUNT_BEFORE" ] || fail "reliability.incident_events row count DECREASED ($INCIDENT_EVENTS_COUNT_BEFORE -> $INCIDENT_EVENTS_COUNT_AFTER) -- historical audit data was deleted"
[ "$REMEDIATION_PROPOSALS_COUNT_AFTER" -ge "$REMEDIATION_PROPOSALS_COUNT_BEFORE" ] || fail "reliability.remediation_proposals row count DECREASED -- historical data was deleted"
[ "$REMEDIATION_EVENTS_COUNT_AFTER" -ge "$REMEDIATION_EVENTS_COUNT_BEFORE" ] || fail "reliability.remediation_events row count DECREASED -- historical audit data was deleted"
# Exactly this run's own expected growth -- this run creates ONE new
# incident, its own audit events (created/investigating/remediating/
# resolved = 4), ONE new remediation proposal, and its own 4
# remediation events (proposed/approved/execution_started/
# execution_succeeded). Growth larger or smaller than exactly this
# would mean either an unrelated row was also created, or this run's
# own expected rows were not all actually written.
[ "$((INCIDENTS_COUNT_AFTER - INCIDENTS_COUNT_BEFORE))" = "1" ] || fail "expected EXACTLY one new incident row, got a delta of $((INCIDENTS_COUNT_AFTER - INCIDENTS_COUNT_BEFORE))"
[ "$((INCIDENT_EVENTS_COUNT_AFTER - INCIDENT_EVENTS_COUNT_BEFORE))" = "4" ] || fail "expected EXACTLY 4 new incident_events rows (created/investigating/remediating/resolved), got a delta of $((INCIDENT_EVENTS_COUNT_AFTER - INCIDENT_EVENTS_COUNT_BEFORE))"
[ "$((REMEDIATION_PROPOSALS_COUNT_AFTER - REMEDIATION_PROPOSALS_COUNT_BEFORE))" = "1" ] || fail "expected EXACTLY one new remediation_proposals row, got a delta of $((REMEDIATION_PROPOSALS_COUNT_AFTER - REMEDIATION_PROPOSALS_COUNT_BEFORE))"
[ "$((REMEDIATION_EVENTS_COUNT_AFTER - REMEDIATION_EVENTS_COUNT_BEFORE))" = "4" ] || fail "expected EXACTLY 4 new remediation_events rows, got a delta of $((REMEDIATION_EVENTS_COUNT_AFTER - REMEDIATION_EVENTS_COUNT_BEFORE))"
remediation_rows_for_this_proposal="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_proposals WHERE id = '$PROPOSAL_ID';")"
[ "$remediation_rows_for_this_proposal" = "1" ] || fail "expected exactly one remediation_proposals row for this run's own proposal, found $remediation_rows_for_this_proposal"
other_incidents_untouched="$(psql_exec -c "SELECT count(*) FROM reliability.incidents WHERE id != '$INCIDENT_ID' AND updated_at > '$SINCE';")"
[ "$other_incidents_untouched" = "0" ] || fail "an incident OTHER than this run's own ($INCIDENT_ID) was updated during this run -- scoped-mutation proof failed (count=$other_incidents_untouched)"
other_proposals_created="$(psql_exec -c "SELECT count(*) FROM reliability.remediation_proposals WHERE id != '$PROPOSAL_ID' AND proposed_at > '$SINCE';")"
[ "$other_proposals_created" = "0" ] || fail "a remediation proposal OTHER than this run's own ($PROPOSAL_ID) was created during this run (count=$other_proposals_created)"
echo "  confirmed: no historical row was deleted; row-count growth is EXACTLY this run's own scoped mutations (one incident, one proposal, 4+4 audit events) -- nothing else touched"

echo ""
echo "PHASE 8 REMEDIATION ACCEPTANCE VERIFIED: a real checkout failure (induced by the controlled payment authorization fault, never a container stop) produced a real Prometheus alert, a real Alertmanager-ingested incident, and a real human-approved remediation proposal; tool-gateway independently re-verified approval before executing the ONE allowlisted action, cleared the real fault, independently verified recovery, and the SAME durable LangGraph run completed through its real interrupt/resume boundary (surviving a real agent-runtime-service restart while waiting); a fresh real checkout now succeeds, the real CheckoutServerErrors alert naturally recovered, and the SAME incident transitioned remediating -> resolved via Alertmanager's own real webhook -- with the complete incident + remediation audit trail intact and no historical or unrelated row touched."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
