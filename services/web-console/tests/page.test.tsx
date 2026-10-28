import { render, screen } from "@testing-library/react";
import { APIError } from "better-auth";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ok, fail } from "../lib/server/http";

// Phase 15: the dashboard replaces the old static placeholder home
// page -- real, bounded backend data (control-plane's own
// GET /api/v1/dashboard/summary) replaces the hardcoded "planned
// sections" list the old version of this test exercised.
vi.mock("../lib/server/control-plane-client", () => ({
  getDashboardSummary: vi.fn(),
}));
vi.mock("../lib/server/service-client", () => ({
  listServices: vi.fn(),
}));
vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers()),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));
vi.mock("@/lib/auth/auth", () => ({
  auth: { api: { getSession: vi.fn(), getActiveMember: vi.fn() } },
}));

import DashboardPage from "../app/page";
import { auth } from "@/lib/auth/auth";
import { getDashboardSummary } from "../lib/server/control-plane-client";
import { listServices } from "../lib/server/service-client";
import { redirect } from "next/navigation";

const getDashboardSummaryMock = getDashboardSummary as unknown as ReturnType<typeof vi.fn>;
const listServicesMock = listServices as unknown as ReturnType<typeof vi.fn>;
const getSessionMock = auth.api.getSession as unknown as ReturnType<typeof vi.fn>;
const getActiveMemberMock = auth.api.getActiveMember as unknown as ReturnType<typeof vi.fn>;
const redirectMock = redirect as unknown as ReturnType<typeof vi.fn>;
void redirectMock;

const ACTOR_USER_ID = "88888888-8888-8888-8888-888888888888";
const ACTOR_ORG_ID = "99999999-9999-9999-9999-999999999999";

function mockAuthenticatedActor(role = "OWNER") {
  getSessionMock.mockResolvedValue({
    user: { id: ACTOR_USER_ID },
    session: { activeOrganizationId: ACTOR_ORG_ID },
  });
  getActiveMemberMock.mockResolvedValue({
    id: "member-1",
    userId: ACTOR_USER_ID,
    organizationId: ACTOR_ORG_ID,
    role,
  });
}

function mockNoSession() {
  getSessionMock.mockResolvedValue({ user: null });
}

function mockRevokedMember() {
  getSessionMock.mockResolvedValue({
    user: { id: ACTOR_USER_ID },
    session: { activeOrganizationId: ACTOR_ORG_ID },
  });
  getActiveMemberMock.mockRejectedValue(
    APIError.from("BAD_REQUEST", { code: "MEMBER_NOT_FOUND", message: "Member not found" }),
  );
}

beforeEach(() => {
  mockAuthenticatedActor();
  listServicesMock.mockResolvedValue(ok({ items: [], total: 0, limit: 1, offset: 0 }));
});

const EMPTY_SUMMARY = {
  generated_at: "2026-01-01T00:00:00+00:00",
  counts: { open: 0, acknowledged: 0, investigating: 0, remediating: 0, resolved: 0, closed: 0, active_critical: 0 },
  pending_approvals_count: 0,
  attention_incidents: [],
  pending_approvals: [],
  activity: [{ day: "2026-01-01", critical: 0, warning: 0, info: 0 }],
  recent_events: [],
};

describe("DashboardPage", () => {
  // Independent-review correction round, BLOCKER 3 bug C: zero
  // incidents is never proof of production health when no customer
  // telemetry is connected -- the badge must state the narrower,
  // honest fact this data actually supports, never "healthy"/"all
  // clear".
  it("renders a real heading and the honest zero-incident state for an empty organization", async () => {
    getDashboardSummaryMock.mockResolvedValue(ok(EMPTY_SUMMARY));

    const jsx = await DashboardPage();
    render(jsx);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeDefined();
    expect(screen.getByText("No active incidents recorded")).toBeDefined();
    expect(screen.queryByText("All clear")).toBeNull();
    expect(screen.getByText("Nothing needs attention right now")).toBeDefined();
    expect(screen.getByText("No services registered yet.")).toBeDefined();
  });

  it("renders real, non-fabricated counts and surfaces a pending approval with a working link", async () => {
    getDashboardSummaryMock.mockResolvedValue(
      ok({
        ...EMPTY_SUMMARY,
        counts: { ...EMPTY_SUMMARY.counts, open: 2, investigating: 1, active_critical: 1 },
        pending_approvals_count: 1,
        pending_approvals: [
          {
            proposal_id: "p1",
            incident_id: "i1",
            agent_run_id: "r1",
            incident_title: "checkout-service is returning HTTP 5xx errors",
            incident_severity: "critical",
            action_type: "clear_payment_authorization_fault",
            target: "payment-service",
            proposed_at: "2026-01-01T00:00:00+00:00",
          },
        ],
      }),
    );

    const jsx = await DashboardPage();
    render(jsx);

    expect(screen.getByText("Critical attention needed")).toBeDefined();
    // Independent-review correction round, BLOCKER 3 bug A: this is a
    // real incident-status count, relabeled to say exactly that --
    // never implied to be a count of active AI investigation runs.
    expect(screen.getByText("Incidents being investigated").previousSibling?.textContent).toBe("1");
    const approvalLink = screen.getByText(/Approval needed: clear_payment_authorization_fault/).closest("a");
    expect(approvalLink?.getAttribute("href")).toBe("/agent-runs/r1");
  });

  // Independent-review correction round, BLOCKER 3 bug B: the metric
  // card must reflect the backend's real, unbounded count -- not
  // len(pending_approvals), which the backend itself caps at 8 for
  // display purposes. This test deliberately gives the two different
  // values (12 real vs. 8 displayed) and asserts the CARD shows 12.
  it("shows the real total pending-approval count even when more than 8 are pending", async () => {
    const approvals = Array.from({ length: 8 }, (_, i) => ({
      proposal_id: `p${i}`,
      incident_id: `i${i}`,
      agent_run_id: `r${i}`,
      incident_title: `incident ${i}`,
      incident_severity: "warning" as const,
      action_type: "restart_pod",
      target: `service-${i}`,
      proposed_at: "2026-01-01T00:00:00+00:00",
    }));
    getDashboardSummaryMock.mockResolvedValue(
      ok({
        ...EMPTY_SUMMARY,
        pending_approvals_count: 12,
        pending_approvals: approvals,
      }),
    );

    const jsx = await DashboardPage();
    render(jsx);

    expect(screen.getByText("Pending approvals").previousSibling?.textContent).toBe("12");
  });

  it("shows a professional failure state, never a fabricated empty dashboard, when control-plane is unavailable", async () => {
    getDashboardSummaryMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const jsx = await DashboardPage();
    render(jsx);

    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
    expect(screen.queryByText("All clear")).toBeNull();
  });

  describe("real actor resolution (Phase 14 Gate 9)", () => {
    it("no session at all -> redirected to sign-in, never rendered unscoped", async () => {
      mockNoSession();

      await expect(DashboardPage()).rejects.toThrow("NEXT_REDIRECT:/sign-in");
      expect(getDashboardSummaryMock).not.toHaveBeenCalled();
    });

    it("a revoked/removed member's still-valid session -> redirected to /organizations, never rendered", async () => {
      mockRevokedMember();

      await expect(DashboardPage()).rejects.toThrow("NEXT_REDIRECT:/organizations");
      expect(getDashboardSummaryMock).not.toHaveBeenCalled();
    });
  });
});
