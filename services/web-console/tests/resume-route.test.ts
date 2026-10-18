import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fail, ok } from "../lib/server/http";

vi.mock("../lib/server/agent-runtime-client", () => ({
  getAgentRun: vi.fn(),
  resumeAgentRun: vi.fn(),
}));
vi.mock("../lib/server/control-plane-client", () => ({
  getRemediationProposal: vi.fn(),
}));

import { POST } from "../app/api/agent-runs/[runId]/resume/route";
import { getAgentRun, resumeAgentRun } from "../lib/server/agent-runtime-client";
import { getRemediationProposal } from "../lib/server/control-plane-client";

const getAgentRunMock = getAgentRun as unknown as ReturnType<typeof vi.fn>;
const resumeAgentRunMock = resumeAgentRun as unknown as ReturnType<typeof vi.fn>;
const getRemediationProposalMock = getRemediationProposal as unknown as ReturnType<typeof vi.fn>;

const RUN_ID = "33333333-3333-3333-3333-333333333333";
const PROPOSAL_ID = "44444444-4444-4444-4444-444444444444";

function agentRunWith(overrides: Record<string, unknown>) {
  return {
    run_id: RUN_ID,
    thread_id: RUN_ID,
    incident_id: "22222222-2222-2222-2222-222222222222",
    status: "running",
    started_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    completed_at: null,
    current_node: "start",
    completed_nodes: [],
    incident_snapshot: null,
    investigation_report: null,
    result_quality: null,
    validation_notes: [],
    error_code: null,
    error_detail: null,
    resumable: true,
    remediation_proposal_id: null,
    remediation_action_type: null,
    remediation_target: null,
    remediation_status: null,
    execution_result: null,
    recovery_verification: null,
    ...overrides,
  };
}

function proposalWith(status: string) {
  return {
    id: PROPOSAL_ID,
    incident_id: "22222222-2222-2222-2222-222222222222",
    agent_run_id: RUN_ID,
    idempotency_key: "key-1",
    action_type: "restart_service",
    target: "checkout-service",
    reason: "high error rate",
    supporting_evidence_ids: [],
    supporting_context_ids: [],
    status,
    proposed_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    decided_at: null,
    decision_comment: null,
    execution_started_at: null,
    execution_completed_at: null,
  };
}

const TRUSTED_ORIGIN = "http://127.0.0.1:3101";

function callRoute(origin: string | null = TRUSTED_ORIGIN) {
  const headers: Record<string, string> = {};
  if (origin !== null) headers.Origin = origin;
  return POST(new Request("http://localhost/api/agent-runs/x/resume", { method: "POST", headers }), {
    params: Promise.resolve({ runId: RUN_ID }),
  });
}

beforeEach(() => {
  vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", TRUSTED_ORIGIN);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("POST /api/agent-runs/[runId]/resume", () => {
  it("valid running resumable run -> exactly one resume call, bounded response", async () => {
    getAgentRunMock.mockResolvedValue(ok(agentRunWith({})));
    const resumed = agentRunWith({ status: "running", current_node: "load_incident" });
    resumeAgentRunMock.mockResolvedValue(ok(resumed));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(resumeAgentRunMock).toHaveBeenCalledTimes(1);
    expect(resumeAgentRunMock).toHaveBeenCalledWith(RUN_ID);
    expect(Object.keys(body).sort()).toEqual(
      ["current_node", "remediation_proposal_id", "remediation_status", "resumable", "run_id", "status"].sort(),
    );
    expect(body.run_id).toBe(RUN_ID);
  });

  it("terminal run (resumable=false) -> no resume call, safe conflict", async () => {
    getAgentRunMock.mockResolvedValue(ok(agentRunWith({ status: "completed", resumable: false })));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(409);
    expect(body.error).toBe("conflict");
    expect(resumeAgentRunMock).not.toHaveBeenCalled();
  });

  it("waiting_for_approval + pending_approval proposal -> no resume call, safe conflict", async () => {
    getAgentRunMock.mockResolvedValue(
      ok(agentRunWith({ status: "waiting_for_approval", current_node: "await_human_approval", remediation_proposal_id: PROPOSAL_ID })),
    );
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith("pending_approval")));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(409);
    expect(body.error).toBe("conflict");
    expect(resumeAgentRunMock).not.toHaveBeenCalled();
  });

  it("waiting_for_approval + already-decided (approved) proposal -> resume is called", async () => {
    getAgentRunMock.mockResolvedValue(
      ok(agentRunWith({ status: "waiting_for_approval", current_node: "await_human_approval", remediation_proposal_id: PROPOSAL_ID })),
    );
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith("approved")));
    resumeAgentRunMock.mockResolvedValue(ok(agentRunWith({ status: "remediating", current_node: "execute_remediation" })));

    const response = await callRoute();

    expect(response.status).toBe(200);
    expect(resumeAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it("waiting_for_approval + already-decided (rejected) proposal -> resume is called", async () => {
    getAgentRunMock.mockResolvedValue(
      ok(agentRunWith({ status: "waiting_for_approval", current_node: "await_human_approval", remediation_proposal_id: PROPOSAL_ID })),
    );
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith("rejected")));
    resumeAgentRunMock.mockResolvedValue(ok(agentRunWith({ status: "completed", current_node: "finalize", resumable: false })));

    const response = await callRoute();

    expect(response.status).toBe(200);
    expect(resumeAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it("missing run -> 404, no resume call", async () => {
    getAgentRunMock.mockResolvedValue(fail("not_found", "agent run not found"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toBe("not_found");
    expect(resumeAgentRunMock).not.toHaveBeenCalled();
  });

  it("maps a resume-call failure safely, without a raw backend body", async () => {
    getAgentRunMock.mockResolvedValue(ok(agentRunWith({})));
    resumeAgentRunMock.mockResolvedValue(fail("unavailable", "agent-runtime-service unreachable, or the resume call timed out"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toBe("unavailable");
    expect(JSON.stringify(body)).not.toMatch(/unreachable|timed out/);
  });

  it("proposal fetch failure during pre-check is mapped safely, never silently resumed", async () => {
    getAgentRunMock.mockResolvedValue(
      ok(agentRunWith({ status: "waiting_for_approval", current_node: "await_human_approval", remediation_proposal_id: PROPOSAL_ID })),
    );
    getRemediationProposalMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toBe("unavailable");
    expect(resumeAgentRunMock).not.toHaveBeenCalled();
  });

  it("rejects a malformed run identifier before any backend call", async () => {
    const response = await POST(
      new Request("http://localhost/api/agent-runs/x/resume", { method: "POST", headers: { Origin: TRUSTED_ORIGIN } }),
      { params: Promise.resolve({ runId: "not-a-uuid" }) },
    );

    expect(response.status).toBe(422);
    expect(getAgentRunMock).not.toHaveBeenCalled();
    expect(resumeAgentRunMock).not.toHaveBeenCalled();
  });

  it("performs no automatic retry: exactly one resume call even when the result is ambiguous", async () => {
    getAgentRunMock.mockResolvedValue(ok(agentRunWith({})));
    resumeAgentRunMock.mockResolvedValue(fail("malformed", "agent-runtime-service resume response did not match the expected shape"));

    await callRoute();

    expect(resumeAgentRunMock).toHaveBeenCalledTimes(1);
  });

  describe("origin/CSRF guard", () => {
    it("rejects a missing Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute(null);
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getAgentRunMock).not.toHaveBeenCalled();
      expect(resumeAgentRunMock).not.toHaveBeenCalled();
    });

    it("rejects a cross-origin Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute("http://evil.example.com");
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getAgentRunMock).not.toHaveBeenCalled();
      expect(resumeAgentRunMock).not.toHaveBeenCalled();
    });

    it("never derives trust from Host/X-Forwarded-Host -- a spoofed forwarded-host with a cross-origin Origin is still rejected", async () => {
      const response = await POST(
        new Request("http://localhost/api/agent-runs/x/resume", {
          method: "POST",
          headers: { Origin: "http://evil.example.com", "X-Forwarded-Host": "127.0.0.1:3101" },
        }),
        { params: Promise.resolve({ runId: RUN_ID }) },
      );

      expect(response.status).toBe(403);
      expect(getAgentRunMock).not.toHaveBeenCalled();
    });

    it("allows a request carrying the exact trusted origin, preserving existing same-origin behavior", async () => {
      getAgentRunMock.mockResolvedValue(ok(agentRunWith({})));
      resumeAgentRunMock.mockResolvedValue(ok(agentRunWith({ status: "running", current_node: "load_incident" })));

      const response = await callRoute(TRUSTED_ORIGIN);

      expect(response.status).toBe(200);
      expect(resumeAgentRunMock).toHaveBeenCalledTimes(1);
    });
  });
});
