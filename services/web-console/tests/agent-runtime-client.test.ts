import { afterEach, describe, expect, it, vi } from "vitest";
import { createAgentRun, getAgentRun, getAgentRunHistory, resumeAgentRun } from "../lib/server/agent-runtime-client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const VALID_AGENT_RUN = {
  run_id: "11111111-1111-1111-1111-111111111111",
  thread_id: "11111111-1111-1111-1111-111111111111",
  incident_id: "22222222-2222-2222-2222-222222222222",
  status: "running",
  started_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  completed_at: null,
  current_node: "load_incident",
  completed_nodes: [],
  incident_snapshot: null,
  investigation_report: null,
  result_quality: null,
  validation_notes: [],
  error_code: null,
  error_detail: null,
  resumable: true,
  remediation_proposal_id: null,
  remediation_action_type: null,
  remediation_target: null,
  remediation_status: null,
  execution_result: null,
  recovery_verification: null,
};

describe("getAgentRun", () => {
  it("returns a real-shaped successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, VALID_AGENT_RUN)));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual(VALID_AGENT_RUN);
  });

  it("categorizes a 404 as not_found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { detail: "agent run not found" })));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("not_found");
  });

  it("categorizes a 422 as validation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, { detail: "invalid uuid" })));
    const result = await getAgentRun("not-a-uuid");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("validation");
  });

  it("categorizes a network-level failure as unavailable, never throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED")));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a 503 as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { detail: "unavailable" })));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a non-JSON body as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes a response missing required fields as malformed", async () => {
    const { resumable: _unused, ...missingResumable } = VALID_AGENT_RUN;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, missingResumable)));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes an invalid status enum value as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { ...VALID_AGENT_RUN, status: "paused" })));
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes an invalid remediation_status convention value as malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { ...VALID_AGENT_RUN, remediation_status: "mystery" })),
    );
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes a malformed execution_result as malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, { ...VALID_AGENT_RUN, execution_result: { status: "ok" /* not succeeded|failed */ } }),
      ),
    );
    const result = await getAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });
});

const VALID_HISTORY = {
  run_id: "11111111-1111-1111-1111-111111111111",
  thread_id: "11111111-1111-1111-1111-111111111111",
  entries: [
    {
      step: 0,
      checkpoint_id: "chk-1",
      node: "start",
      status_at_step: "running",
      created_at: "2026-01-01T00:00:00+00:00",
      next_nodes: ["load_incident"],
    },
  ],
};

describe("getAgentRunHistory", () => {
  it("returns a real-shaped successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, VALID_HISTORY)));
    const result = await getAgentRunHistory(VALID_HISTORY.run_id);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual(VALID_HISTORY);
  });

  it("fails safely (malformed) when an entry is missing a required field", async () => {
    const corrupted = {
      ...VALID_HISTORY,
      entries: [{ step: 0, node: "start", created_at: "2026-01-01T00:00:00+00:00", next_nodes: [] }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, corrupted)));
    const result = await getAgentRunHistory(VALID_HISTORY.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("fails safely (malformed) when an entry's status_at_step is not a real enum value", async () => {
    const corrupted = {
      ...VALID_HISTORY,
      entries: [{ ...VALID_HISTORY.entries[0], status_at_step: "paused" }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, corrupted)));
    const result = await getAgentRunHistory(VALID_HISTORY.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes a 404 as not_found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { detail: "agent run not found" })));
    const result = await getAgentRunHistory(VALID_HISTORY.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("not_found");
  });
});

describe("createAgentRun", () => {
  const INCIDENT_ID = "22222222-2222-2222-2222-222222222222";

  it("sends exactly one real POST (never PATCH) with {incident_id} and no more", async () => {
    // Regression guard, paired with transitionIncidentStatus's own
    // PATCH regression test in control-plane-client.test.ts: this
    // observes the actual RequestInit.method agent-runtime-service's
    // real POST /api/v1/agent-runs contract requires, so a future
    // http.ts change that accidentally routes this call through
    // patchJson (or any non-POST method) would fail this test.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, { ...VALID_AGENT_RUN, incident_id: INCIDENT_ID }));
    vi.stubGlobal("fetch", fetchMock);

    await createAgentRun(INCIDENT_ID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://agent-runtime-service:8003/api/v1/agent-runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ incident_id: INCIDENT_ID });
  });

  it("returns the seeded AgentRun on 201", async () => {
    const seeded = { ...VALID_AGENT_RUN, incident_id: INCIDENT_ID };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(201, seeded)));

    const result = await createAgentRun(INCIDENT_ID);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual(seeded);
  });

  it("categorizes a 422 as validation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, { detail: "invalid incident_id" })));
    const result = await createAgentRun(INCIDENT_ID);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("validation");
  });

  it("categorizes a network-level failure as unavailable, never throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED")));
    const result = await createAgentRun(INCIDENT_ID);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a 503 as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { detail: "unavailable" })));
    const result = await createAgentRun(INCIDENT_ID);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a non-JSON body as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 201 })));
    const result = await createAgentRun(INCIDENT_ID);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("performs no automatic retry on an ambiguous/network failure -- exactly one call, ever", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ETIMEDOUT"));
    vi.stubGlobal("fetch", fetchMock);

    const result = await createAgentRun(INCIDENT_ID);

    expect(result.ok).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("resumeAgentRun", () => {
  it("sends exactly one real POST to .../resume with an empty body -- no request body is bound by the real contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, VALID_AGENT_RUN));
    vi.stubGlobal("fetch", fetchMock);

    await resumeAgentRun(VALID_AGENT_RUN.run_id);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`http://agent-runtime-service:8003/api/v1/agent-runs/${VALID_AGENT_RUN.run_id}/resume`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it("returns the real updated AgentRun on 200", async () => {
    const resumed = { ...VALID_AGENT_RUN, status: "waiting_for_approval", current_node: "await_human_approval" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, resumed)));

    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual(resumed);
  });

  it("categorizes a 404 as not_found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { detail: "agent run not found" })));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("not_found");
  });

  it("categorizes a 409 (terminal state or approval still pending) as conflict", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(409, { detail: "approval_pending: proposal is pending_approval" })),
    );
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("conflict");
  });

  it("categorizes a 422 as validation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, { detail: "invalid uuid" })));
    const result = await resumeAgentRun("not-a-uuid");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("validation");
  });

  it("categorizes a 503 (dependency unavailable, run remains resumable) as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { detail: "tool-gateway unavailable" })));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a 500 (defensive backend error) as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(500, { detail: "proposal not found" })));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a network-level failure/timeout as unavailable, never throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ETIMEDOUT")));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
  });

  it("categorizes a non-JSON body as malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("categorizes a 200 response that does not match the AgentRun shape as malformed", async () => {
    const { resumable: _unused, ...missingResumable } = VALID_AGENT_RUN;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, missingResumable)));
    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("malformed");
  });

  it("performs no automatic retry on an ambiguous/network failure -- exactly one call, ever", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ETIMEDOUT"));
    vi.stubGlobal("fetch", fetchMock);

    const result = await resumeAgentRun(VALID_AGENT_RUN.run_id);

    expect(result.ok).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
