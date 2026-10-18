import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { StartInvestigationControl } from "../components/StartInvestigationControl";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
  pushMock.mockClear();
});

describe("StartInvestigationControl", () => {
  it("16. renders a Start control for an eligible (open) incident", () => {
    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    expect(screen.getByRole("button", { name: /start ai investigation/i })).toBeDefined();
  });

  it("renders the recovery-variant label and limitation helper text for an investigating incident", () => {
    render(
      <StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="investigating" />,
    );
    expect(screen.getByRole("button", { name: /create investigation run/i })).toBeDefined();
    expect(screen.getByText(/cannot list existing agent runs/i)).toBeDefined();
  });

  it("18. click performs one same-origin POST and disables the button while pending", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    const button = screen.getByRole("button");
    fireEvent.click(button);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/incidents/11111111-1111-1111-1111-111111111111/investigations",
      { method: "POST" },
    );
    await waitFor(() => expect(button).toHaveProperty("disabled", true));

    resolveFetch(jsonResponse(201, { run_id: "33333333-3333-3333-3333-333333333333", incident_id: "11111111-1111-1111-1111-111111111111" }));
  });

  it("19. on success, navigates using the real returned durable run_id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(201, { run_id: "33333333-3333-3333-3333-333333333333", incident_id: "11111111-1111-1111-1111-111111111111" }),
      ),
    );

    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/agent-runs/33333333-3333-3333-3333-333333333333"));
  });

  it("20. on failure, shows a safe operator-facing message, never a raw body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(409, { error: "conflict", message: "The incident is no longer eligible." })),
    );

    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/no longer eligible/i));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("23. navigation occurs only after the durable run_id is received, with no resume request involved", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(201, { run_id: "33333333-3333-3333-3333-333333333333", incident_id: "11111111-1111-1111-1111-111111111111" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/agent-runs/33333333-3333-3333-3333-333333333333"));
    // Exactly one fetch call total -- the start POST -- never a second
    // call to anything resembling a resume endpoint.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("resume"))).toBe(true);
  });

  it("21. never receives or renders a token string -- only incident id/status are ever passed", () => {
    const source = StartInvestigationControl.toString();
    expect(source).not.toMatch(/TOKEN/);
    render(<StartInvestigationControl incidentId="11111111-1111-1111-1111-111111111111" incidentStatus="open" />);
    expect(document.body.textContent ?? "").not.toMatch(/token/i);
  });
});
