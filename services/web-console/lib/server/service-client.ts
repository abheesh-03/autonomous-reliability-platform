import "server-only";

import type { RegisteredService, ServiceKind, ServiceListResponse } from "../types/service";
import { type BackendResult, buildQuery, fail, getJson, ok, postJson } from "./http";

const CONTROL_PLANE_URL = process.env.WEB_CONSOLE_CONTROL_PLANE_URL ?? "http://control-plane:8000";

function actorAuthHeader(actorToken: string): Record<string, string> {
  return { "X-Service-Assertion": actorToken };
}

// Mirrors control-plane's own bounds exactly (api/services.py): limit
// 1..100 (default 20), offset >=0 (default 0).
function clampLimit(limit: number | undefined): number {
  if (limit === undefined || !Number.isFinite(limit)) return 20;
  return Math.min(100, Math.max(1, Math.trunc(limit)));
}

function clampOffset(offset: number | undefined): number {
  if (offset === undefined || !Number.isFinite(offset)) return 0;
  return Math.max(0, Math.trunc(offset));
}

/**
 * Both calls REQUIRE a real actor token -- control-plane's own
 * require_actor_context dependency rejects a missing/absent assertion
 * with 401 unconditionally for this resource (see
 * core/authz.py::require_actor_context's own docstring), unlike every
 * pre-Phase-15 endpoint this console also calls.
 *
 * Independent-review correction round, BLOCKER 4: genuinely paginated
 * -- never fetches every service merely to display or count them. A
 * caller that only needs the total (e.g. the dashboard's services
 * card) should pass `{ limit: 1, offset: 0 }` and read `.total`, never
 * omit pagination and read `.items.length`.
 */
export async function listServices(
  actorToken: string,
  params: { limit?: number; offset?: number } = {},
): Promise<BackendResult<ServiceListResponse>> {
  const query = buildQuery({ limit: clampLimit(params.limit), offset: clampOffset(params.offset) });
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/services${query}`,
    undefined,
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON service list response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for the service registry");
  }
  if (result.status === 422) {
    return fail("validation", "control-plane rejected the service list query parameters");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for the service list`);
  }
  const body = result.body as Partial<ServiceListResponse> | null;
  if (
    !body ||
    !Array.isArray(body.items) ||
    typeof body.total !== "number" ||
    typeof body.limit !== "number" ||
    typeof body.offset !== "number"
  ) {
    return fail("malformed", "control-plane service list response did not match the expected shape");
  }
  return ok(body as ServiceListResponse);
}

export async function createService(
  input: { name: string; kind: ServiceKind; language: string | null; description: string | null },
  actorToken: string,
): Promise<BackendResult<RegisteredService>> {
  const result = await postJson(`${CONTROL_PLANE_URL}/api/v1/services`, input, actorAuthHeader(actorToken));
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON service response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for the service registry");
  }
  if (result.status === 403) {
    return fail("forbidden", "the current user's role does not permit registering a service");
  }
  if (result.status === 409) {
    return fail("conflict", "a service with this name is already registered in this organization");
  }
  if (result.status === 422) {
    return fail("validation", "control-plane rejected the new service request");
  }
  if (result.status !== 201) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for service creation`);
  }
  const body = result.body as Partial<RegisteredService> | null;
  if (!body || typeof body.id !== "string") {
    return fail("malformed", "control-plane service response did not match the expected shape");
  }
  return ok(body as RegisteredService);
}
