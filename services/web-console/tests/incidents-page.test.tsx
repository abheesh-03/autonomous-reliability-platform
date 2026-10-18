import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ok, fail } from "../lib/server/http";

vi.mock("../lib/server/control-plane-client", () => ({
  listIncidents: vi.fn(),
}));

import IncidentsPage from "../app/incidents/page";
import { listIncidents } from "../lib/server/control-plane-client";

const listIncidentsMock = listIncidents as unknown as ReturnType<typeof vi.fn>;

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
    );
  });
});
