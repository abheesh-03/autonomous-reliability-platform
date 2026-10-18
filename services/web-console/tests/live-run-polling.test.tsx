import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

import { LiveRunPolling, pollIntervalMs } from "../components/LiveRunPolling";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  refreshMock.mockClear();
});

describe("pollIntervalMs", () => {
  it("running polls fast (~2-3s)", () => {
    expect(pollIntervalMs("running", "investigating")).toBe(2500);
  });

  it("waiting_for_approval polls slower (~5s)", () => {
    expect(pollIntervalMs("waiting_for_approval", "investigating")).toBe(5000);
  });

  it("completed + incident still remediating keeps polling (~5s)", () => {
    expect(pollIntervalMs("completed", "remediating")).toBe(5000);
  });

  it("failed + incident still remediating keeps polling (~5s)", () => {
    expect(pollIntervalMs("failed", "remediating")).toBe(5000);
  });

  it("completed + incident resolved stops polling", () => {
    expect(pollIntervalMs("completed", "resolved")).toBeNull();
  });

  it("failed + incident not remediating stops polling", () => {
    expect(pollIntervalMs("failed", "investigating")).toBeNull();
  });

  it("completed + live incident status unknown (fetch failed) stops polling, never assumes remediating", () => {
    expect(pollIntervalMs("completed", null)).toBeNull();
  });
});

describe("LiveRunPolling", () => {
  it("schedules a refresh while running", () => {
    render(<LiveRunPolling status="running" incidentStatus="investigating" />);

    expect(refreshMock).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2500);
    expect(refreshMock).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2500);
    expect(refreshMock).toHaveBeenCalledTimes(2);
  });

  it("schedules a slower refresh while waiting_for_approval", () => {
    render(<LiveRunPolling status="waiting_for_approval" incidentStatus="investigating" />);

    vi.advanceTimersByTime(2500);
    expect(refreshMock).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2500);
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("keeps refreshing once completed if the incident is still remediating", () => {
    render(<LiveRunPolling status="completed" incidentStatus="remediating" />);

    vi.advanceTimersByTime(5000);
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("stops scheduling once completed and the incident is resolved -- no timer is ever set", () => {
    render(<LiveRunPolling status="completed" incidentStatus="resolved" />);

    vi.advanceTimersByTime(60_000);
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("clears its timer on unmount -- no refresh fires after the component is gone", () => {
    const { unmount } = render(<LiveRunPolling status="running" incidentStatus="investigating" />);
    unmount();

    vi.advanceTimersByTime(60_000);
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("never calls fetch -- every tick is a plain router.refresh(), never a POST/mutation", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<LiveRunPolling status="running" incidentStatus="investigating" />);
    vi.advanceTimersByTime(10_000);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(refreshMock.mock.calls.length).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });

  it("renders no visible UI", () => {
    const { container } = render(<LiveRunPolling status="running" incidentStatus="investigating" />);
    expect(container.firstChild).toBeNull();
  });
});
