import { NextResponse } from "next/server";
import { backendErrorResponse } from "../../../../../lib/server/bff-error-response";
import { rejectCrossOriginMutation } from "../../../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../../../lib/server/actor";
import { createIntegrationCredential, listIntegrationCredentials } from "../../../../../lib/server/integration-client";

/**
 * Phase 16 Gate 10: the browser never calls control-plane directly --
 * same BFF-only pattern every existing mutation route already follows.
 * POST creates a real credential and returns its real secret EXACTLY
 * ONCE, straight through from control-plane's own one-time response;
 * this route never persists or logs it.
 */
export async function POST(request: Request, { params }: { params: Promise<{ serviceId: string }> }) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");

  const { serviceId } = await params;
  const result = await createIntegrationCredential(serviceId, "opentelemetry", controlPlaneToken);
  if (!result.ok) {
    return backendErrorResponse(result.error.kind);
  }
  return NextResponse.json(result.data, { status: 201 });
}

export async function GET(_request: Request, { params }: { params: Promise<{ serviceId: string }> }) {
  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");

  const { serviceId } = await params;
  const result = await listIntegrationCredentials(serviceId, controlPlaneToken);
  if (!result.ok) {
    return backendErrorResponse(result.error.kind);
  }
  return NextResponse.json(result.data);
}
