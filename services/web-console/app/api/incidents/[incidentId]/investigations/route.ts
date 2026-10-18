import { NextResponse } from "next/server";
import { createAgentRun } from "../../../../../lib/server/agent-runtime-client";
import { getIncident, transitionIncidentStatus } from "../../../../../lib/server/control-plane-client";
import type { BackendErrorKind } from "../../../../../lib/server/http";

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

const STATUS_FOR_KIND: Record<BackendErrorKind, number> = {
  not_found: 404,
  validation: 422,
  conflict: 409,
  unauthorized: 500,
  configuration: 500,
  unavailable: 503,
  malformed: 502,
};

const MESSAGE_FOR_KIND: Record<BackendErrorKind, string> = {
  not_found: "Incident not found.",
  validation: "The request was rejected as invalid.",
  conflict: "The incident's status changed or no longer permits this action.",
  unauthorized: "This server could not authenticate to control-plane.",
  configuration: "This server is not configured to start investigations.",
  unavailable: "A backend service is temporarily unavailable.",
  malformed: "Received an unexpected response from a backend service.",
};

function errorResponse(kind: BackendErrorKind) {
  return NextResponse.json({ error: kind, message: MESSAGE_FOR_KIND[kind] }, { status: STATUS_FOR_KIND[kind] });
}

export async function POST(_request: Request, { params }: { params: Promise<{ incidentId: string }> }) {
  const { incidentId } = await params;

  if (!UUID_PATTERN.test(incidentId)) {
    return errorResponse("validation");
  }

  const incidentResult = await getIncident(incidentId);
  if (!incidentResult.ok) {
    return errorResponse(incidentResult.error.kind);
  }
  const incident = incidentResult.data;

  if (incident.status === "open" || incident.status === "acknowledged") {
    const transition = await transitionIncidentStatus(incidentId, incident.status, "investigating");
    if (!transition.ok) {
      return errorResponse(transition.error.kind);
    }
    // Falls through to agent-run creation below -- the incident is now
    // authoritatively "investigating".
  } else if (incident.status !== "investigating") {
    // remediating / resolved / closed: never a valid starting point
    // for a new investigation. No lifecycle transition is invented
    // here.
    return errorResponse("conflict");
  }
  // else: already "investigating" -- the PATCH is skipped entirely,
  // per the frozen start workflow (never a redundant transition merely
  // to satisfy a frontend assumption).

  const runResult = await createAgentRun(incidentId);
  if (!runResult.ok) {
    return errorResponse(runResult.error.kind);
  }

  // Bounded response: the browser needs the durable identifier, not
  // agent-runtime-service's entire internal AgentRun state.
  return NextResponse.json({ run_id: runResult.data.run_id, incident_id: incidentId }, { status: 201 });
}
