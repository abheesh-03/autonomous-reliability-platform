import { NextResponse } from "next/server";
import { getAgentRun, resumeAgentRun } from "../../../../../lib/server/agent-runtime-client";
import { backendErrorResponse } from "../../../../../lib/server/bff-error-response";
import { getRemediationProposal } from "../../../../../lib/server/control-plane-client";
import { rejectCrossOriginMutation } from "../../../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../../../lib/server/actor";

// Gate B's mutation boundary: executes/continues an ALREADY-DURABLE
// AgentRun. This is a SEPARATE HTTP request from Stage 4's own
// start-investigation route by design -- the browser must already
// possess the durable run_id (received from a prior, separate
// request) before this one is ever called; this route never creates
// a run, and the start route never calls this one. See
// docs/architecture/phase-9-web-console.md.
//
// Makes AT MOST ONE resumeAgentRun call per browser request. Never
// retries automatically on a timeout/network error/ambiguous
// response: without an idempotency key on the backend's own resume
// endpoint, a blind retry could race or duplicate a still-in-flight
// execution. On any such failure, this returns a safe "unavailable"/
// "malformed" result and expects the caller (the browser's
// AgentRunActions component) to reconcile by re-fetching the durable
// AgentRun (a plain page refresh) rather than retrying blindly.

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  // Phase 14 Gate 5/7: a real, currently-authenticated actor is
  // required for every mutation this console's BFF performs -- never
  // just the existing origin/CSRF guard above.
  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");
  const agentRuntimeToken = await signAssertion(actorCheck.actor, "agent-runtime-service");

  const { runId } = await params;

  if (!UUID_PATTERN.test(runId)) {
    return backendErrorResponse("validation");
  }

  const agentRunResult = await getAgentRun(runId, agentRuntimeToken);
  if (!agentRunResult.ok) {
    return backendErrorResponse(agentRunResult.error.kind);
  }
  const agentRun = agentRunResult.data;

  if (!agentRun.resumable) {
    // Terminal (completed/failed, next empty per the backend's own
    // semantics) -- never attempted; the backend's own 409 would
    // catch this too, but checking the already-loaded `resumable`
    // field avoids an avoidable round trip for an outcome we already
    // know.
    return backendErrorResponse("conflict", "This agent run has already reached a terminal state and cannot be resumed.");
  }

  if (agentRun.status === "waiting_for_approval" && agentRun.remediation_proposal_id) {
    // Do not blindly resume while the real, durable proposal is still
    // undecided -- read it first and use its actual status, never a
    // guess. (If the backend's own interrupt-vs-proposal reconciliation
    // ever disagrees with this pre-check, the backend's own 409 is
    // still the final word; this is an optimization, not the only
    // safety net.)
    const proposalResult = await getRemediationProposal(agentRun.remediation_proposal_id, controlPlaneToken);
    if (!proposalResult.ok) {
      return backendErrorResponse(proposalResult.error.kind);
    }
    if (proposalResult.data.status === "pending_approval") {
      return backendErrorResponse("conflict", "The remediation proposal has not been decided yet.");
    }
  }

  const resumeResult = await resumeAgentRun(runId, agentRuntimeToken);
  if (!resumeResult.ok) {
    return backendErrorResponse(resumeResult.error.kind);
  }

  const resumed = resumeResult.data;
  // Bounded response: only the fields the browser needs to reconcile
  // its own view, never the entire backend AgentRun (investigation
  // report, checkpoint internals, etc. are all re-fetched by the
  // Server Component on refresh, never duplicated here).
  return NextResponse.json(
    {
      run_id: resumed.run_id,
      status: resumed.status,
      current_node: resumed.current_node,
      resumable: resumed.resumable,
      remediation_proposal_id: resumed.remediation_proposal_id,
      remediation_status: resumed.remediation_status,
    },
    { status: 200 },
  );
}
