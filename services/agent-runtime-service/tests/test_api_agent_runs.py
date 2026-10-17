"""API-contract tests via FastAPI's TestClient.

Deliberately builds its OWN minimal FastAPI app (same routers as the
real app.main:app) rather than using the real app's own `lifespan`,
which opens a REAL PostgreSQL connection at startup -- that is exactly
what test_checkpoint_durability.py exists to exercise for real; these
tests stay fast/offline by wiring `app.state.graph` directly to a real
compiled graph backed by `InMemorySaver` (Phase 7 §LANGGRAPH: allowed
for focused unit tests where persistence is not under test) plus fake
control-plane/investigator client doubles.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent_runtime_service.api.agent_runs import router as agent_runs_router
from agent_runtime_service.clients.control_plane import ControlPlaneUnavailableError
from agent_runtime_service.clients.investigator import InvestigatorUnavailableError
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)


class FakeControlPlaneClient:
    def __init__(self, *, raise_=None):
        self._raise = raise_

    async def get_incident(self, incident_id):
        if self._raise:
            raise self._raise
        return IncidentSnapshot.model_validate(incident_json(incident_id=uuid.UUID(incident_id)))


class FakeInvestigatorClient:
    def __init__(self, *, raise_=None):
        self._raise = raise_

    async def investigate(self, incident_id):
        if self._raise:
            raise self._raise
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(str(incident_id))))


def _build_app(control_plane=None, investigator=None) -> FastAPI:
    app = FastAPI()
    app.include_router(agent_runs_router)
    control_plane = control_plane or FakeControlPlaneClient()
    graph = compile_graph(
        control_plane,
        investigator or FakeInvestigatorClient(),
        BOUNDS,
        InMemorySaver(),
        # No tool_gateway_client here -- every one of these Phase
        # 7-era tests' incidents/policy never reaches a real
        # remediation proposal, so propose_remediation always finalizes
        # as "not_applicable" and the real interrupt is never reached
        # (see tests/test_remediation_graph.py /
        # tests/test_api_remediation.py for the Phase 8 paths that DO
        # reach it).
    )
    app.state.graph = graph
    app.state.runtime_bounds = BOUNDS
    # Phase 8: resume_agent_run's own approval-gate logic reads this --
    # unused by any of these legacy tests (their runs never reach a
    # real pending interrupt at all) but required for the app to be
    # constructed the same shape the real main.py builds it.
    app.state.control_plane_client = control_plane
    return app


def test_create_agent_run_seeds_only_and_never_executes():
    """Phase 7 correction round (finding #2 -- CORE INVARIANT): the
    caller must possess a durable run_id BEFORE any fallible external
    graph work begins. create_agent_run now seeds a durable initial
    checkpoint only -- it makes NO control-plane/investigator-service
    call at all."""
    control_plane_calls = {"n": 0}
    investigator_calls = {"n": 0}

    class CountingControlPlaneClient(FakeControlPlaneClient):
        async def get_incident(self, incident_id):
            control_plane_calls["n"] += 1
            return await super().get_incident(incident_id)

    class CountingInvestigatorClient(FakeInvestigatorClient):
        async def investigate(self, incident_id):
            investigator_calls["n"] += 1
            return await super().investigate(incident_id)

    client = TestClient(
        _build_app(control_plane=CountingControlPlaneClient(), investigator=CountingInvestigatorClient())
    )
    resp = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"
    assert body["current_node"] == "start"
    assert body["completed_nodes"] == []
    assert body["incident_id"] == str(SAMPLE_INCIDENT_ID)
    assert uuid.UUID(body["run_id"])
    assert body["thread_id"] == body["run_id"]
    assert body["resumable"] is True
    assert body["incident_snapshot"] is None
    assert body["investigation_report"] is None
    assert control_plane_calls["n"] == 0
    assert investigator_calls["n"] == 0


def test_resume_executes_a_freshly_created_run_to_completion():
    client = TestClient(_build_app())
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    assert created["status"] == "running"

    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == created["run_id"]
    assert body["status"] == "completed"
    assert body["resumable"] is False
    assert body["investigation_report"] is not None
    # Phase 8: propose_remediation always runs now, between
    # evaluate_investigation and finalize -- this test's fake client
    # never configures a tool-gateway client, so it safely finalizes
    # as remediation_status="not_applicable" (see
    # tests/test_remediation_graph.py for the paths where it doesn't).
    assert body["completed_nodes"] == [
        "load_incident",
        "run_investigation",
        "evaluate_investigation",
        "propose_remediation",
        "finalize",
    ]
    assert body["remediation_status"] == "not_applicable"


def test_create_agent_run_malformed_incident_id_is_422():
    client = TestClient(_build_app())
    resp = client.post("/api/v1/agent-runs", json={"incident_id": "not-a-uuid"})
    assert resp.status_code == 422


def test_create_agent_run_rejects_unknown_field():
    client = TestClient(_build_app())
    resp = client.post(
        "/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID), "thread_id": "caller-supplied"}
    )
    assert resp.status_code == 422


def test_two_runs_for_the_same_incident_get_different_run_ids():
    app = _build_app()
    client = TestClient(app)
    resp1 = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
    resp2 = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
    assert resp1.json()["run_id"] != resp2.json()["run_id"]


def test_get_unknown_run_id_is_404():
    client = TestClient(_build_app())
    resp = client.get(f"/api/v1/agent-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_agent_run_after_creation_matches():
    app = _build_app()
    client = TestClient(app)
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    fetched = client.get(f"/api/v1/agent-runs/{created['run_id']}").json()
    assert fetched == created


def test_history_for_unknown_run_is_404():
    client = TestClient(_build_app())
    resp = client.get(f"/api/v1/agent-runs/{uuid.uuid4()}/history")
    assert resp.status_code == 404


def test_history_is_safe_and_chronological():
    app = _build_app()
    client = TestClient(app)
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    history = client.get(f"/api/v1/agent-runs/{created['run_id']}/history").json()

    assert history["run_id"] == created["run_id"]
    assert len(history["entries"]) >= 4  # start + 4 node completions, at minimum
    steps = [e["step"] for e in history["entries"]]
    assert steps == sorted(steps)  # chronological order
    nodes = [e["node"] for e in history["entries"]]
    assert "finalize" in nodes
    # Safe metadata only -- no raw checkpoint blob/bytes ever present.
    for entry in history["entries"]:
        assert isinstance(entry["checkpoint_id"], str)
        assert "checkpoint" not in entry or not isinstance(entry.get("checkpoint"), (bytes, bytearray))


def test_resume_unknown_run_is_404():
    client = TestClient(_build_app())
    resp = client.post(f"/api/v1/agent-runs/{uuid.uuid4()}/resume")
    assert resp.status_code == 404


def test_resume_already_completed_run_is_409_and_never_re_executes():
    investigate_calls = {"n": 0}

    class CountingInvestigatorClient(FakeInvestigatorClient):
        async def investigate(self, incident_id):
            investigate_calls["n"] += 1
            return await super().investigate(incident_id)

    app = _build_app(investigator=CountingInvestigatorClient())
    client = TestClient(app)
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    completed = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume").json()
    assert investigate_calls["n"] == 1
    assert completed["status"] == "completed"

    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    assert resp.status_code == 409
    assert investigate_calls["n"] == 1  # never re-executed

    # Repeating the resume attempt again is equally safe.
    resp2 = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    assert resp2.status_code == 409
    assert investigate_calls["n"] == 1


# --- Phase 7 correction round (finding #3): transient dependency
# failures during resume are translated into a safe 503, never a
# persisted "failed" state -- the run remains fully resumable. ---------


def test_resume_returns_503_when_control_plane_temporarily_unavailable_and_remains_resumable():
    control_plane = FakeControlPlaneClient(raise_=ControlPlaneUnavailableError("could not reach control-plane"))
    client = TestClient(_build_app(control_plane=control_plane))
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()

    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    assert resp.status_code == 503
    body = resp.json()
    # Fixed, generic, safe message -- never the raw exception text.
    assert body["detail"] == "control-plane is temporarily unavailable; this agent run remains resumable"

    # The run is NOT terminal -- GET still reports it as running/resumable.
    fetched = client.get(f"/api/v1/agent-runs/{created['run_id']}").json()
    assert fetched["status"] == "running"
    assert fetched["resumable"] is True
    assert fetched["error_code"] is None

    # Recovery: control-plane becomes reachable -- resume now succeeds
    # and reaches completed, continuing from the SAME run_id.
    control_plane._raise = None
    resumed = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume").json()
    assert resumed["status"] == "completed"
    assert resumed["run_id"] == created["run_id"]


def test_resume_returns_503_when_investigator_temporarily_unavailable_and_remains_resumable():
    investigator = FakeInvestigatorClient(raise_=InvestigatorUnavailableError("investigator-service returned 503"))
    client = TestClient(_build_app(investigator=investigator))
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()

    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"] == "investigator-service is temporarily unavailable; this agent run remains resumable"

    fetched = client.get(f"/api/v1/agent-runs/{created['run_id']}").json()
    assert fetched["status"] == "running"
    assert fetched["resumable"] is True
    # load_incident already succeeded and was durably committed.
    assert fetched["incident_snapshot"] is not None
    assert fetched["completed_nodes"] == ["load_incident"]

    investigator._raise = None
    resumed = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume").json()
    assert resumed["status"] == "completed"
    assert resumed["completed_nodes"].count("load_incident") == 1


def test_resume_a_genuinely_incomplete_run_recovers_and_completes():
    """Failure injection happens through the TEST harness directly
    against the app's own graph object (Phase 7 §CHECKPOINT
    DURABILITY PROOF: "Do not add a public 'crash me' HTTP endpoint.
    Failure injection belongs only in tests / acceptance harnesses") --
    never through a real HTTP request. This proves the RESUME endpoint
    itself (not just the graph in isolation, already covered by
    test_checkpoint_durability.py / test_graph.py) correctly serves a
    genuinely incomplete run: 200, recovers, completes, never
    re-executes the already-durable load_incident step."""
    import uuid as uuid_module

    control_plane_calls = {"n": 0}

    class CountingControlPlaneClient(FakeControlPlaneClient):
        async def get_incident(self, incident_id):
            control_plane_calls["n"] += 1
            return await super().get_incident(incident_id)

    class CrashOnceInvestigatorClient:
        def __init__(self):
            self.calls = 0

        async def investigate(self, incident_id):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated transient crash (test harness only)")
            return InvestigationReport.model_validate(
                investigation_report_json(incident_id=uuid.UUID(str(incident_id)))
            )

    investigator = CrashOnceInvestigatorClient()
    app = _build_app(control_plane=CountingControlPlaneClient(), investigator=investigator)

    # Test-harness-only failure injection: invoke the app's OWN graph
    # directly (bypassing HTTP) to create a genuinely incomplete
    # checkpoint, exactly as a real mid-node process crash would leave
    # behind.
    run_id = uuid_module.uuid4()
    thread_id = str(run_id)
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "run_id": thread_id,
        "incident_id": str(SAMPLE_INCIDENT_ID),
        "status": "running",
        "started_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }
    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(app.state.graph.ainvoke(initial_state, config=config, durability="sync"))
    assert control_plane_calls["n"] == 1
    assert investigator.calls == 1

    client = TestClient(app)
    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert investigator.calls == 2
    # load_incident was never re-executed by resume -- its result was
    # already durably checkpointed.
    assert control_plane_calls["n"] == 1
