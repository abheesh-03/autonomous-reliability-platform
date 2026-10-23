import "server-only";

import { type BackendResult, fail, getJson, ok, postJson } from "./http";
import { parseAgentRun, parseAgentRunHistory } from "./agent-run-validation";
import type { AgentRun, AgentRunHistory } from "../types/agent-run";

const AGENT_RUNTIME_URL = process.env.WEB_CONSOLE_AGENT_RUNTIME_URL ?? "http://agent-runtime-service:8003";

// Re-audited (Gate A) against scripts/verify-agent-runtime.sh's own
// `agent_runtime_post` helper -- the proven, already-successful real
// acceptance flow calls POST .../resume with `curl --max-time 60`,
// never the generic 5s mutation timeout used for ordinary
// reads/writes elsewhere in this client. A resume call can execute
// several real graph nodes (investigation, evaluation, proposal
// creation, tool-gateway execution, recovery verification) before
// pausing at the next interrupt or finishing -- far longer than a
// simple read or a single PATCH/POST.
const RESUME_TIMEOUT_MS = 60_000;

// Phase 14 Gate 8: same dedicated-header convention as
// control-plane-client.ts's actorAuthHeader -- see that module's
// docstring for why this is never `Authorization`.
function actorAuthHeader(actorToken?: string): Record<string, string> {
  return actorToken ? { "X-Service-Assertion": actorToken } : {};
}

export async function getAgentRun(runId: string, actorToken?: string): Promise<BackendResult<AgentRun>> {
  const result = await getJson(
    `${AGENT_RUNTIME_URL}/api/v1/agent-runs/${encodeURIComponent(runId)}`,
    undefined,
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "agent-runtime-service unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "agent-runtime-service returned a non-JSON agent run response");
  }
  if (result.status === 404) {
    return fail("not_found", "agent run not found");
  }
  if (result.status === 422) {
    return fail("validation", "invalid agent run identifier");
  }
  if (result.status !== 200) {
    return fail("unavailable", `agent-runtime-service returned unexpected status ${result.status} for agent run`);
  }
  const agentRun = parseAgentRun(result.body);
  if (!agentRun) {
    return fail("malformed", "agent-runtime-service agent run response did not match the expected shape");
  }
  return ok(agentRun);
}

/**
 * Seeds a durable checkpoint ONLY -- agent-runtime-service's own
 * POST /api/v1/agent-runs never executes a node or calls control-plane/
 * investigator-service (Phase 7's own core invariant). This function
 * makes exactly ONE POST per call; it never retries on an ambiguous
 * failure, since the current create endpoint has no idempotency key
 * and a blind retry could create a second durable run for the same
 * incident (see docs/architecture/phase-9-web-console.md). The caller
 * (the start-investigation Route Handler) is responsible for making
 * at most one call per browser request.
 */
export async function createAgentRun(incidentId: string, actorToken?: string): Promise<BackendResult<AgentRun>> {
  const result = await postJson(
    `${AGENT_RUNTIME_URL}/api/v1/agent-runs`,
    { incident_id: incidentId },
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "agent-runtime-service unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "agent-runtime-service returned a non-JSON agent run response");
  }
  if (result.status === 403) {
    return fail("forbidden", "the current user's role does not permit starting an investigation");
  }
  if (result.status === 422) {
    return fail("validation", "agent-runtime-service rejected the agent run request");
  }
  if (result.status !== 201) {
    return fail(
      "unavailable",
      `agent-runtime-service returned unexpected status ${result.status} for agent run creation`,
    );
  }
  const agentRun = parseAgentRun(result.body);
  if (!agentRun) {
    return fail("malformed", "agent-runtime-service agent run response did not match the expected shape");
  }
  return ok(agentRun);
}

/**
 * Executes/continues the SAME durable LangGraph thread -- Gate A
 * re-confirmed this is the real, current, no-request-body contract
 * (`POST /api/v1/agent-runs/{run_id}/resume`; the backend does not
 * even bind a body model, so an empty object is sent purely to match
 * the proven acceptance scripts' own convention). Makes exactly ONE
 * POST per call -- never retries on an ambiguous failure (timeout,
 * network error, or a malformed response): without an idempotency
 * key, a blind retry could race a still-in-flight execution. The
 * caller (the resume Route Handler) is responsible for making at most
 * one call per browser request and for reconciling via a fresh GET
 * rather than retrying blindly.
 */
export async function resumeAgentRun(runId: string, actorToken?: string): Promise<BackendResult<AgentRun>> {
  const result = await postJson(
    `${AGENT_RUNTIME_URL}/api/v1/agent-runs/${encodeURIComponent(runId)}/resume`,
    {},
    actorAuthHeader(actorToken),
    RESUME_TIMEOUT_MS,
  );
  if ("networkError" in result) {
    return fail("unavailable", "agent-runtime-service unreachable, or the resume call timed out");
  }
  if (result.parseError) {
    return fail("malformed", "agent-runtime-service returned a non-JSON resume response");
  }
  if (result.status === 403) {
    return fail("forbidden", "the current user's role does not permit resuming this agent run");
  }
  if (result.status === 404) {
    return fail("not_found", "agent run not found");
  }
  if (result.status === 409) {
    return fail("conflict", "agent run is not in a resumable state, or approval is still pending");
  }
  if (result.status === 422) {
    return fail("validation", "invalid agent run identifier");
  }
  if (result.status === 503) {
    return fail("unavailable", "a dependency is temporarily unavailable; this agent run remains resumable");
  }
  if (result.status !== 200) {
    return fail("unavailable", `agent-runtime-service returned unexpected status ${result.status} for resume`);
  }
  const agentRun = parseAgentRun(result.body);
  if (!agentRun) {
    return fail("malformed", "agent-runtime-service resume response did not match the expected shape");
  }
  return ok(agentRun);
}

export async function getAgentRunHistory(
  runId: string,
  actorToken?: string,
): Promise<BackendResult<AgentRunHistory>> {
  const result = await getJson(
    `${AGENT_RUNTIME_URL}/api/v1/agent-runs/${encodeURIComponent(runId)}/history`,
    undefined,
    actorAuthHeader(actorToken),
  );
  if ("networkError" in result) {
    return fail("unavailable", "agent-runtime-service unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "agent-runtime-service returned a non-JSON agent run history response");
  }
  if (result.status === 404) {
    return fail("not_found", "agent run not found");
  }
  if (result.status === 422) {
    return fail("validation", "invalid agent run identifier");
  }
  if (result.status !== 200) {
    return fail(
      "unavailable",
      `agent-runtime-service returned unexpected status ${result.status} for agent run history`,
    );
  }
  const history = parseAgentRunHistory(result.body);
  if (!history) {
    return fail("malformed", "agent-runtime-service agent run history response did not match the expected shape");
  }
  return ok(history);
}
