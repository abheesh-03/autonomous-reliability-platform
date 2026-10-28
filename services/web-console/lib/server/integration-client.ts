import "server-only";

import type {
  ConnectionType,
  IntegrationCredentialCreated,
  IntegrationCredentialListResponse,
} from "../types/integration";
import type { TelemetrySummary } from "../types/telemetry";
import { type BackendResult, buildQuery, fail, getJson, ok, postJson } from "./http";

const CONTROL_PLANE_URL = process.env.WEB_CONSOLE_CONTROL_PLANE_URL ?? "http://control-plane:8000";

function actorAuthHeader(actorToken: string): Record<string, string> {
  return { "X-Service-Assertion": actorToken };
}

/**
 * Phase 16 Gate 2/3: both calls REQUIRE a real actor token -- same
 * unconditional require_actor_context contract every Phase 15/16
 * services-registry route already uses. Creating/revoking additionally
 * requires control-plane's own real role check
 * (OWNER/ADMIN/ENGINEER) -- a 403 from either surfaces as
 * BackendErrorKind "forbidden".
 */
export async function createIntegrationCredential(
  serviceId: string,
  connectionType: ConnectionType,
  actorToken: string,
): Promise<BackendResult<IntegrationCredentialCreated>> {
  const result = await postJson(
    `${CONTROL_PLANE_URL}/api/v1/services/${encodeURIComponent(serviceId)}/integrations`,
    { connection_type: connectionType },
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON integration credential response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for integrations");
  }
  if (result.status === 403) {
    return fail("forbidden", "the current user's role does not permit creating an integration credential");
  }
  if (result.status === 404) {
    return fail("not_found", "service not found");
  }
  if (result.status !== 201) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for credential creation`);
  }
  const body = result.body as Partial<IntegrationCredentialCreated> | null;
  if (!body || !body.credential || typeof body.bearer_token !== "string") {
    return fail("malformed", "control-plane integration credential response did not match the expected shape");
  }
  return ok(body as IntegrationCredentialCreated);
}

export async function listIntegrationCredentials(
  serviceId: string,
  actorToken: string,
): Promise<BackendResult<IntegrationCredentialListResponse>> {
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/services/${encodeURIComponent(serviceId)}/integrations`,
    undefined,
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON integration list response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for integrations");
  }
  if (result.status === 404) {
    return fail("not_found", "service not found");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for the integration list`);
  }
  const body = result.body as Partial<IntegrationCredentialListResponse> | null;
  if (!body || !Array.isArray(body.items)) {
    return fail("malformed", "control-plane integration list response did not match the expected shape");
  }
  return ok(body as IntegrationCredentialListResponse);
}

export async function revokeIntegrationCredential(
  serviceId: string,
  integrationId: string,
  actorToken: string,
): Promise<BackendResult<void>> {
  const result = await postJson(
    `${CONTROL_PLANE_URL}/api/v1/services/${encodeURIComponent(serviceId)}/integrations/${encodeURIComponent(integrationId)}/revoke`,
    {},
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for integrations");
  }
  if (result.status === 403) {
    return fail("forbidden", "the current user's role does not permit revoking an integration credential");
  }
  if (result.status === 404) {
    return fail("not_found", "integration credential not found");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for credential revocation`);
  }
  return ok(undefined);
}

export async function getServiceTelemetrySummary(
  serviceId: string,
  actorToken: string,
  windowMinutes?: number,
): Promise<BackendResult<TelemetrySummary>> {
  const query = buildQuery({ window_minutes: windowMinutes });
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/services/${encodeURIComponent(serviceId)}/telemetry-summary${query}`,
    undefined,
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON telemetry summary response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "this server could not authenticate to control-plane for telemetry");
  }
  if (result.status === 404) {
    return fail("not_found", "service not found");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for the telemetry summary`);
  }
  const body = result.body as Partial<TelemetrySummary> | null;
  if (!body || typeof body.status !== "string" || typeof body.request_count !== "number") {
    return fail("malformed", "control-plane telemetry summary response did not match the expected shape");
  }
  return ok(body as TelemetrySummary);
}
