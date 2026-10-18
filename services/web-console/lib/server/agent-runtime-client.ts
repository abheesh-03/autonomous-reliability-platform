import "server-only";

import { type BackendResult, fail, getJson, ok } from "./http";
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
