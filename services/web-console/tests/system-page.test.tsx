import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/server/health-client", () => ({
  checkServiceHealth: vi.fn(),
}));

import SystemPage from "../app/system/page";
import { checkServiceHealth } from "../lib/server/health-client";

const checkServiceHealthMock = checkServiceHealth as unknown as ReturnType<typeof vi.fn>;

describe("SystemPage", () => {
  it("renders every monitored service, with one unavailable service never hiding the healthy others", async () => {
    checkServiceHealthMock.mockImplementation(async (name: string) => {
      if (name === "investigator-service") {
        return { name, live: "UNAVAILABLE", ready: "UNAVAILABLE" };
      }
      return { name, live: "UP", ready: "READY" };
    });

    const jsx = await SystemPage();
    render(jsx);

    expect(screen.getByText("control-plane")).toBeDefined();
    expect(screen.getByText("agent-runtime-service")).toBeDefined();
    expect(screen.getByText("investigator-service")).toBeDefined();
    expect(screen.getByText("retrieval-service")).toBeDefined();

    // The unavailable service's own row shows UNAVAILABLE...
    const rows = screen.getAllByRole("row");
    const investigatorRow = rows.find((row) => row.textContent?.includes("investigator-service"));
    expect(investigatorRow?.textContent).toContain("UNAVAILABLE");

    // ...while the healthy services still show their own real UP/READY
    // result, never dragged down by the failing one.
    const controlPlaneRow = rows.find((row) => row.textContent?.includes("control-plane"));
    expect(controlPlaneRow?.textContent).toContain("UP");
    expect(controlPlaneRow?.textContent).toContain("READY");
  });

  it("never synthesizes a healthy result for a service it never calls", async () => {
    checkServiceHealthMock.mockImplementation(async (name: string) => ({
      name,
      live: "UNKNOWN",
      ready: "UNKNOWN",
    }));

    const jsx = await SystemPage();
    render(jsx);

    expect(screen.queryByText("UP")).toBeNull();
    expect(screen.queryByText("READY")).toBeNull();
  });
});
