import { render, screen, within } from "@testing-library/react";
import { APIError } from "better-auth";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ok, fail } from "../lib/server/http";

vi.mock("../lib/server/control-plane-client", () => ({
  listIncidents: vi.fn(),
}));
// Phase 14 correction round: only the Next.js/Better-Auth PLUMBING is
// mocked here -- lib/server/actor.ts's own resolveActor/
// requireActorOrRedirect run for REAL against these, so a test
// simulating "no session"/"revoked member" exercises the actual
// authorization decision, not a stubbed-out tautology.
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

import IncidentsPage from "../app/incidents/page";
import { auth } from "@/lib/auth/auth";
import { listIncidents } from "../lib/server/control-plane-client";
import { redirect } from "next/navigation";

const listIncidentsMock = listIncidents as unknown as ReturnType<typeof vi.fn>;
const getSessionMock = auth.api.getSession as unknown as ReturnType<typeof vi.fn>;
const getActiveMemberMock = auth.api.getActiveMember as unknown as ReturnType<typeof vi.fn>;
const redirectMock = redirect as unknown as ReturnType<typeof vi.fn>;

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

function mockSessionNoActiveOrg() {
  getSessionMock.mockResolvedValue({ user: { id: ACTOR_USER_ID }, session: { activeOrganizationId: null } });
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
});

const SAMPLE_INCIDENT = {
  id: "11111111-1111-1111-1111-111111111111",
  source: "alertmanager",
  source_fingerprint: "abc123",
  title: "checkout-service is returning HTTP 5xx errors",
  description: null,
  severity: "critical",
  status: "open",
  first_seen_at: "2026-01-01T00:00:00+00:00",
  last_seen_at: "2026-01-01T00:05:00+00:00",
  resolved_at: null,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:05:00+00:00",
};

describe("IncidentsPage", () => {
  it("renders real-shaped incident data from the client", async () => {
    listIncidentsMock.mockResolvedValue(ok({ items: [SAMPLE_INCIDENT], total: 1, limit: 20, offset: 0 }));

    const jsx = await IncidentsPage({ searchParams: Promise.resolve({}) });
    render(jsx);

    const row = screen.getByText(SAMPLE_INCIDENT.title).closest("tr");
    expect(row).not.toBeNull();
    const rowScope = within(row as HTMLElement);
    expect(rowScope.getByText("critical")).toBeDefined();
    expect(rowScope.getByText("open")).toBeDefined();
    expect(rowScope.getByText("alertmanager")).toBeDefined();
  });

  it("shows a professional failure state, never a fake empty list, when control-plane is unavailable", async () => {
    listIncidentsMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const jsx = await IncidentsPage({ searchParams: Promise.resolve({}) });
    render(jsx);

    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
    expect(screen.queryByText(/no incidents match/i)).toBeNull();
  });

  it("renders pagination links using the real backend total/limit/offset", async () => {
    listIncidentsMock.mockResolvedValue(ok({ items: [SAMPLE_INCIDENT], total: 50, limit: 20, offset: 20 }));

    const jsx = await IncidentsPage({ searchParams: Promise.resolve({ offset: "20" }) });
    render(jsx);

    const prevLink = screen.getByText("← Previous").closest("a");
    const nextLink = screen.getByText("Next →").closest("a");
    expect(prevLink?.getAttribute("href")).toContain("offset=0");
    expect(nextLink?.getAttribute("href")).toContain("offset=40");
  });

  it("passes the parsed filters through to the client", async () => {
    listIncidentsMock.mockResolvedValue(ok({ items: [], total: 0, limit: 20, offset: 0 }));

    await IncidentsPage({ searchParams: Promise.resolve({ status: "open", severity: "critical" }) });

    expect(listIncidentsMock).toHaveBeenCalledWith(
      expect.objectContaining({ status: "open", severity: "critical" }),
      expect.any(String),
    );
  });

  describe("real actor resolution (Phase 14 Gate 9)", () => {
    it("no session at all -> redirected to sign-in, never rendered unscoped", async () => {
      mockNoSession();

      await expect(IncidentsPage({ searchParams: Promise.resolve({}) })).rejects.toThrow("NEXT_REDIRECT:/sign-in");
      expect(listIncidentsMock).not.toHaveBeenCalled();
    });

    it("a session with no active organization -> redirected to /organizations", async () => {
      mockSessionNoActiveOrg();

      await expect(IncidentsPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
        "NEXT_REDIRECT:/organizations",
      );
      expect(listIncidentsMock).not.toHaveBeenCalled();
    });

    it("a revoked/removed member's still-valid session -> redirected to /organizations, never rendered", async () => {
      mockRevokedMember();

      await expect(IncidentsPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
        "NEXT_REDIRECT:/organizations",
      );
      expect(listIncidentsMock).not.toHaveBeenCalled();
    });
  });
});
