#!/usr/bin/env bash
#
# verify-kubernetes-remediation-live.sh — Phase 12B-D, Gate 9: an
# OPT-IN, EXPLICIT-CONFIRMATION-REQUIRED live acceptance script for the
# ONE allowlisted Kubernetes remediation action
# (restart_allowlisted_deployment against
# Deployment/reliability-sandbox/crashloop-demo in cluster
# kind-reliability-lab).
#
# ====================================================================
# THIS SCRIPT IS PREPARED BUT HAS NEVER BEEN RUN.
# ====================================================================
# No live Kubernetes write has been validated by this phase's own work
# -- only the OFFLINE integration acceptance (mocked Kubernetes
# transport, real policy/approval/executor logic) and the LIVE
# READ-ONLY acceptance (scripts/verify-kubernetes-observer-real-stack.sh,
# Phase 12A) have actually been executed. Running THIS script is a
# separate, explicit, human-approved action -- never implied by
# anything else in this round.
#
# Unlike every other verify-*.sh script in this repo, this one:
#   - performs a REAL Kubernetes write (a Deployment rollout restart)
#     against a REAL cluster, if, and only if, every guard below
#     passes AND the operator explicitly confirms interactively;
#   - requires TOOL_GATEWAY_KUBERNETES_EXECUTION_ENABLED=true to
#     already be set in tool-gateway's OWN process environment (this
#     script cannot and does not set it for tool-gateway -- that is a
#     separate, deliberate operator action, Gate 6: "a real Kubernetes
#     write requires a separate explicit operator opt-in after source
#     review");
#   - refuses outright (exit 1, no write of any kind) if tool-gateway's
#     own kubernetes capability endpoint reports no confirmed targeted
#     failure right now (precondition_met=false) -- this script never
#     injects a failure to make the precondition true; Gate 9: "Do not
#     inject failures";
#   - is NEVER invoked by `make`, CI, or any other script in this
#     repository -- it must be run directly, by a human, who has
#     already read this entire file;
#   - reuses the EXACT same real APIs a real agent run would use
#     (control-plane's finding-ingestion/incident/remediation-proposal
#     endpoints, agent-runtime-service's own /api/v1/agent-runs
#     create/resume), mirroring scripts/verify-remediation.sh's own
#     real-end-to-end convention -- never a shortcut that bypasses the
#     durable proposal/approval/execution path.
#
# Target identity is HARD-CODED -- TARGET_CLUSTER/TARGET_NAMESPACE/
# TARGET_DEPLOYMENT are never overridable via environment or flag, and
# there is no notion of "production" this script could ever be pointed
# at.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

readonly TARGET_CLUSTER="kind-reliability-lab"
readonly TARGET_NAMESPACE="reliability-sandbox"
readonly TARGET_DEPLOYMENT="crashloop-demo"
readonly TARGET_DEPLOYMENT_REF="Deployment/$TARGET_NAMESPACE/$TARGET_DEPLOYMENT"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://localhost:8000}"
TOOL_GATEWAY_URL="${TOOL_GATEWAY_URL:-http://localhost:8004}"
AGENT_RUNTIME_URL="${AGENT_RUNTIME_URL:-http://localhost:8003}"

fail() {
  echo "REFUSED/FAILED: $1" >&2
  exit 1
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "$name must be set in this shell's environment before running this script"
}

tg_get() {
  curl -s --connect-timeout 2 --max-time 15 -w '\n%{http_code}' \
    -H "Authorization: Bearer ${TOOL_GATEWAY_EXECUTION_TOKEN}" "$TOOL_GATEWAY_URL$1"
}

cp_post() {
  # cp_post <path> <bearer-token> <json-body>
  curl -s --connect-timeout 2 --max-time 15 -w '\n%{http_code}' -X POST "$CONTROL_PLANE_URL$1" \
    -H "Authorization: Bearer $2" -H "Content-Type: application/json" -d "$3"
}

ar_post() {
  curl -s --connect-timeout 2 --max-time 30 -w '\n%{http_code}' -X POST "$AGENT_RUNTIME_URL$1" \
    -H "Content-Type: application/json" -d "${2:-{\}}"
}

body_of() { echo "$1" | sed '$d'; }
status_of() { echo "$1" | tail -1; }

main() {
cd "$REPO_ROOT"

echo "====================================================================" >&2
echo "Phase 12B-D LIVE Kubernetes remediation acceptance -- READ THIS FULLY" >&2
echo "====================================================================" >&2
echo "Target (hard-coded, not overridable): $TARGET_DEPLOYMENT_REF in cluster $TARGET_CLUSTER" >&2
echo "" >&2

require_env TOOL_GATEWAY_EXECUTION_TOKEN
require_env CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN
require_env CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN

echo "=== Step 1/6: preflight -- tool-gateway's own fresh kubernetes capability read ===" >&2
cap_resp="$(tg_get /api/v1/remediation-capabilities/kubernetes)"
[[ "$(status_of "$cap_resp")" == "200" ]] || fail "GET /api/v1/remediation-capabilities/kubernetes returned $(status_of "$cap_resp") -- is tool-gateway running with TOOL_GATEWAY_KUBERNETES_* configured?"
cap_body="$(body_of "$cap_resp")"
echo "$cap_body" | python3 -m json.tool >&2

observed_uid="$(echo "$cap_body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("deployment_uid") or "")')"
precondition_met="$(echo "$cap_body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("precondition_met"))')"
[[ -n "$observed_uid" ]] || fail "no deployment_uid in tool-gateway's response -- refusing to proceed without a real identity to bind to"
[[ "$precondition_met" == "True" ]] || fail "precondition_met=false -- $TARGET_DEPLOYMENT_REF is not currently showing a confirmed targeted failure. This script never injects one (Gate 9); nothing to remediate right now."

echo "" >&2
echo "Current observed Deployment UID: $observed_uid" >&2
read -r -p "Type the EXACT phrase to confirm — 'restart $TARGET_DEPLOYMENT uid=$observed_uid': " confirmation
[[ "$confirmation" == "restart $TARGET_DEPLOYMENT uid=$observed_uid" ]] || fail "confirmation phrase did not match exactly -- nothing was done"

echo "=== Step 2/6: ingest a Kubernetes finding to create/update a durable incident ===" >&2
# A minimal, honest finding -- this script does not run the full
# detectors/kubernetes pipeline itself; it reports exactly what Step 1
# above already independently confirmed (a confirmed targeted failure,
# per tool-gateway's own fresh read), never a fabricated detector
# result.
collected_at="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.UTC).isoformat())')"
finding_body=$(python3 -c "
import json
print(json.dumps({
    'cluster': '$TARGET_CLUSTER', 'namespace': '$TARGET_NAMESPACE', 'resource_kind': 'Deployment',
    'resource_name': '$TARGET_DEPLOYMENT', 'resource_uid': '$observed_uid', 'detector_id': 'crash_loop_backoff',
    'result': 'confirmed', 'collection_completeness': 'complete', 'collected_at': '$collected_at',
    'decision_rationale': 'verify-kubernetes-remediation-live.sh: tool-gateway independently confirmed a targeted failure reason on this Deployment immediately before this run',
}))
")
ingest_resp="$(cp_post /internal/v1/kubernetes/findings "$CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN" "$finding_body")"
[[ "$(status_of "$ingest_resp")" == "201" ]] || fail "POST /internal/v1/kubernetes/findings returned $(status_of "$ingest_resp"): $(body_of "$ingest_resp")"
incident_id="$(body_of "$ingest_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["incident_id"])')"
echo "  incident_id=$incident_id" >&2

echo "=== Step 3/6: start a REAL durable agent run for this incident, resume until the approval interrupt ===" >&2
create_resp="$(ar_post /api/v1/agent-runs "{\"incident_id\":\"$incident_id\"}")"
[[ "$(status_of "$create_resp")" == "201" ]] || fail "POST /api/v1/agent-runs returned $(status_of "$create_resp"): $(body_of "$create_resp")"
run_id="$(body_of "$create_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
echo "  run_id=$run_id" >&2

proposal_id=""
for _attempt in 1 2 3 4 5; do
  resume_resp="$(ar_post "/api/v1/agent-runs/$run_id/resume")"
  [[ "$(status_of "$resume_resp")" == "200" ]] || fail "resume returned $(status_of "$resume_resp"): $(body_of "$resume_resp")"
  proposal_id="$(body_of "$resume_resp" | python3 -c 'import json,sys; b=json.load(sys.stdin); print((b.get("remediation_proposal_id") or ""))' 2>/dev/null || true)"
  [[ -n "$proposal_id" ]] && break
  sleep 2
done
[[ -n "$proposal_id" ]] || fail "no remediation proposal appeared after repeated resumes -- the deterministic policy may not have matched (see propose_remediation's own kubernetes branch)"
echo "  proposal_id=$proposal_id" >&2

echo "=== Step 4/6: approve via the REAL control-plane operator endpoint (this script IS the human operator) ===" >&2
decision_resp="$(cp_post "/api/v1/remediation-proposals/$proposal_id/decision" "$CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN" \
  '{"expected_status":"pending_approval","decision":"approve","comment":"verify-kubernetes-remediation-live.sh acceptance run"}')"
[[ "$(status_of "$decision_resp")" == "200" ]] || fail "decision (approve) returned $(status_of "$decision_resp"): $(body_of "$decision_resp")"
echo "  approved" >&2

echo "=== Step 5/6: resume the agent run -- this triggers the REAL tool-gateway execute()/restart/verify ===" >&2
exec_resp="$(ar_post "/api/v1/agent-runs/$run_id/resume")"
[[ "$(status_of "$exec_resp")" == "200" ]] || fail "resume (execute) returned $(status_of "$exec_resp"): $(body_of "$exec_resp")"
remediation_status="$(body_of "$exec_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("remediation_status"))')"
echo "  remediation_status=$remediation_status" >&2
body_of "$exec_resp" | python3 -m json.tool >&2 || true

echo "=== Step 6/6: independent postcondition verification (fresh, read-only) ===" >&2
"$SCRIPT_DIR/verify-kubernetes-observer-real-stack.sh" || echo "  (read-only observer script reported a non-zero exit -- see its own output above)" >&2

echo "" >&2
if [[ "$remediation_status" == "succeeded" ]]; then
  echo "LIVE KUBERNETES REMEDIATION ACCEPTANCE: remediation_status=succeeded (tool-gateway's own independent recovery verification confirmed VERIFIED_RECOVERED before reporting this)." >&2
else
  echo "LIVE KUBERNETES REMEDIATION ACCEPTANCE: remediation_status=$remediation_status -- this is reported exactly as observed, never papered over." >&2
fi
echo "No cluster resource was created by this script; nothing of this script's own needs to be cleaned up. The restart annotation applied to $TARGET_DEPLOYMENT_REF is not reverted (a rollout restart has no meaningful undo -- see 'kubectl rollout history' for that Deployment's own history)." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
