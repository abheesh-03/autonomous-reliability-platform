import { NextResponse } from "next/server";
import { backendErrorResponse } from "../../../../../../../lib/server/bff-error-response";
import { rejectCrossOriginMutation } from "../../../../../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../../../../../lib/server/actor";
import { revokeIntegrationCredential } from "../../../../../../../lib/server/integration-client";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ serviceId: string; integrationId: string }> },
) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");

  const { serviceId, integrationId } = await params;
  const result = await revokeIntegrationCredential(serviceId, integrationId, controlPlaneToken);
  if (!result.ok) {
    return backendErrorResponse(result.error.kind);
  }
  return NextResponse.json({ ok: true });
}
