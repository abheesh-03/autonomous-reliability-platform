import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fail, ok } from "../lib/server/http";

vi.mock("../lib/server/control-plane-client", () => ({
  getIncident: vi.fn(),
  getAllIncidentEvents: vi.fn(),
  getAllIncidentRemediationProposals: vi.fn(),
  getAllRemediationProposalEvents: vi.fn(),
}));
// StartInvestigationControl (rendered for open/acknowledged/investigating
// incidents) calls useRouter() -- needs a router context stub to render
// under Vitest/jsdom, same as agent-run-page.test.tsx/start-investigation-control.test.tsx.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import IncidentDetailPage from "../app/incidents/[incidentId]/page";
import {
  getAllIncidentEvents,
  getAllIncidentRemediationProposals,
  getAllRemediationProposalEvents,
  getIncident,
} from "../lib/server/control-plane-client";

const getIncidentMock = getIncident as unknown as ReturnType<typeof vi.fn>;
const getAllIncidentEventsMock = getAllIncidentEvents as unknown as ReturnType<typeof vi.fn>;
const getAllIncidentRemediationProposalsMock = getAllIncidentRemediationProposals as unknown as ReturnType<
  typeof vi.fn
>;
const getAllRemediationProposalEventsMock = getAllRemediationProposalEvents as unknown as ReturnType<typeof vi.fn>;

const SAMPLE_INCIDENT = {
  id: "11111111-1111-1111-1111-111111111111",
  source: "alertmanager",
  source_fingerprint: "abc123",
  title: "checkout-service is returning HTTP 5xx errors",
  description: "real downstream payment failures",
  severity: "critical",
  status: "resolved",
  first_seen_at: "2026-01-01T00:00:00+00:00",
  last_seen_at: "2026-01-01T00:05:00+00:00",
  resolved_at: "2026-01-01T00:10:00+00:00",
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:10:00+00:00",
};

const SAMPLE_EVENT = {
  id: 1,
  incident_id: SAMPLE_INCIDENT.id,
  event_type: "created",
  actor_type: "alertmanager",
  previous_status: null,
  new_status: "open",
  occurred_at: "2026-01-01T00:00:00+00:00",
  metadata: {},
};

function makeProposal(id: string) {
  return {
    id,
    incident_id: SAMPLE_INCIDENT.id,
    agent_run_id: "33333333-3333-3333-3333-333333333333",
    idempotency_key: `k-${id}`,
    action_type: "clear_payment_authorization_fault",
    target: "payment-service",
    reason: "clear the controlled fault",
    supporting_evidence_ids: [],
    supporting_context_ids: [],
    status: "succeeded",
    proposed_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    decided_at: "2026-01-01T00:01:00+00:00",
    decision_comment: null,
    execution_started_at: "2026-01-01T00:02:00+00:00",
    execution_completed_at: "2026-01-01T00:03:00+00:00",
  };
}

describe("IncidentDetailPage", () => {
  it("renders incident metadata and the real audit timeline", async () => {
    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([SAMPLE_EVENT]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([]));

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    expect(screen.getByRole("heading", { name: SAMPLE_INCIDENT.title })).toBeDefined();
    expect(screen.getByText("created")).toBeDefined();
    expect(screen.getByText(/open/)).toBeDefined();
  });

  it("never invents remediation data when no proposal exists", async () => {
    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([]));

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    expect(screen.getByText(/no remediation proposal exists/i)).toBeDefined();
    expect(getAllRemediationProposalEventsMock).not.toHaveBeenCalled();
  });

  it("renders a real proposal's own event history, preserving order", async () => {
    const proposal = {
      id: "22222222-2222-2222-2222-222222222222",
      incident_id: SAMPLE_INCIDENT.id,
      agent_run_id: "33333333-3333-3333-3333-333333333333",
      idempotency_key: "k1",
      action_type: "clear_payment_authorization_fault",
      target: "payment-service",
      reason: "clear the controlled fault",
      supporting_evidence_ids: [],
      supporting_context_ids: [],
      status: "succeeded",
      proposed_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
      decided_at: "2026-01-01T00:01:00+00:00",
      decision_comment: null,
      execution_started_at: "2026-01-01T00:02:00+00:00",
      execution_completed_at: "2026-01-01T00:03:00+00:00",
    };
    const proposalEvents = [
      { id: 1, proposal_id: proposal.id, event_type: "proposed", actor_type: "agent", occurred_at: "2026-01-01T00:00:00+00:00", metadata: {} },
      { id: 2, proposal_id: proposal.id, event_type: "approved", actor_type: "operator", occurred_at: "2026-01-01T00:01:00+00:00", metadata: {} },
    ];

    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([proposal]));
    getAllRemediationProposalEventsMock.mockResolvedValue(ok(proposalEvents));

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    expect(screen.getByText("clear_payment_authorization_fault")).toBeDefined();
    const renderedText = document.body.textContent ?? "";
    expect(renderedText.indexOf("proposed")).toBeLessThan(renderedText.indexOf("approved"));

    // The proposal's own real agent_run_id is linked, read-only -- no
    // new discovery API, no mutation.
    const viewRunLink = screen.getByText("View agent run").closest("a");
    expect(viewRunLink?.getAttribute("href")).toBe(`/agent-runs/${proposal.agent_run_id}`);
  });

  it("represents a proposal's genuinely empty event history as empty, not as a failure", async () => {
    const proposal = makeProposal("22222222-2222-2222-2222-222222222222");

    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([proposal]));
    getAllRemediationProposalEventsMock.mockResolvedValue(ok([]));

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    expect(screen.getByText(/no remediation events recorded/i)).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders a failure state for a proposal whose event history fetch failed, distinct from a genuinely empty history", async () => {
    const proposal = makeProposal("22222222-2222-2222-2222-222222222222");

    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([proposal]));
    getAllRemediationProposalEventsMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
    expect(screen.queryByText(/no remediation events recorded/i)).toBeNull();
  });

  it("a failed event-history fetch for one proposal never hides another proposal's own valid events", async () => {
    const failingProposal = makeProposal("22222222-2222-2222-2222-222222222222");
    const healthyProposal = makeProposal("44444444-4444-4444-4444-444444444444");
    const healthyEvents = [
      {
        id: 9,
        proposal_id: healthyProposal.id,
        event_type: "proposed",
        actor_type: "agent",
        occurred_at: "2026-01-01T00:00:00+00:00",
        metadata: {},
      },
    ];

    getIncidentMock.mockResolvedValue(ok(SAMPLE_INCIDENT));
    getAllIncidentEventsMock.mockResolvedValue(ok([SAMPLE_EVENT]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([failingProposal, healthyProposal]));
    getAllRemediationProposalEventsMock.mockImplementation(async (proposalId: string) =>
      proposalId === failingProposal.id ? fail("unavailable", "control-plane unreachable") : ok(healthyEvents),
    );

    const jsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(jsx);

    // The incident itself and its own audit timeline are unaffected.
    expect(screen.getByRole("heading", { name: SAMPLE_INCIDENT.title })).toBeDefined();
    expect(screen.getByText("created")).toBeDefined();

    // Exactly one failure state is shown (the failing proposal's own),
    // and the healthy proposal's own real event is still rendered.
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText(/proposed \(agent\)/)).toBeDefined();
  });

  it("17. shows the Start control for an eligible (open) incident, and no normal Start control for a resolved one", async () => {
    getAllIncidentEventsMock.mockResolvedValue(ok([]));
    getAllIncidentRemediationProposalsMock.mockResolvedValue(ok([]));

    getIncidentMock.mockResolvedValue(ok({ ...SAMPLE_INCIDENT, status: "open" }));
    const openJsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    const { unmount } = render(openJsx);
    expect(screen.getByRole("button", { name: /start ai investigation/i })).toBeDefined();
    unmount();

    getIncidentMock.mockResolvedValue(ok({ ...SAMPLE_INCIDENT, status: "resolved" }));
    const resolvedJsx = await IncidentDetailPage({ params: Promise.resolve({ incidentId: SAMPLE_INCIDENT.id }) });
    render(resolvedJsx);
    expect(screen.queryByRole("button", { name: /investigation/i })).toBeNull();
    expect(screen.getByText(/cannot be started while the incident is resolved/i)).toBeDefined();
  });
});
