import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

import { RemediationDecisionControl } from "../components/RemediationDecisionControl";

const RUN_ID = "33333333-3333-3333-3333-333333333333";
const PROPOSAL_ID = "44444444-4444-4444-4444-444444444444";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
  refreshMock.mockClear();
});

describe("RemediationDecisionControl", () => {
  it("shows Approve/Reject when the proposal is pending_approval", () => {
    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    expect(screen.getByRole("button", { name: /approve/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDefined();
    expect(screen.queryByRole("button", { name: /continue workflow/i })).toBeNull();
  });

  it("shows a separate 'Continue workflow' action once the proposal has been decided but the run has not resumed", () => {
    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="approved" runResumable={true} />,
    );
    expect(screen.getByRole("button", { name: /continue workflow/i })).toBeDefined();
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /reject/i })).toBeNull();
  });

  it("renders nothing once the run is no longer resumable and the proposal is already decided", () => {
    const { container } = render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="succeeded" runResumable={false} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("disables Approve/Reject while a decision is pending", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    const approveButton = screen.getByRole("button", { name: /approve/i });
    fireEvent.click(approveButton);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`/api/remediation-proposals/${PROPOSAL_ID}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: "approve", comment: undefined }),
    });
    await waitFor(() => expect(approveButton).toHaveProperty("disabled", true));

    resolveFetch(jsonResponse(200, { id: PROPOSAL_ID, status: "approved" }));
  });

  it("on confirmed approve success, reconciles via router.refresh() and never calls resume itself", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: PROPOSAL_ID, status: "approved" }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("resume"))).toBe(true);
  });

  it("on a safe decision failure, shows the message, still refreshes, and never retries automatically", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { error: "conflict", message: "The proposal's status changed." }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/status changed/i));
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("on an ambiguous network failure during approve, shows a safe message and reconciles via refresh without retrying", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ETIMEDOUT"));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("'Continue workflow' calls the resume route (not the decision route) exactly once and refreshes on completion", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { run_id: RUN_ID, status: "remediating" }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="approved" runResumable={true} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /continue workflow/i }));

    expect(fetchMock).toHaveBeenCalledWith(`/api/agent-runs/${RUN_ID}/resume`, { method: "POST" });
    await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never references or renders a backend URL or an approver token", () => {
    const source = RemediationDecisionControl.toString();
    expect(source).not.toMatch(/TOKEN/);
    expect(source).not.toMatch(/control-plane:8000|agent-runtime-service:8003/);
    render(
      <RemediationDecisionControl runId={RUN_ID} proposalId={PROPOSAL_ID} proposalStatus="pending_approval" runResumable={true} />,
    );
    expect(document.body.textContent ?? "").not.toMatch(/token|control-plane:8000|agent-runtime-service:8003/i);
  });
});
