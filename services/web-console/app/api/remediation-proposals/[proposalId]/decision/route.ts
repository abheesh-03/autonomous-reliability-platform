import { NextResponse } from "next/server";
import { backendErrorResponse } from "../../../../../lib/server/bff-error-response";
import { decideRemediationProposal, getRemediationProposal } from "../../../../../lib/server/control-plane-client";
import { rejectCrossOriginMutation } from "../../../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../../../lib/server/actor";

// Gate C's one new mutation boundary: records a human/operator
// decision on an ALREADY-DURABLE remediation proposal. This route
// NEVER calls resumeAgentRun -- decision and resume are deliberately
// two separate HTTP requests (see docs/architecture/phase-9-web-console.md).
// The operator must make a SEPARATE, explicit "Continue workflow"
// request (the Gate B resume route) after a decision is recorded; this
// route itself only ever writes the proposal/incident state the
// backend's own decide() method already owns.
//
// The browser sends ONLY {decision, comment?} -- never an
// expected_status. This server derives expected_status itself from a
// fresh read of the real, current, durable proposal immediately
// before deciding, so a stale browser-held status value can never be
// used as the optimistic-concurrency guard; the backend's own 409
// still rejects a decision that raced a concurrent change between
// this read and the decide() write.

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_COMMENT_CHARS = 1000;

interface DecisionRequestBody {
  decision: "approve" | "reject";
  comment?: string;
}

function parseBody(value: unknown): DecisionRequestBody | null {
  if (!value || typeof value !== "object") return null;
  const body = value as Record<string, unknown>;
  if (body.decision !== "approve" && body.decision !== "reject") return null;
  if (body.comment !== undefined) {
    if (typeof body.comment !== "string" || body.comment.length > MAX_COMMENT_CHARS) return null;
  }
  return { decision: body.decision, comment: body.comment as string | undefined };
}

export async function POST(request: Request, { params }: { params: Promise<{ proposalId: string }> }) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  // Phase 14 Gate 7 (security-critical): CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
  // (still attached by decideRemediationProposal below, unchanged)
  // alone is no longer treated as sufficient by THIS BFF either -- a
  // real, currently-authenticated actor is required before this route
  // even attempts the decision call, and that actor's own signed
  // assertion is forwarded so control-plane can independently verify
  // their role/organization against the proposal's owning incident.
  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");

  const { proposalId } = await params;

  if (!UUID_PATTERN.test(proposalId)) {
    return backendErrorResponse("validation");
  }

  const rawBody: unknown = await request.json().catch(() => null);
  const body = parseBody(rawBody);
  if (!body) {
    return backendErrorResponse("validation", "The decision request was rejected as invalid.");
  }

  const proposalResult = await getRemediationProposal(proposalId, controlPlaneToken);
  if (!proposalResult.ok) {
    return backendErrorResponse(proposalResult.error.kind);
  }

  const decisionResult = await decideRemediationProposal(
    proposalId,
    proposalResult.data.status,
    body.decision,
    body.comment,
    controlPlaneToken,
  );
  if (!decisionResult.ok) {
    return backendErrorResponse(decisionResult.error.kind);
  }

  const decided = decisionResult.data;
  // Bounded response: only what the browser needs to reconcile its
  // own view -- never the proposal's full internal fields.
  return NextResponse.json(
    {
      id: decided.id,
      status: decided.status,
      decided_at: decided.decided_at,
      decision_comment: decided.decision_comment,
      incident_id: decided.incident_id,
    },
    { status: 200 },
  );
}
