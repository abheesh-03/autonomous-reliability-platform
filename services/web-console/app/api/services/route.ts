import { NextResponse } from "next/server";
import { backendErrorResponse } from "../../../lib/server/bff-error-response";
import { rejectCrossOriginMutation } from "../../../lib/server/origin-guard";
import { requireActorOrUnauthorized, signAssertion } from "../../../lib/server/actor";
import { createService } from "../../../lib/server/service-client";
import { SERVICE_KINDS, type ServiceKind } from "../../../lib/types/service";

/**
 * Phase 15 Gate 10: the browser never calls control-plane directly --
 * this is the one mutation boundary for service registration, same
 * BFF-only pattern every existing mutation route already follows. The
 * real assertion this mints is the ONLY thing that makes control-plane's
 * own require_actor_context dependency accept the request.
 */
export async function POST(request: Request) {
  const originRejection = rejectCrossOriginMutation(request);
  if (originRejection) return originRejection;

  const actorCheck = await requireActorOrUnauthorized();
  if (!actorCheck.ok) return actorCheck.response;
  const controlPlaneToken = await signAssertion(actorCheck.actor, "control-plane");

  const body: unknown = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return backendErrorResponse("validation");
  }
  const { name, kind, language, description } = body as Record<string, unknown>;
  if (typeof name !== "string" || name.trim().length === 0 || name.length > 200) {
    return backendErrorResponse("validation");
  }
  if (typeof kind !== "string" || !SERVICE_KINDS.includes(kind as ServiceKind)) {
    return backendErrorResponse("validation");
  }
  if (language !== null && typeof language !== "undefined" && typeof language !== "string") {
    return backendErrorResponse("validation");
  }
  if (description !== null && typeof description !== "undefined" && typeof description !== "string") {
    return backendErrorResponse("validation");
  }

  const result = await createService(
    {
      name: name.trim(),
      kind: kind as ServiceKind,
      language: typeof language === "string" && language.trim().length > 0 ? language.trim() : null,
      description: typeof description === "string" && description.trim().length > 0 ? description.trim() : null,
    },
    controlPlaneToken,
  );
  if (!result.ok) {
    return backendErrorResponse(result.error.kind);
  }
  return NextResponse.json(result.data, { status: 201 });
}
