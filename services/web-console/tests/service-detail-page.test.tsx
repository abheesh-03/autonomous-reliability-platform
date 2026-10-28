import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ok, fail } from "../lib/server/http";
import { ToastProvider } from "../components/ui/toast";

function renderWithProviders(jsx: React.ReactElement) {
  return render(<ToastProvider>{jsx}</ToastProvider>);
}

vi.mock("../lib/server/service-client", () => ({
  getService: vi.fn(),
}));
vi.mock("../lib/server/integration-client", () => ({
  listIntegrationCredentials: vi.fn(),
  getServiceTelemetrySummary: vi.fn(),
}));
vi.mock("../lib/server/control-plane-client", () => ({
  listIncidents: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: vi.fn(async () => new Headers()) }));
vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/auth/auth", () => ({
  auth: { api: { getSession: vi.fn(), getActiveMember: vi.fn() } },
}));

import ServiceDetailPage from "../app/services/[serviceId]/page";
import { auth } from "@/lib/auth/auth";
import { getService } from "../lib/server/service-client";
import { listIntegrationCredentials, getServiceTelemetrySummary } from "../lib/server/integration-client";
import { listIncidents } from "../lib/server/control-plane-client";

const getServiceMock = getService as unknown as ReturnType<typeof vi.fn>;
const listIntegrationsMock = listIntegrationCredentials as unknown as ReturnType<typeof vi.fn>;
const getTelemetryMock = getServiceTelemetrySummary as unknown as ReturnType<typeof vi.fn>;
const listIncidentsMock = listIncidents as unknown as ReturnType<typeof vi.fn>;
const getSessionMock = auth.api.getSession as unknown as ReturnType<typeof vi.fn>;
const getActiveMemberMock = auth.api.getActiveMember as unknown as ReturnType<typeof vi.fn>;

const SERVICE_ID = "11111111-1111-1111-1111-111111111111";
const ORG_ID = "99999999-9999-9999-9999-999999999999";

function mockActor(role = "OWNER") {
  getSessionMock.mockResolvedValue({
    user: { id: "user-1" },
    session: { activeOrganizationId: ORG_ID },
  });
  getActiveMemberMock.mockResolvedValue({ id: "member-1", userId: "user-1", organizationId: ORG_ID, role });
}

const SERVICE = {
  id: SERVICE_ID,
  organization_id: ORG_ID,
  name: "checkout-api",
  kind: "rest_api" as const,
  language: "Python",
  description: "Handles checkout",
  created_by_user_id: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const EMPTY_TELEMETRY = {
  service_id: SERVICE_ID,
  status: "not_configured" as const,
  window_minutes: 15,
  request_count: 0,
  error_count: 0,
  request_rate_per_minute: 0,
  error_rate: null,
  mean_latency_seconds: null,
  last_observed_at: null,
  generated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  mockActor();
  listIntegrationsMock.mockResolvedValue(ok({ items: [] }));
  getTelemetryMock.mockResolvedValue(ok(EMPTY_TELEMETRY));
  listIncidentsMock.mockResolvedValue(ok({ items: [], total: 0, limit: 50, offset: 0 }));
});

describe("ServiceDetailPage", () => {
  it("renders the service header and the honest not-configured telemetry state", async () => {
    getServiceMock.mockResolvedValue(ok(SERVICE));

    const jsx = await ServiceDetailPage({ params: Promise.resolve({ serviceId: SERVICE_ID }) });
    renderWithProviders(jsx);

    expect(screen.getByRole("heading", { name: "checkout-api" })).toBeDefined();
    expect(screen.getByText("Not configured")).toBeDefined();
    expect(screen.getByText("No integration credentials yet. Generate one to connect a real external application.")).toBeDefined();
  });

  it("renders real, non-fabricated telemetry measurements when receiving data", async () => {
    getServiceMock.mockResolvedValue(ok(SERVICE));
    getTelemetryMock.mockResolvedValue(
      ok({
        ...EMPTY_TELEMETRY,
        status: "receiving_telemetry",
        request_count: 120,
        error_count: 6,
        request_rate_per_minute: 8,
        error_rate: 0.05,
        mean_latency_seconds: 0.09,
        last_observed_at: "2026-01-01T00:05:00Z",
      }),
    );

    const jsx = await ServiceDetailPage({ params: Promise.resolve({ serviceId: SERVICE_ID }) });
    renderWithProviders(jsx);

    expect(screen.getByText("Receiving telemetry")).toBeDefined();
    expect(screen.getByText("8.0/min")).toBeDefined();
    expect(screen.getByText("5.0%")).toBeDefined();
  });

  it("shows a professional failure state when the service backend call fails, never fabricating a service", async () => {
    getServiceMock.mockResolvedValue(fail("unavailable", "control-plane unreachable"));

    const jsx = await ServiceDetailPage({ params: Promise.resolve({ serviceId: SERVICE_ID }) });
    renderWithProviders(jsx);

    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
    expect(screen.queryByText("checkout-api")).toBeNull();
  });

  it("calls notFound (never renders) for a service that does not exist or belongs to another organization", async () => {
    getServiceMock.mockResolvedValue(fail("not_found", "service not found"));

    await expect(ServiceDetailPage({ params: Promise.resolve({ serviceId: SERVICE_ID }) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("hides credential management for a VIEWER but still shows telemetry", async () => {
    mockActor("VIEWER");
    getServiceMock.mockResolvedValue(ok(SERVICE));

    const jsx = await ServiceDetailPage({ params: Promise.resolve({ serviceId: SERVICE_ID }) });
    renderWithProviders(jsx);

    expect(screen.getByText("Requires OWNER / ADMIN / ENGINEER")).toBeDefined();
    expect(screen.queryByRole("button", { name: /generate credential/i })).toBeNull();
  });
});
