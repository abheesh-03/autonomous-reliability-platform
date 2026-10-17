"""API-contract tests for Phase 8's human-approval resume gate
(api/agent_runs.py::resume_agent_run). Same convention
test_api_agent_runs.py already establishes: a minimal FastAPI app
wired directly to a real compiled graph (InMemorySaver -- persistence
itself is proven for real in test_remediation_durability.py) plus fake
control-plane/investigator/tool-gateway doubles.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent_runtime_service.api.agent_runs import router as agent_runs_router
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.domain.remediation import RemediationCapability, RemediationExecutionResult, RemediationProposal
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)


class FakeControlPlaneClient:
    def __init__(self) -> None:
        self._proposal: RemediationProposal | None = None
        self.get_proposal_calls = 0

    async def get_incident(self, incident_id):
        return IncidentSnapshot.model_validate(incident_json(incident_id=uuid.UUID(incident_id)))

    async def create_remediation_proposal(self, **kwargs):
        self._proposal = RemediationProposal.model_validate(
            {
                "id": str(uuid.uuid4()),
                "incident_id": kwargs["incident_id"],
                "agent_run_id": kwargs["agent_run_id"],
                "action_type": kwargs["action_type"],
                "target": kwargs["target"],
                "status": "pending_approval",
            }
        )
        return self._proposal

    def decide(self, decision: str) -> None:
        assert self._proposal is not None
        self._proposal = self._proposal.model_copy(update={"status": decision})

    async def get_remediation_proposal(self, proposal_id):
        self.get_proposal_calls += 1
        assert self._proposal is not None
        return self._proposal


class FakeInvestigatorClient:
    async def investigate(self, incident_id):
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(str(incident_id))))


class FakeToolGatewayClient:
    """`control_plane`, if given, is mutated to "succeeded" on a real
    `execute()` call -- modeling the REAL cross-service coupling
    (tool-gateway's own execution/start+execution/result calls
    actually advance control-plane's durable proposal record) that a
    fake tool-gateway talking to a SEPARATE fake control-plane object
    would otherwise never reproduce. Without this, verify_recovery's
    own independent re-fetch of the proposal would see a stale
    'approved' status forever -- exactly the kind of test-fake
    infidelity a real integration (scripts/verify-remediation.sh)
    exists to catch for real."""

    def __init__(self, control_plane: "FakeControlPlaneClient | None" = None) -> None:
        self.execute_calls = 0
        self._control_plane = control_plane
        self._precondition_met = True

    async def get_capability(self):
        return RemediationCapability.model_validate(
            {
                "action_type": "clear_payment_authorization_fault",
                "target": "payment-service",
                "precondition_met": self._precondition_met,
                "target_healthy": True,
            }
        )

    async def execute(self, proposal_id):
        self.execute_calls += 1
        if self._control_plane is not None:
            self._control_plane.decide("succeeded")
        # Models the real tool-gateway/payment-service coupling: a
        # successful execute() genuinely cleared the controlled fault.
        self._precondition_met = False
        return RemediationExecutionResult.model_validate(
            {"proposal_id": proposal_id, "status": "succeeded", "detail": "cleared"}
        )


def _build_app(control_plane=None, tool_gateway=None, saver=None):
    app = FastAPI()
    app.include_router(agent_runs_router)
    control_plane = control_plane or FakeControlPlaneClient()
    graph = compile_graph(
        control_plane, FakeInvestigatorClient(), BOUNDS, saver or InMemorySaver(), tool_gateway or FakeToolGatewayClient()
    )
    app.state.graph = graph
    app.state.runtime_bounds = BOUNDS
    app.state.control_plane_client = control_plane
    return app, control_plane


def _create_and_reach_interrupt(client):
    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")
    return created["run_id"], resp


def test_get_run_reports_waiting_for_approval_with_the_real_pending_interrupt():
    app, _control_plane = _build_app()
    client = TestClient(app)
    run_id, resp = _create_and_reach_interrupt(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_approval"
    assert body["remediation_proposal_id"] is not None
    assert body["remediation_action_type"] == "clear_payment_authorization_fault"
    assert body["remediation_target"] == "payment-service"
    assert body["resumable"] is True

    fetched = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert fetched["status"] == "waiting_for_approval"
    assert fetched["remediation_proposal_id"] == body["remediation_proposal_id"]


def test_resume_while_pending_approval_returns_409_and_never_executes():
    app, control_plane = _build_app()
    client = TestClient(app)
    run_id, _ = _create_and_reach_interrupt(client)

    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume")
    assert resp.status_code == 409
    assert "approval_pending" in resp.json()["detail"]

    # Still waiting for the SAME proposal -- nothing advanced.
    fetched = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert fetched["status"] == "waiting_for_approval"


def test_resume_cannot_be_bypassed_by_a_caller_supplied_body():
    """Phase 8 §HUMAN DECISION SOURCE OF TRUTH: the resume endpoint
    has NO decision field at all -- POSTing one must have zero
    effect. The proposal remains pending_approval regardless."""
    app, control_plane = _build_app()
    client = TestClient(app)
    run_id, _ = _create_and_reach_interrupt(client)

    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume", json={"approved": True, "decision": "approved"})
    assert resp.status_code == 409
    assert "approval_pending" in resp.json()["detail"]

    fetched = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert fetched["status"] == "waiting_for_approval"
    assert fetched["remediation_status"] == "pending_approval"


def test_resume_after_trusted_approval_executes_and_completes():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(control_plane=control_plane)
    app, control_plane = _build_app(control_plane=control_plane, tool_gateway=tool_gateway)
    client = TestClient(app)
    run_id, _ = _create_and_reach_interrupt(client)

    control_plane.decide("approved")
    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["remediation_status"] == "succeeded"
    assert body["execution_result"]["status"] == "succeeded"
    assert body["recovery_verification"] == {
        "proposal_succeeded": True,
        "fault_inactive": True,
        "target_healthy": True,
    }
    assert tool_gateway.execute_calls == 1
    assert body["resumable"] is False


def test_resume_after_trusted_rejection_finalizes_without_ever_executing():
    tool_gateway = FakeToolGatewayClient()
    app, control_plane = _build_app(tool_gateway=tool_gateway)
    client = TestClient(app)
    run_id, _ = _create_and_reach_interrupt(client)

    control_plane.decide("rejected")
    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["remediation_status"] == "rejected"
    assert tool_gateway.execute_calls == 0
    assert body.get("execution_result") is None


def test_resume_with_ambiguous_proposal_create_response_returns_503_and_remains_resumable():
    """Phase 8 correction round (finding #2), point D: an ambiguous
    remediation-proposal CREATE response (control-plane already
    committed, but the response itself was lost/malformed) must come
    back as a safe 503 -- never a 500, never a raw response body or
    credential, and the run must still report `resumable=True`, never
    a persisted terminal failure."""
    from agent_runtime_service.clients.control_plane import RemediationProposalCreateAmbiguousError

    class AmbiguousCreateControlPlaneClient(FakeControlPlaneClient):
        async def create_remediation_proposal(self, **kwargs):
            raise RemediationProposalCreateAmbiguousError("malformed create response (simulated, test-only)")

    control_plane = AmbiguousCreateControlPlaneClient()
    app, _ = _build_app(control_plane=control_plane)
    client = TestClient(app)

    created = client.post("/api/v1/agent-runs", json={"incident_id": str(SAMPLE_INCIDENT_ID)}).json()
    resp = client.post(f"/api/v1/agent-runs/{created['run_id']}/resume")

    assert resp.status_code == 503
    body = resp.json()
    assert "resumable" in body["detail"]
    assert "Bearer" not in body["detail"]

    fetched = client.get(f"/api/v1/agent-runs/{created['run_id']}").json()
    assert fetched["resumable"] is True
    assert fetched["remediation_proposal_id"] is None


def test_resume_with_ambiguous_tool_gateway_response_still_in_flight_returns_503_and_remains_resumable():
    """Phase 8 correction round (finding #1) at the API layer: an
    ambiguous tool-gateway execute() response that reconciles to
    'still in flight' (control-plane reports 'executing') must come
    back as a safe 503 -- never a 500, and never a persisted terminal
    failure -- and the run must still report `resumable=True`."""
    from agent_runtime_service.clients.tool_gateway import ToolGatewayOutputError

    class TwoStageControlPlaneClient(FakeControlPlaneClient):
        """First get_remediation_proposal call is resume_agent_run's
        OWN pre-check (must see 'approved' to build the trusted resume
        Command); every call after that is execute_remediation's own
        reconciliation re-fetch, simulating that execution/start had
        already genuinely advanced the proposal to 'executing' by the
        time the ambiguous tool-gateway response arrived."""

        async def get_remediation_proposal(self, proposal_id):
            self.get_proposal_calls += 1
            assert self._proposal is not None
            if self.get_proposal_calls == 1:
                return self._proposal.model_copy(update={"status": "approved"})
            return self._proposal.model_copy(update={"status": "executing"})

    class AmbiguousToolGatewayClient(FakeToolGatewayClient):
        async def execute(self, proposal_id):
            self.execute_calls += 1
            raise ToolGatewayOutputError("malformed execute response (simulated, test-only)")

    control_plane = TwoStageControlPlaneClient()
    tool_gateway = AmbiguousToolGatewayClient(control_plane=control_plane)
    app, control_plane = _build_app(control_plane=control_plane, tool_gateway=tool_gateway)
    client = TestClient(app)
    run_id, _ = _create_and_reach_interrupt(client)

    control_plane.decide("approved")
    resp = client.post(f"/api/v1/agent-runs/{run_id}/resume")

    assert resp.status_code == 503
    assert "resumable" in resp.json()["detail"]

    fetched = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert fetched["resumable"] is True


def test_same_run_id_still_waits_for_the_same_proposal_after_a_fresh_graph_object():
    """Simulates the 'agent-runtime-service restarted' scenario at the
    API layer: a brand-new app/graph object, but the SAME underlying
    checkpoint store (here, the same InMemorySaver instance -- the
    real container-restart proof against a real AsyncPostgresSaver is
    test_remediation_durability.py). The same run_id must still report
    the same waiting state and the same proposal id."""
    shared_saver = InMemorySaver()
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(control_plane=control_plane)

    app1, _ = _build_app(control_plane=control_plane, tool_gateway=tool_gateway, saver=shared_saver)
    client1 = TestClient(app1)
    run_id, resp1 = _create_and_reach_interrupt(client1)
    proposal_id = resp1.json()["remediation_proposal_id"]

    # "Restart": a completely new app/graph, same saver, same control-plane record.
    app2, _ = _build_app(
        control_plane=control_plane, tool_gateway=FakeToolGatewayClient(control_plane=control_plane), saver=shared_saver
    )
    client2 = TestClient(app2)

    fetched = client2.get(f"/api/v1/agent-runs/{run_id}").json()
    assert fetched["status"] == "waiting_for_approval"
    assert fetched["remediation_proposal_id"] == proposal_id

    control_plane.decide("approved")
    resumed = client2.post(f"/api/v1/agent-runs/{run_id}/resume").json()
    assert resumed["status"] == "completed"
    assert resumed["remediation_status"] == "succeeded"
