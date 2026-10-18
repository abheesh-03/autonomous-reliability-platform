import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

import { AgentRunActions } from "../components/AgentRunActions";

const RUN_ID = "33333333-3333-3333-3333-333333333333";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
  refreshMock.mockClear();
});

describe("AgentRunActions", () => {
  it("a freshly-created run (current_node start) shows 'Run investigation'", () => {
    render(<AgentRunActions runId={RUN_ID} currentNode="start" resumable={true} />);
    expect(screen.getByRole("button", { name: /run investigation/i })).toBeDefined();
  });

  it("a transiently-interrupted mid-run shows 'Resume run'", () => {
    render(<AgentRunActions runId={RUN_ID} currentNode="load_incident" resumable={true} />);
    expect(screen.getByRole("button", { name: /resume run/i })).toBeDefined();
  });

  it("renders nothing for a non-resumable (terminal) run", () => {
    const { container } = render(<AgentRunActions runId={RUN_ID} currentNode="finalize" resumable={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("disables the control while a request is pending", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<AgentRunActions runId={RUN_ID} currentNode="start" resumable={true} />);
    const button = screen.getByRole("button");
    fireEvent.click(button);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`/api/agent-runs/${RUN_ID}/resume`, { method: "POST" });
    await waitFor(() => expect(button).toHaveProperty("disabled", true));

    resolveFetch(jsonResponse(200, { run_id: RUN_ID }));
  });

  it("on confirmed success, reconciles via router.refresh()", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { run_id: RUN_ID, status: "running" })));

    render(<AgentRunActions runId={RUN_ID} currentNode="start" resumable={true} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1));
  });

  it("on a safe backend failure, shows the message and still refreshes -- never retries automatically", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { error: "conflict", message: "The remediation proposal has not been decided yet." }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AgentRunActions runId={RUN_ID} currentNode="load_incident" resumable={true} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/has not been decided yet/i));
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("on an ambiguous network failure, shows a safe message, reconciles via refresh, and does not silently retry", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ETIMEDOUT"));
    vi.stubGlobal("fetch", fetchMock);

    render(<AgentRunActions runId={RUN_ID} currentNode="load_incident" resumable={true} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never references or renders a backend URL or token", () => {
    const source = AgentRunActions.toString();
    expect(source).not.toMatch(/TOKEN/);
    expect(source).not.toMatch(/agent-runtime-service|control-plane/);
    render(<AgentRunActions runId={RUN_ID} currentNode="start" resumable={true} />);
    expect(document.body.textContent ?? "").not.toMatch(/token|agent-runtime-service|control-plane/i);
  });
});
