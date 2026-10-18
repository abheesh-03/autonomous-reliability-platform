import "server-only";

import type {
  Incident,
  IncidentEvent,
  IncidentEventListResponse,
  IncidentListResponse,
  IncidentSeverity,
  IncidentStatus,
} from "../types/incident";
import type {
  RemediationEvent,
  RemediationEventListResponse,
  RemediationProposal,
  RemediationProposalListResponse,
  RemediationProposalStatus,
} from "../types/remediation";
import {
  type BackendResult,
  buildQuery,
  fail,
  fetchAllPages,
  getJson,
  ok,
  patchJson,
  postJson,
} from "./http";

const CONTROL_PLANE_URL =
  process.env.WEB_CONSOLE_CONTROL_PLANE_URL ?? "http://control-plane:8000";

/**
 * Reads CONTROL_PLANE_LIFECYCLE_TOKEN fresh on every call (never cached
 * at module load, so a corrected .env takes effect on the next request
 * without a process restart) -- returns null for unset OR
 * whitespace-only, treated identically as "not configured".
 */
function getLifecycleToken(): string | null {
  const token = process.env.CONTROL_PLANE_LIFECYCLE_TOKEN;
  return token && token.trim().length > 0 ? token : null;
}

/**
 * Same fresh-read, fail-closed convention as getLifecycleToken --
 * reuses control-plane's EXISTING CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
 * secret (api/auth.py::require_remediation_approver_token). This is a
 * distinct secret from the lifecycle token: the approver token proves
 * "a human decided this proposal," never "this server may transition
 * incident lifecycle," and the two must never be used interchangeably.
 */
function getRemediationApproverToken(): string | null {
  const token = process.env.CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN;
  return token && token.trim().length > 0 ? token : null;
}

export interface ListIncidentsParams {
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  source?: string;
  limit?: number;
  offset?: number;
}

// Mirrors control-plane's own bounds exactly (api/incidents.py):
// limit 1..100 (default 20), offset >=0 (default 0). Clamped here as a
// defensive second layer -- the page itself also clamps whatever a
// browser-supplied query string contained before it ever reaches this
// function.
function clampLimit(limit: number | undefined): number {
  if (limit === undefined || !Number.isFinite(limit)) return 20;
  return Math.min(100, Math.max(1, Math.trunc(limit)));
}

function clampOffset(offset: number | undefined): number {
  if (offset === undefined || !Number.isFinite(offset)) return 0;
  return Math.max(0, Math.trunc(offset));
}

export async function listIncidents(
  params: ListIncidentsParams,
): Promise<BackendResult<IncidentListResponse>> {
  const query = buildQuery({
    status: params.status,
    severity: params.severity,
    source: params.source,
    limit: clampLimit(params.limit),
    offset: clampOffset(params.offset),
  });
  const result = await getJson(`${CONTROL_PLANE_URL}/api/v1/incidents${query}`);
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON incident list response");
  }
  if (result.status === 422) {
    return fail("validation", "control-plane rejected the incident list query parameters");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for incident list`);
  }
  const body = result.body as Partial<IncidentListResponse> | null;
  if (
    !body ||
    !Array.isArray(body.items) ||
    typeof body.total !== "number" ||
    typeof body.limit !== "number" ||
    typeof body.offset !== "number"
  ) {
    return fail("malformed", "control-plane incident list response did not match the expected shape");
  }
  return ok(body as IncidentListResponse);
}

export async function getIncident(incidentId: string): Promise<BackendResult<Incident>> {
  const result = await getJson(`${CONTROL_PLANE_URL}/api/v1/incidents/${encodeURIComponent(incidentId)}`);
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON incident response");
  }
  if (result.status === 404) {
    return fail("not_found", "incident not found");
  }
  if (result.status === 422) {
    return fail("validation", "invalid incident identifier");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for incident detail`);
  }
  const body = result.body as Partial<Incident> | null;
  if (!body || typeof body.id !== "string" || typeof body.status !== "string") {
    return fail("malformed", "control-plane incident response did not match the expected shape");
  }
  return ok(body as Incident);
}

/**
 * Stage 4's one mutation: PATCH /api/v1/incidents/{id}/status, the
 * ONLY write path this console's server is allowed to call. Fails
 * CLOSED before any network request if CONTROL_PLANE_LIFECYCLE_TOKEN
 * is unset/blank -- never sends an unauthenticated request and hopes
 * for a useful response. `expected_status`/`target_status` are sent
 * exactly as given (optimistic-concurrency guard the backend itself
 * enforces); this function never guesses or re-reads the current
 * status on the caller's behalf.
 */
export async function transitionIncidentStatus(
  incidentId: string,
  expectedStatus: IncidentStatus,
  targetStatus: IncidentStatus,
): Promise<BackendResult<Incident>> {
  const token = getLifecycleToken();
  if (!token) {
    return fail("configuration", "the lifecycle token is not configured on this server");
  }

  const result = await patchJson(
    `${CONTROL_PLANE_URL}/api/v1/incidents/${encodeURIComponent(incidentId)}/status`,
    { expected_status: expectedStatus, target_status: targetStatus },
    { Authorization: `Bearer ${token}` },
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON incident status response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "control-plane rejected this server's lifecycle token");
  }
  if (result.status === 404) {
    return fail("not_found", "incident not found");
  }
  if (result.status === 409) {
    return fail("conflict", "the incident's status changed or the transition is not permitted");
  }
  if (result.status === 422) {
    return fail("validation", "control-plane rejected the status transition request");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `control-plane returned unexpected status ${result.status} for the incident status transition`,
    );
  }
  const body = result.body as Partial<Incident> | null;
  if (!body || typeof body.id !== "string" || typeof body.status !== "string") {
    return fail("malformed", "control-plane incident status response did not match the expected shape");
  }
  return ok(body as Incident);
}

async function getIncidentEventsPage(
  incidentId: string,
  limit: number,
  offset: number,
): Promise<BackendResult<IncidentEventListResponse>> {
  const query = buildQuery({ limit, offset });
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/incidents/${encodeURIComponent(incidentId)}/events${query}`,
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON incident events response");
  }
  if (result.status === 404) {
    return fail("not_found", "incident not found");
  }
  if (result.status !== 200) {
    return fail("unavailable", `control-plane returned unexpected status ${result.status} for incident events`);
  }
  const body = result.body as Partial<IncidentEventListResponse> | null;
  if (!body || !Array.isArray(body.items) || typeof body.total !== "number") {
    return fail("malformed", "control-plane incident events response did not match the expected shape");
  }
  return ok(body as IncidentEventListResponse);
}

/**
 * The incident detail page shows the COMPLETE durable audit timeline,
 * never just the first default-sized page -- see fetchAllPages's own
 * bounded-pagination contract (lib/server/http.ts).
 */
export async function getAllIncidentEvents(incidentId: string): Promise<BackendResult<IncidentEvent[]>> {
  return fetchAllPages((limit, offset) => getIncidentEventsPage(incidentId, limit, offset));
}

async function getIncidentRemediationProposalsPage(
  incidentId: string,
  limit: number,
  offset: number,
): Promise<BackendResult<RemediationProposalListResponse>> {
  const query = buildQuery({ limit, offset });
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/incidents/${encodeURIComponent(incidentId)}/remediation-proposals${query}`,
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON remediation proposal list response");
  }
  if (result.status === 404) {
    return fail("not_found", "incident not found");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `control-plane returned unexpected status ${result.status} for remediation proposals`,
    );
  }
  const body = result.body as Partial<RemediationProposalListResponse> | null;
  if (!body || !Array.isArray(body.items) || typeof body.total !== "number") {
    return fail("malformed", "control-plane remediation proposal list response did not match the expected shape");
  }
  return ok(body as RemediationProposalListResponse);
}

export async function getAllIncidentRemediationProposals(
  incidentId: string,
): Promise<BackendResult<RemediationProposal[]>> {
  return fetchAllPages((limit, offset) => getIncidentRemediationProposalsPage(incidentId, limit, offset));
}

// Stage 3: used only to enrich an AgentRun's own remediation_proposal_id
// with the durable proposal's real fields (reason, decision, execution
// timestamps) on /agent-runs/[runId] -- a real, existing, unauthenticated
// GET endpoint, never a new discovery API.
export async function getRemediationProposal(proposalId: string): Promise<BackendResult<RemediationProposal>> {
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/remediation-proposals/${encodeURIComponent(proposalId)}`,
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON remediation proposal response");
  }
  if (result.status === 404) {
    return fail("not_found", "remediation proposal not found");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `control-plane returned unexpected status ${result.status} for remediation proposal`,
    );
  }
  const body = result.body as Partial<RemediationProposal> | null;
  if (!body || typeof body.id !== "string" || typeof body.status !== "string") {
    return fail("malformed", "control-plane remediation proposal response did not match the expected shape");
  }
  return ok(body as RemediationProposal);
}

/**
 * Gate C's one new mutation: POST
 * /api/v1/remediation-proposals/{id}/decision. Fails CLOSED before any
 * network request if CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN is
 * unset/blank -- same convention as transitionIncidentStatus. The real
 * backend endpoint is a POST (never PATCH) despite being a state
 * transition, per api/remediation.py::decide_remediation_proposal --
 * this function uses postJson accordingly, not patchJson.
 *
 * `expectedStatus` must be the CALLER's own freshly-read current
 * status (optimistic-concurrency guard the backend itself enforces);
 * this function never guesses or re-reads it. On approve, the backend
 * ALSO atomically transitions the owning incident
 * investigating -> remediating in the same DB transaction; on reject,
 * the backend touches only the proposal row, never the incident. This
 * client never re-implements either rule -- it only forwards the
 * decision and reports the backend's own resulting proposal.
 */
export async function decideRemediationProposal(
  proposalId: string,
  expectedStatus: RemediationProposalStatus,
  decision: "approve" | "reject",
  comment?: string,
): Promise<BackendResult<RemediationProposal>> {
  const token = getRemediationApproverToken();
  if (!token) {
    return fail("configuration", "the remediation approver token is not configured on this server");
  }

  const result = await postJson(
    `${CONTROL_PLANE_URL}/api/v1/remediation-proposals/${encodeURIComponent(proposalId)}/decision`,
    { expected_status: expectedStatus, decision, comment: comment ?? null },
    { Authorization: `Bearer ${token}` },
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON remediation decision response");
  }
  if (result.status === 401) {
    return fail("unauthorized", "control-plane rejected this server's remediation approver token");
  }
  if (result.status === 404) {
    return fail("not_found", "remediation proposal not found");
  }
  if (result.status === 409) {
    return fail("conflict", "the proposal's status changed, or the owning incident is no longer eligible");
  }
  if (result.status === 422) {
    return fail("validation", "control-plane rejected the remediation decision request");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `control-plane returned unexpected status ${result.status} for the remediation decision`,
    );
  }
  const body = result.body as Partial<RemediationProposal> | null;
  if (!body || typeof body.id !== "string" || typeof body.status !== "string") {
    return fail("malformed", "control-plane remediation decision response did not match the expected shape");
  }
  return ok(body as RemediationProposal);
}

async function getRemediationProposalEventsPage(
  proposalId: string,
  limit: number,
  offset: number,
): Promise<BackendResult<RemediationEventListResponse>> {
  const query = buildQuery({ limit, offset });
  const result = await getJson(
    `${CONTROL_PLANE_URL}/api/v1/remediation-proposals/${encodeURIComponent(proposalId)}/events${query}`,
  );
  if ("networkError" in result) {
    return fail("unavailable", "control-plane unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "control-plane returned a non-JSON remediation event response");
  }
  if (result.status === 404) {
    return fail("not_found", "remediation proposal not found");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `control-plane returned unexpected status ${result.status} for remediation proposal events`,
    );
  }
  const body = result.body as Partial<RemediationEventListResponse> | null;
  if (!body || !Array.isArray(body.items) || typeof body.total !== "number") {
    return fail("malformed", "control-plane remediation event response did not match the expected shape");
  }
  return ok(body as RemediationEventListResponse);
}

export async function getAllRemediationProposalEvents(
  proposalId: string,
): Promise<BackendResult<RemediationEvent[]>> {
  return fetchAllPages((limit, offset) => getRemediationProposalEventsPage(proposalId, limit, offset));
}
