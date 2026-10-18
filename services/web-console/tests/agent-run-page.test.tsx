import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fail, ok } from "../lib/server/http";

vi.mock("../lib/server/agent-runtime-client", () => ({
  getAgentRun: vi.fn(),
  getAgentRunHistory: vi.fn(),
}));
vi.mock("../lib/server/control-plane-client", () => ({
  getRemediationProposal: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

import AgentRunPage from "../app/agent-runs/[runId]/page";
import { getAgentRun, getAgentRunHistory } from "../lib/server/agent-runtime-client";
import { getRemediationProposal } from "../lib/server/control-plane-client";
import { notFound } from "next/navigation";

const getAgentRunMock = getAgentRun as unknown as ReturnType<typeof vi.fn>;
const getAgentRunHistoryMock = getAgentRunHistory as unknown as ReturnType<typeof vi.fn>;
const getRemediationProposalMock = getRemediationProposal as unknown as ReturnType<typeof vi.fn>;
const notFoundMock = notFound as unknown as ReturnType<typeof vi.fn>;

const BASE_AGENT_RUN = {
  run_id: "11111111-1111-1111-1111-111111111111",
  thread_id: "11111111-1111-1111-1111-111111111111",
  incident_id: "22222222-2222-2222-2222-222222222222",
  status: "running" as const,
  started_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:05:00+00:00",
  completed_at: null,
  current_node: "run_investigation",
  completed_nodes: ["load_incident"],
  incident_snapshot: {
    id: "22222222-2222-2222-2222-222222222222",
    source: "alertmanager",
    source_fingerprint: "abc",
    title: "checkout-service is returning HTTP 5xx errors",
    description: null,
    severity: "critical" as const,
    status: "investigating" as const,
    first_seen_at: "2026-01-01T00:00:00+00:00",
    last_seen_at: "2026-01-01T00:00:00+00:00",
    resolved_at: null,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
  },
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
};

const SAMPLE_REPORT = {
  incident_id: BASE_AGENT_RUN.incident_id,
  investigated_at: "2026-01-01T00:04:00+00:00",
  incident_status_at_investigation: "investigating",
  summary: "checkout-service experienced a dependency failure.",
  observations: [{ statement: "payment-service returned 5xx", evidence_ids: ["ev-1"] }],
  hypotheses: [
    {
      statement: "payment-service outage caused the failures",
      supporting_evidence_ids: ["ev-1"],
      conflicting_evidence_ids: [],
      supporting_context_ids: [],
      conflicting_context_ids: [],
      confidence: "high",
    },
  ],
  missing_evidence: [],
  suggested_checks: [],
  evidence: [
    {
      id: "ev-1",
      source: "prometheus",
      observed_at: "2026-01-01T00:03:00+00:00",
      window_start: null,
      window_end: null,
      summary: "CheckoutServerErrors firing",
      detail: "rate() > 0 over 5m",
      reference: {},
    },
  ],
  source_outcomes: [{ source: "prometheus", status: "ok", detail: "query succeeded", query_summary: null }],
  retrieval_context: {
    knowledge: [
      {
        context_id: "ctx-1",
        source_type: "knowledge",
        source_key: "runbooks/checkout-5xx.md",
        title: "Checkout 5xx runbook",
        excerpt: "Check payment-service health first.",
        similarity: 0.87,
        metadata: {},
        embedding_space: "local-lexical-v1",
      },
    ],
    historical_incidents: [],
    outcome: "ok",
    detail: "",
  },
  provider: { configured: true, provider: "openai", model: "gpt-4o-mini" },
  validation_notes: [],
};

describe("AgentRunPage", () => {
  it("renders the running state, completed nodes, current node, and incident snapshot", async () => {
    getAgentRunMock.mockResolvedValue(ok(BASE_AGENT_RUN));
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByText("running")).toBeDefined();
    expect(screen.getByText("load_incident")).toBeDefined();
    expect(screen.getByText("run_investigation (current)")).toBeDefined();
    expect(screen.getByText(BASE_AGENT_RUN.incident_snapshot.title)).toBeDefined();
  });

  it("renders investigation report evidence and provenance", async () => {
    getAgentRunMock.mockResolvedValue(ok({ ...BASE_AGENT_RUN, investigation_report: SAMPLE_REPORT, result_quality: "well_supported" }));
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByText(SAMPLE_REPORT.summary)).toBeDefined();
    expect(screen.getByText("payment-service outage caused the failures")).toBeDefined();
    expect(screen.getByText(/CheckoutServerErrors firing/)).toBeDefined();
    expect(screen.getByText(/well_supported/)).toBeDefined();
  });

  it("renders retrieval/RAG context from the report without calling retrieval-service", async () => {
    getAgentRunMock.mockResolvedValue(ok({ ...BASE_AGENT_RUN, investigation_report: SAMPLE_REPORT }));
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByText("Checkout 5xx runbook")).toBeDefined();
    expect(screen.getByText(/similarity 0.870/)).toBeDefined();
  });

  it("renders waiting_for_approval as a real read-only wait state, never resolved/approved", async () => {
    getAgentRunMock.mockResolvedValue(
      ok({
        ...BASE_AGENT_RUN,
        status: "waiting_for_approval",
        remediation_proposal_id: "33333333-3333-3333-3333-333333333333",
        remediation_action_type: "clear_payment_authorization_fault",
        remediation_target: "payment-service",
        remediation_status: "pending_approval",
      }),
    );
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));
    getRemediationProposalMock.mockResolvedValue(
      ok({
        id: "33333333-3333-3333-3333-333333333333",
        incident_id: BASE_AGENT_RUN.incident_id,
        agent_run_id: BASE_AGENT_RUN.run_id,
        idempotency_key: "k1",
        action_type: "clear_payment_authorization_fault",
        target: "payment-service",
        reason: "clear the controlled fault",
        supporting_evidence_ids: [],
        supporting_context_ids: [],
        status: "pending_approval",
        proposed_at: "2026-01-01T00:05:00+00:00",
        updated_at: "2026-01-01T00:05:00+00:00",
        decided_at: null,
        decision_comment: null,
        execution_started_at: null,
        execution_completed_at: null,
      }),
    );

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByRole("status").textContent).toMatch(/waiting for human approval/i);
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /reject/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume/i })).toBeNull();
  });

  it("renders remediation proposal state when a proposal exists", async () => {
    getAgentRunMock.mockResolvedValue(
      ok({
        ...BASE_AGENT_RUN,
        status: "completed",
        remediation_proposal_id: "33333333-3333-3333-3333-333333333333",
        remediation_action_type: "clear_payment_authorization_fault",
        remediation_target: "payment-service",
        remediation_status: "succeeded",
      }),
    );
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));
    getRemediationProposalMock.mockResolvedValue(
      ok({
        id: "33333333-3333-3333-3333-333333333333",
        incident_id: BASE_AGENT_RUN.incident_id,
        agent_run_id: BASE_AGENT_RUN.run_id,
        idempotency_key: "k1",
        action_type: "clear_payment_authorization_fault",
        target: "payment-service",
        reason: "clear the controlled fault",
        supporting_evidence_ids: [],
        supporting_context_ids: [],
        status: "succeeded",
        proposed_at: "2026-01-01T00:05:00+00:00",
        updated_at: "2026-01-01T00:06:00+00:00",
        decided_at: "2026-01-01T00:05:30+00:00",
        decision_comment: null,
        execution_started_at: "2026-01-01T00:05:45+00:00",
        execution_completed_at: "2026-01-01T00:06:00+00:00",
      }),
    );

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByText("clear the controlled fault")).toBeDefined();
    expect(screen.getByText("clear_payment_authorization_fault")).toBeDefined();
  });

  it("renders execution result when present", async () => {
    getAgentRunMock.mockResolvedValue(
      ok({
        ...BASE_AGENT_RUN,
        status: "completed",
        remediation_proposal_id: "33333333-3333-3333-3333-333333333333",
        remediation_status: "succeeded",
        execution_result: { status: "succeeded", detail: null },
      }),
    );
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));
    getRemediationProposalMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    const executionParagraph = screen.getByText(/Execution:/).closest("p");
    expect(executionParagraph?.textContent).toMatch(/succeeded/);
  });

  it("renders recovery verification checks when present", async () => {
    getAgentRunMock.mockResolvedValue(
      ok({
        ...BASE_AGENT_RUN,
        status: "completed",
        recovery_verification: { proposal_succeeded: true, fault_inactive: true, target_healthy: false },
      }),
    );
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    expect(screen.getByText(/Proposal succeeded/)).toBeDefined();
    expect(screen.getByText(/Target healthy/)).toBeDefined();
  });

  it("renders safe error/resumability information for a failed run", async () => {
    getAgentRunMock.mockResolvedValue(
      ok({
        ...BASE_AGENT_RUN,
        status: "failed",
        resumable: false,
        error_code: "investigator_unavailable",
        error_detail: "investigator-service returned an unexpected response",
      }),
    );
    getAgentRunHistoryMock.mockResolvedValue(ok({ run_id: BASE_AGENT_RUN.run_id, thread_id: BASE_AGENT_RUN.thread_id, entries: [] }));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/investigator_unavailable/);
    expect(alert.textContent).toMatch(/not resumable/i);
  });

  it("calls notFound for a missing run", async () => {
    getAgentRunMock.mockResolvedValue(fail("not_found", "agent run not found"));

    await expect(
      AgentRunPage({ params: Promise.resolve({ runId: "00000000-0000-0000-0000-000000000000" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("keeps the AgentRun visible with a scoped failure when history fails", async () => {
    getAgentRunMock.mockResolvedValue(ok(BASE_AGENT_RUN));
    getAgentRunHistoryMock.mockResolvedValue(fail("unavailable", "agent-runtime-service unreachable"));

    const jsx = await AgentRunPage({ params: Promise.resolve({ runId: BASE_AGENT_RUN.run_id }) });
    render(jsx);

    // The run itself still renders in full.
    expect(screen.getByText("running")).toBeDefined();
    expect(screen.getByText(BASE_AGENT_RUN.incident_snapshot.title)).toBeDefined();
    // Only the checkpoint-history section shows the failure.
    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
  });
});
