import "server-only";

import { NextResponse } from "next/server";
import type { BackendErrorKind } from "./http";

// Shared across every Route Handler (start-investigation, resume,
// decision) so the HTTP-status/message mapping can never silently
// diverge between them. Never a raw backend body -- always one of
// these fixed, safe, operator-facing messages (or an explicit
// override for a route-specific nuance, e.g. "approval still
// pending").
const STATUS_FOR_KIND: Record<BackendErrorKind, number> = {
  not_found: 404,
  validation: 422,
  conflict: 409,
  unauthorized: 500,
  configuration: 500,
  unavailable: 503,
  malformed: 502,
  forbidden: 403,
};

const MESSAGE_FOR_KIND: Record<BackendErrorKind, string> = {
  not_found: "Not found.",
  validation: "The request was rejected as invalid.",
  conflict: "The requested action is no longer valid for the current state.",
  unauthorized: "This server could not authenticate to a backend service.",
  configuration: "This server is not configured correctly for this action.",
  unavailable: "A backend service is temporarily unavailable.",
  malformed: "Received an unexpected response from a backend service.",
  forbidden: "You do not have permission to perform this action.",
};

export function backendErrorResponse(kind: BackendErrorKind, overrideMessage?: string) {
  return NextResponse.json(
    { error: kind, message: overrideMessage ?? MESSAGE_FOR_KIND[kind] },
    { status: STATUS_FOR_KIND[kind] },
  );
}
