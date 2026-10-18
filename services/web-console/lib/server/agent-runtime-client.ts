import "server-only";

import { type BackendResult, fail, getJson, ok, postJson } from "./http";
import { parseAgentRun, parseAgentRunHistory } from "./agent-run-validation";
import type { AgentRun, AgentRunHistory } from "../types/agent-run";

const AGENT_RUNTIME_URL = process.env.WEB_CONSOLE_AGENT_RUNTIME_URL ?? "http://agent-runtime-service:8003";

export async function getAgentRun(runId: string): Promise<BackendResult<AgentRun>> {
  const result = await getJson(`${AGENT_RUNTIME_URL}/api/v1/agent-runs/${encodeURIComponent(runId)}`);
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
export async function createAgentRun(incidentId: string): Promise<BackendResult<AgentRun>> {
  const result = await postJson(`${AGENT_RUNTIME_URL}/api/v1/agent-runs`, { incident_id: incidentId });
  if ("networkError" in result) {
    return fail("unavailable", "agent-runtime-service unreachable");
  }
  if (result.parseError) {
    return fail("malformed", "agent-runtime-service returned a non-JSON agent run response");
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

export async function getAgentRunHistory(runId: string): Promise<BackendResult<AgentRunHistory>> {
  const result = await getJson(`${AGENT_RUNTIME_URL}/api/v1/agent-runs/${encodeURIComponent(runId)}/history`);
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
