import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

import { demoSnapshot } from "../lib/demo/snapshot";
import DemoOverviewPage from "../app/demo/page";
import DemoIncidentPage from "../app/demo/incident/[incidentId]/page";
import DemoInvestigationPage from "../app/demo/investigation/[runId]/page";
import DemoTelemetryPage from "../app/demo/telemetry/[serviceId]/page";

const REAL_INCIDENT_ID = demoSnapshot.incident_scenario.incident.id;
const REAL_RUN_ID = demoSnapshot.incident_scenario.agent_run.run_id;
const REAL_SERVICE_ID = demoSnapshot.telemetry_scenario.service.id;

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // Phase 18, Section 3: the recorded demo must never make an
  // operational/live-data request of any kind. A real spy on global
  // fetch -- not an assumption -- proves every demo page below is
  // backed entirely by the bundled static snapshot.
  fetchSpy = vi.fn(() => {
    throw new Error("demo pages must never call fetch()");
  });
  vi.stubGlobal("fetch", fetchSpy);
});

describe("recorded demo pages: anonymous access and snapshot-only rendering", () => {
  it("overview page renders real recorded counts and all three entry points without any fetch", () => {
    render(DemoOverviewPage());

    expect(screen.getByText(demoSnapshot.incident_scenario.incident.title)).toBeDefined();
    expect(screen.getByText(demoSnapshot.telemetry_scenario.service.name, { exact: false })).toBeDefined();
    expect(screen.getByRole("link", { name: /view incident/i }).getAttribute("href")).toBe(
      `/demo/incident/${REAL_INCIDENT_ID}`,
    );
    expect(screen.getByRole("link", { name: /view investigation/i }).getAttribute("href")).toBe(
      `/demo/investigation/${REAL_RUN_ID}`,
    );
    expect(screen.getByRole("link", { name: /view telemetry/i }).getAttribute("href")).toBe(
      `/demo/telemetry/${REAL_SERVICE_ID}`,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("incident page renders the real recorded incident and audit timeline for its real id, without fetch", async () => {
    const jsx = await DemoIncidentPage({ params: Promise.resolve({ incidentId: REAL_INCIDENT_ID }) });
    render(jsx);

    expect(screen.getByRole("heading", { name: demoSnapshot.incident_scenario.incident.title })).toBeDefined();
    expect(screen.getByText(/audit timeline/i)).toBeDefined();
    // No pretend action controls -- Section 1's explicit requirement.
    expect(screen.queryByRole("button", { name: /start.*investigation/i })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("incident page returns not-found for an id that is not the recorded one", async () => {
    await expect(
      DemoIncidentPage({ params: Promise.resolve({ incidentId: "00000000-0000-0000-0000-000000000000" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("investigation page renders the completed recorded run with report, remediation, and recovery verification, without fetch or live controls", async () => {
    const jsx = await DemoInvestigationPage({ params: Promise.resolve({ runId: REAL_RUN_ID }) });
    render(jsx);

    expect(screen.getByRole("heading", { name: "AI investigation" })).toBeDefined();
    expect(screen.getByText(/recorded run/i)).toBeDefined();
    // The real recorded remediation action/target must be shown...
    expect(screen.getAllByText(demoSnapshot.incident_scenario.agent_run.remediation_target, { exact: false }).length).toBeGreaterThan(0);
    // ...but never behind a live control.
    expect(screen.queryByRole("button", { name: /^(run investigation|approve|reject|continue workflow)$/i })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("investigation page returns not-found for an id that is not the recorded one", async () => {
    await expect(
      DemoInvestigationPage({ params: Promise.resolve({ runId: "00000000-0000-0000-0000-000000000000" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("telemetry page renders the real recorded service telemetry for its real id, without fetch or a live credential-generation control", async () => {
    const jsx = await DemoTelemetryPage({ params: Promise.resolve({ serviceId: REAL_SERVICE_ID }) });
    render(jsx);

    expect(screen.getByRole("heading", { name: demoSnapshot.telemetry_scenario.service.name })).toBeDefined();
    expect(screen.getByText(demoSnapshot.telemetry_scenario.credential.credential_id)).toBeDefined();
    expect(screen.queryByRole("button", { name: /generate credential/i })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("telemetry page returns not-found for an id that is not the recorded one", async () => {
    await expect(
      DemoTelemetryPage({ params: Promise.resolve({ serviceId: "00000000-0000-0000-0000-000000000000" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("recorded demo snapshot: no private fields", () => {
  it("never carries an organization id, created_by_user_id, or bearer_token anywhere in the published snapshot", () => {
    const serialized = JSON.stringify(demoSnapshot);
    expect(serialized).not.toMatch(/organization_id/i);
    expect(serialized).not.toMatch(/created_by_user_id/i);
    expect(serialized).not.toMatch(/bearer_token/i);
    expect(serialized).not.toMatch(/decided_by_user_id/i);
    expect(serialized).not.toMatch(/decided_by_organization_id/i);
  });

  it("never carries an @ sign anywhere (no email address leaked into the public snapshot)", () => {
    const serialized = JSON.stringify(demoSnapshot);
    expect(serialized).not.toMatch(/@/);
  });
});
