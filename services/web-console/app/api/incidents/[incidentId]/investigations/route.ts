import { NextResponse } from "next/server";
import { createAgentRun } from "../../../../../lib/server/agent-runtime-client";
import { backendErrorResponse } from "../../../../../lib/server/bff-error-response";
import { getIncident, transitionIncidentStatus } from "../../../../../lib/server/control-plane-client";
import { rejectCrossOriginMutation } from "../../../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../../../lib/server/actor";

// Stage 4's one mutation boundary: the browser never calls control-plane
// or agent-runtime-service directly, and never holds
// CONTROL_PLANE_LIFECYCLE_TOKEN -- see
// docs/architecture/phase-9-web-console.md.
//
// CORE INVARIANT this handler exists to preserve (Phase 7): the caller
// must receive the durable run_id BEFORE any fallible graph
// execution/resume begins. This handler NEVER calls
// POST /api/v1/agent-runs/{run_id}/resume -- that boundary belongs to
// a later stage. It also makes AT MOST ONE createAgentRun call per
// request: the current create endpoint has no idempotency key, so a
// blind retry on an ambiguous failure could create a second durable
// run for the same incident. If createAgentRun fails after a
// successful lifecycle transition, this handler does NOT attempt to
// roll the incident back to its prior status -- the lifecycle
// transition and agent-run creation are two separate durable systems,
// never one distributed transaction; the incident genuinely IS
// "investigating" at that point, and a safe retry of this same
// request handles that state correctly (skipping the PATCH, per the
// algorithm below).

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(request: Request, { params }: { params: Promise<{ incidentId: string }> }) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");
  const agentRuntimeToken = await signAssertion(actorCheck.actor, "agent-runtime-service");

  const { incidentId } = await params;

  if (!UUID_PATTERN.test(incidentId)) {
    return backendErrorResponse("validation");
  }

  const incidentResult = await getIncident(incidentId, controlPlaneToken);
  if (!incidentResult.ok) {
    return backendErrorResponse(incidentResult.error.kind);
  }
  const incident = incidentResult.data;

  if (incident.status === "open" || incident.status === "acknowledged") {
    const transition = await transitionIncidentStatus(incidentId, incident.status, "investigating", controlPlaneToken);
    if (!transition.ok) {
      return backendErrorResponse(transition.error.kind);
    }
    // Falls through to agent-run creation below -- the incident is now
    // authoritatively "investigating".
  } else if (incident.status !== "investigating") {
    // remediating / resolved / closed: never a valid starting point
    // for a new investigation. No lifecycle transition is invented
    // here.
    return backendErrorResponse("conflict", "The incident's status changed or no longer permits this action.");
  }
  // else: already "investigating" -- the PATCH is skipped entirely,
  // per the frozen start workflow (never a redundant transition merely
  // to satisfy a frontend assumption).

  const runResult = await createAgentRun(incidentId, agentRuntimeToken);
  if (!runResult.ok) {
    return backendErrorResponse(runResult.error.kind);
  }

  // Bounded response: the browser needs the durable identifier, not
  // agent-runtime-service's entire internal AgentRun state.
  return NextResponse.json({ run_id: runResult.data.run_id, incident_id: incidentId }, { status: 201 });
}
