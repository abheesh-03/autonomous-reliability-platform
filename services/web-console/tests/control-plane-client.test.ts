import { afterEach, describe, expect, it, vi } from "vitest";
import { getIncident, listIncidents } from "../lib/server/control-plane-client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listIncidents", () => {
  it("builds the exact query string control-plane expects", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [], total: 0, limit: 10, offset: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    await listIncidents({ status: "open", severity: "critical", source: "alertmanager", limit: 10, offset: 5 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.pathname).toBe("/api/v1/incidents");
    expect(requestedUrl.searchParams.get("status")).toBe("open");
    expect(requestedUrl.searchParams.get("severity")).toBe("critical");
    expect(requestedUrl.searchParams.get("source")).toBe("alertmanager");
    expect(requestedUrl.searchParams.get("limit")).toBe("10");
    expect(requestedUrl.searchParams.get("offset")).toBe("5");
  });

  it("omits filter parameters that were not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [], total: 0, limit: 20, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await listIncidents({});

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.has("status")).toBe(false);
    expect(requestedUrl.searchParams.has("severity")).toBe(false);
    expect(requestedUrl.searchParams.has("source")).toBe(false);
    // Defaults are still sent explicitly, clamped to the API's bounds.
    expect(requestedUrl.searchParams.get("limit")).toBe("20");
    expect(requestedUrl.searchParams.get("offset")).toBe("0");
  });

  it("clamps an out-of-range limit before ever calling control-plane", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [], total: 0, limit: 100, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await listIncidents({ limit: 99999, offset: -5 });

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.get("limit")).toBe("100");
    expect(requestedUrl.searchParams.get("offset")).toBe("0");
  });
});

describe("getIncident error categorization", () => {
  it("categorizes a 404 as not_found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { detail: "not found" })));
    const result = await getIncident("11111111-1111-1111-1111-111111111111");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("not_found");
  });

  it("categorizes a 422 as validation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, { detail: "bad uuid" })));
    const result = await getIncident("not-a-uuid");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("validation");
  });

  it("categorizes a 503 as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { detail: "unavailable" })));
    const result = await getIncident("11111111-1111-1111-1111-111111111111");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a network-level failure as unavailable, never throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED")),
    );
    const result = await getIncident("11111111-1111-1111-1111-111111111111");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a non-JSON body as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>not json</html>", { status: 200 })));
    const result = await getIncident("11111111-1111-1111-1111-111111111111");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes a 200 response with the wrong shape as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { unexpected: "shape" })));
    const result = await getIncident("11111111-1111-1111-1111-111111111111");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("returns the incident on a well-formed 200", async () => {
    const incident = {
      id: "11111111-1111-1111-1111-111111111111",
      source: "alertmanager",
      source_fingerprint: "abc",
      title: "checkout-service is returning HTTP 5xx errors",
      description: null,
      severity: "critical",
      status: "open",
      first_seen_at: "2026-01-01T00:00:00+00:00",
      last_seen_at: "2026-01-01T00:00:00+00:00",
      resolved_at: null,
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, incident)));
    const result = await getIncident(incident.id);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual(incident);
  });
});
