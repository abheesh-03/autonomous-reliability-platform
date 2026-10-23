import { APIError } from "better-auth";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fail, ok } from "../lib/server/http";

vi.mock("../lib/server/control-plane-client", () => ({
  getIncident: vi.fn(),
  transitionIncidentStatus: vi.fn(),
}));
vi.mock("../lib/server/agent-runtime-client", () => ({
  createAgentRun: vi.fn(),
}));
// Phase 14 correction round: only the Next.js/Better-Auth PLUMBING is
// mocked here -- lib/server/actor.ts's own resolveActor/
// requireActorOrUnauthorized run for REAL against these.
vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers()),
}));
vi.mock("@/lib/auth/auth", () => ({
  auth: { api: { getSession: vi.fn(), getActiveMember: vi.fn() } },
}));

import { POST } from "../app/api/incidents/[incidentId]/investigations/route";
import { auth } from "@/lib/auth/auth";
import { getIncident, transitionIncidentStatus } from "../lib/server/control-plane-client";
import { createAgentRun } from "../lib/server/agent-runtime-client";

const getIncidentMock = getIncident as unknown as ReturnType<typeof vi.fn>;
const transitionIncidentStatusMock = transitionIncidentStatus as unknown as ReturnType<typeof vi.fn>;
const createAgentRunMock = createAgentRun as unknown as ReturnType<typeof vi.fn>;
const getSessionMock = auth.api.getSession as unknown as ReturnType<typeof vi.fn>;
const getActiveMemberMock = auth.api.getActiveMember as unknown as ReturnType<typeof vi.fn>;

const ACTOR_USER_ID = "88888888-8888-8888-8888-888888888888";
const ACTOR_ORG_ID = "99999999-9999-9999-9999-999999999999";

function mockAuthenticatedActor(role = "OWNER") {
  getSessionMock.mockResolvedValue({
    user: { id: ACTOR_USER_ID },
    session: { activeOrganizationId: ACTOR_ORG_ID },
  });
  getActiveMemberMock.mockResolvedValue({
    id: "member-1",
    userId: ACTOR_USER_ID,
    organizationId: ACTOR_ORG_ID,
    role,
  });
}

function mockNoSession() {
  getSessionMock.mockResolvedValue(null);
}

function mockRevokedMember() {
  getSessionMock.mockResolvedValue({
    user: { id: ACTOR_USER_ID },
    session: { activeOrganizationId: ACTOR_ORG_ID },
  });
  getActiveMemberMock.mockRejectedValue(
    APIError.from("BAD_REQUEST", { code: "MEMBER_NOT_FOUND", message: "Member not found" }),
  );
}

const INCIDENT_ID = "11111111-1111-1111-1111-111111111111";
const RUN_ID = "33333333-3333-3333-3333-333333333333";

function incidentWith(status: string) {
  return {
    id: INCIDENT_ID,
    source: "alertmanager",
    source_fingerprint: "abc",
    title: "checkout-service is returning HTTP 5xx errors",
    description: null,
    severity: "critical",
    status,
    first_seen_at: "2026-01-01T00:00:00+00:00",
    last_seen_at: "2026-01-01T00:00:00+00:00",
    resolved_at: null,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
  };
}

function seededAgentRun() {
  return {
    run_id: RUN_ID,
    thread_id: RUN_ID,
    incident_id: INCIDENT_ID,
    status: "running",
    started_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    completed_at: null,
    current_node: "start",
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
}

const TRUSTED_ORIGIN = "http://127.0.0.1:3101";

function callRoute(origin: string | null = TRUSTED_ORIGIN) {
  const headers: Record<string, string> = {};
  if (origin !== null) headers.Origin = origin;
  return POST(new Request("http://localhost/api/incidents/x/investigations", { method: "POST", headers }), {
    params: Promise.resolve({ incidentId: INCIDENT_ID }),
  });
}

beforeEach(() => {
  vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", TRUSTED_ORIGIN);
  mockAuthenticatedActor();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("POST /api/incidents/[incidentId]/investigations", () => {
  it("7. open incident: PATCHes open->investigating, creates exactly one run, returns the durable run_id", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("open")));
    transitionIncidentStatusMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual({ run_id: RUN_ID, incident_id: INCIDENT_ID });
    expect(transitionIncidentStatusMock).toHaveBeenCalledWith(INCIDENT_ID, "open", "investigating", expect.any(String));
    expect(createAgentRunMock).toHaveBeenCalledTimes(1);
    expect(createAgentRunMock).toHaveBeenCalledWith(INCIDENT_ID, expect.any(String));
  });

  it("8. acknowledged incident: PATCHes acknowledged->investigating, creates a run", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("acknowledged")));
    transitionIncidentStatusMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

    const response = await callRoute();

    expect(response.status).toBe(201);
    expect(transitionIncidentStatusMock).toHaveBeenCalledWith(
      INCIDENT_ID,
      "acknowledged",
      "investigating",
      expect.any(String),
    );
    expect(createAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it("9. already investigating: skips the PATCH, still creates a run", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

    const response = await callRoute();

    expect(response.status).toBe(201);
    expect(transitionIncidentStatusMock).not.toHaveBeenCalled();
    expect(createAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it.each(["remediating", "resolved", "closed"])(
    "10. %s incident: no PATCH, no run creation, safe conflict",
    async (status) => {
      getIncidentMock.mockResolvedValue(ok(incidentWith(status)));

      const response = await callRoute();
      const body = await response.json();

      expect(response.status).toBe(409);
      expect(body.error).toBe("conflict");
      expect(transitionIncidentStatusMock).not.toHaveBeenCalled();
      expect(createAgentRunMock).not.toHaveBeenCalled();
    },
  );

  it("11. lifecycle PATCH conflict: no run creation", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("open")));
    transitionIncidentStatusMock.mockResolvedValue(fail("conflict", "stale expected_status"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(409);
    expect(body.error).toBe("conflict");
    expect(createAgentRunMock).not.toHaveBeenCalled();
  });

  it("12. lifecycle PATCH succeeds but create-run fails: no rollback PATCH is attempted", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("open")));
    transitionIncidentStatusMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(fail("unavailable", "agent-runtime-service unreachable"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toBe("unavailable");
    // Exactly one PATCH call (the forward transition) -- never a
    // second call attempting to roll the incident back to "open".
    expect(transitionIncidentStatusMock).toHaveBeenCalledTimes(1);
    expect(transitionIncidentStatusMock).toHaveBeenCalledWith(INCIDENT_ID, "open", "investigating", expect.any(String));
  });

  it("13. create-run network/ambiguous failure: no second create-run attempt", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(fail("unavailable", "agent-runtime-service unreachable"));

    const response = await callRoute();

    expect(response.status).toBe(503);
    expect(createAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it("14. missing incident: 404, no mutation", async () => {
    getIncidentMock.mockResolvedValue(fail("not_found", "incident not found"));

    const response = await callRoute();
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toBe("not_found");
    expect(transitionIncidentStatusMock).not.toHaveBeenCalled();
    expect(createAgentRunMock).not.toHaveBeenCalled();
  });

  it("15. the success response is bounded: run_id and incident_id only", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

    const response = await callRoute();
    const body = await response.json();

    expect(Object.keys(body).sort()).toEqual(["incident_id", "run_id"]);
  });

  it("22. never calls anything resembling /resume -- createAgentRun is the only agent-runtime write", async () => {
    getIncidentMock.mockResolvedValue(ok(incidentWith("open")));
    transitionIncidentStatusMock.mockResolvedValue(ok(incidentWith("investigating")));
    createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

    await callRoute();

    // The mocked agent-runtime-client module exposes ONLY createAgentRun
    // in this test (see the vi.mock above) -- if the route ever called
    // a resumeAgentRun export, this mock would throw "is not a
    // function" rather than silently succeeding.
    expect(createAgentRunMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a malformed incident identifier before any backend call", async () => {
    const response = await POST(
      new Request("http://localhost/api/incidents/x/investigations", { method: "POST", headers: { Origin: TRUSTED_ORIGIN } }),
      { params: Promise.resolve({ incidentId: "not-a-uuid" }) },
    );

    expect(response.status).toBe(422);
    expect(getIncidentMock).not.toHaveBeenCalled();
  });

  describe("origin/CSRF guard", () => {
    it("rejects a missing Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute(null);
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getIncidentMock).not.toHaveBeenCalled();
      expect(transitionIncidentStatusMock).not.toHaveBeenCalled();
      expect(createAgentRunMock).not.toHaveBeenCalled();
    });

    it("rejects a cross-origin Origin header with a safe 403, before any backend call", async () => {
      const response = await callRoute("http://evil.example.com");
      const body = await response.json();

      expect(response.status).toBe(403);
      expect(body.error).toBe("forbidden");
      expect(getIncidentMock).not.toHaveBeenCalled();
      expect(createAgentRunMock).not.toHaveBeenCalled();
    });

    it("never derives trust from Host/X-Forwarded-Host -- a spoofed forwarded-host with a cross-origin Origin is still rejected", async () => {
      const response = await POST(
        new Request("http://localhost/api/incidents/x/investigations", {
          method: "POST",
          headers: { Origin: "http://evil.example.com", "X-Forwarded-Host": "127.0.0.1:3101" },
        }),
        { params: Promise.resolve({ incidentId: INCIDENT_ID }) },
      );

      expect(response.status).toBe(403);
      expect(getIncidentMock).not.toHaveBeenCalled();
    });

    it("allows a request carrying the exact trusted origin, preserving existing same-origin behavior", async () => {
      getIncidentMock.mockResolvedValue(ok(incidentWith("investigating")));
      createAgentRunMock.mockResolvedValue(ok(seededAgentRun()));

      const response = await callRoute(TRUSTED_ORIGIN);

      expect(response.status).toBe(201);
      expect(getIncidentMock).toHaveBeenCalledTimes(1);
    });
  });

  describe("real actor resolution (Phase 14 Gate 9/Blocker 1)", () => {
    it("no session at all -> 401, before any backend call", async () => {
      mockNoSession();

      const response = await callRoute();
      const body = await response.json();

      expect(response.status).toBe(401);
      expect(body.error).toBe("unauthorized");
      expect(getIncidentMock).not.toHaveBeenCalled();
      expect(createAgentRunMock).not.toHaveBeenCalled();
    });

    it("a revoked/removed member's still-valid session cannot start an investigation -- 401, no mutation", async () => {
      mockRevokedMember();

      const response = await callRoute();
      const body = await response.json();

      expect(response.status).toBe(401);
      expect(body.error).toBe("unauthorized");
      expect(getIncidentMock).not.toHaveBeenCalled();
      expect(transitionIncidentStatusMock).not.toHaveBeenCalled();
      expect(createAgentRunMock).not.toHaveBeenCalled();
    });
  });
});
