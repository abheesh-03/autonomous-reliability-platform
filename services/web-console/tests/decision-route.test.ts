import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fail, ok } from "../lib/server/http";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

vi.mock("../lib/server/control-plane-client", () => ({
  decideRemediationProposal: vi.fn(),
  getRemediationProposal: vi.fn(),
}));

import { POST } from "../app/api/remediation-proposals/[proposalId]/decision/route";
import { decideRemediationProposal, getRemediationProposal } from "../lib/server/control-plane-client";

const getRemediationProposalMock = getRemediationProposal as unknown as ReturnType<typeof vi.fn>;
const decideRemediationProposalMock = decideRemediationProposal as unknown as ReturnType<typeof vi.fn>;

const PROPOSAL_ID = "44444444-4444-4444-4444-444444444444";
const INCIDENT_ID = "22222222-2222-2222-2222-222222222222";

function proposalWith(overrides: Record<string, unknown>) {
  return {
    id: PROPOSAL_ID,
    incident_id: INCIDENT_ID,
    agent_run_id: "33333333-3333-3333-3333-333333333333",
    idempotency_key: "key-1",
    action_type: "restart_service",
    target: "checkout-service",
    reason: "high error rate",
    supporting_evidence_ids: [],
    supporting_context_ids: [],
    status: "pending_approval",
    proposed_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    decided_at: null,
    decision_comment: null,
    execution_started_at: null,
    execution_completed_at: null,
    ...overrides,
  };
}

const TRUSTED_ORIGIN = "http://127.0.0.1:3101";

function callRoute(body: unknown, origin: string | null = TRUSTED_ORIGIN) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (origin !== null) headers.Origin = origin;
  return POST(
    new Request("http://localhost/api/remediation-proposals/x/decision", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ proposalId: PROPOSAL_ID }) },
  );
}

beforeEach(() => {
  vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", TRUSTED_ORIGIN);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("POST /api/remediation-proposals/[proposalId]/decision", () => {
  it("pending_approval + approve: derives expected_status from a fresh read, calls decide exactly once, returns bounded response", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
    decideRemediationProposalMock.mockResolvedValue(
      ok(proposalWith({ status: "approved", decided_at: "2026-01-01T00:05:00+00:00" })),
    );

    const response = await callRoute({ decision: "approve", comment: "looks safe" });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(decideRemediationProposalMock).toHaveBeenCalledTimes(1);
    expect(decideRemediationProposalMock).toHaveBeenCalledWith(PROPOSAL_ID, "pending_approval", "approve", "looks safe");
    expect(body).toEqual({
      id: PROPOSAL_ID,
      status: "approved",
      decided_at: "2026-01-01T00:05:00+00:00",
      decision_comment: null,
      incident_id: INCIDENT_ID,
    });
  });

  it("pending_approval + reject: calls decide exactly once with decision=reject", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
    decideRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "rejected" })));

    const response = await callRoute({ decision: "reject" });

    expect(response.status).toBe(200);
    expect(decideRemediationProposalMock).toHaveBeenCalledWith(PROPOSAL_ID, "pending_approval", "reject", undefined);
  });

  it("a stale/illegal transition reported by the backend is a safe conflict, never retried", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "approved" })));
    decideRemediationProposalMock.mockResolvedValue(fail("conflict", "the proposal's status changed"));

    const response = await callRoute({ decision: "approve" });
    const body = await response.json();

    expect(response.status).toBe(409);
    expect(body.error).toBe("conflict");
    expect(decideRemediationProposalMock).toHaveBeenCalledTimes(1);
  });

  it("missing proposal -> 404, no decide call", async () => {
    getRemediationProposalMock.mockResolvedValue(fail("not_found", "remediation proposal not found"));

    const response = await callRoute({ decision: "approve" });
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toBe("not_found");
    expect(decideRemediationProposalMock).not.toHaveBeenCalled();
  });

  it("rejects a comment over the 1000-character bound before any backend call", async () => {
    const response = await callRoute({ decision: "approve", comment: "x".repeat(1001) });
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body.error).toBe("validation");
    expect(getRemediationProposalMock).not.toHaveBeenCalled();
    expect(decideRemediationProposalMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid decision value before any backend call", async () => {
    const response = await callRoute({ decision: "maybe" });

    expect(response.status).toBe(422);
    expect(getRemediationProposalMock).not.toHaveBeenCalled();
    expect(decideRemediationProposalMock).not.toHaveBeenCalled();
  });

  it("rejects a browser-supplied expected_status field entirely -- it is never read, only decision/comment are used", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
    decideRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "approved" })));

    await callRoute({ decision: "approve", expected_status: "executing" });

    // The call always uses the server's OWN fresh read ("pending_approval"
    // from the mock above), never the attacker/stale-client-controlled
    // "executing" value that was smuggled into the request body.
    expect(decideRemediationProposalMock).toHaveBeenCalledWith(PROPOSAL_ID, "pending_approval", "approve", undefined);
  });

  it("rejects a malformed proposal identifier before any backend call", async () => {
    const response = await POST(
      new Request("http://localhost/api/remediation-proposals/x/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: TRUSTED_ORIGIN },
        body: JSON.stringify({ decision: "approve" }),
      }),
      { params: Promise.resolve({ proposalId: "not-a-uuid" }) },
    );

    expect(response.status).toBe(422);
    expect(getRemediationProposalMock).not.toHaveBeenCalled();
  });

  it("never calls resumeAgentRun or anything resembling /resume -- decision and resume stay separate requests", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
    decideRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "approved" })));

    const routeSource = readFileSync(
      join(ROOT, "app/api/remediation-proposals/[proposalId]/decision/route.ts"),
      "utf-8",
    );
    const nonCommentSource = routeSource
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");
    expect(nonCommentSource).not.toMatch(/resumeAgentRun/);
    expect(nonCommentSource).not.toMatch(/\/resume/);

    await callRoute({ decision: "approve" });
  });

  it("performs no automatic retry: exactly one decide call even on an ambiguous/malformed failure", async () => {
    getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
    decideRemediationProposalMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    await callRoute({ decision: "approve" });

    expect(decideRemediationProposalMock).toHaveBeenCalledTimes(1);
  });

  describe("origin/CSRF guard", () => {
    it("rejects a missing Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute({ decision: "approve" }, null);
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getRemediationProposalMock).not.toHaveBeenCalled();
      expect(decideRemediationProposalMock).not.toHaveBeenCalled();
    });

    it("rejects a cross-origin Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute({ decision: "approve" }, "http://evil.example.com");
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getRemediationProposalMock).not.toHaveBeenCalled();
      expect(decideRemediationProposalMock).not.toHaveBeenCalled();
    });

    it("never derives trust from Host/X-Forwarded-Host -- a spoofed forwarded-host with a cross-origin Origin is still rejected", async () => {
      const response = await POST(
        new Request("http://localhost/api/remediation-proposals/x/decision", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Origin: "http://evil.example.com",
            "X-Forwarded-Host": "127.0.0.1:3101",
          },
          body: JSON.stringify({ decision: "approve" }),
        }),
        { params: Promise.resolve({ proposalId: PROPOSAL_ID }) },
      );

      expect(response.status).toBe(403);
      expect(getRemediationProposalMock).not.toHaveBeenCalled();
    });

    it("allows a request carrying the exact trusted origin, preserving existing same-origin behavior", async () => {
      getRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "pending_approval" })));
      decideRemediationProposalMock.mockResolvedValue(ok(proposalWith({ status: "approved" })));

      const response = await callRoute({ decision: "approve" }, TRUSTED_ORIGIN);

      expect(response.status).toBe(200);
      expect(decideRemediationProposalMock).toHaveBeenCalledTimes(1);
    });
  });
});
