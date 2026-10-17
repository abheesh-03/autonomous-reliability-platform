"""REAL PostgreSQL + REAL LangGraph interrupt/resume durability proof
(Phase 8). Not mocked: a real `AsyncPostgresSaver` against the real
running Postgres, using THIS service's own real
`build_graph`/`AgentGraphState`/node wiring -- only the three external
HTTP clients (control-plane, investigator, tool-gateway) are fake
doubles, the same seam-based convention test_checkpoint_durability.py
already establishes. This is the file that satisfies Phase 8's own
explicit requirement: "Do not replace the real PostgreSQL checkpointer
with only InMemorySaver for persistence/HITL tests."

Scope, precisely (same honest framing as test_checkpoint_durability.py's
own docstring): one Python test process. "Instance A" and "instance B"
are two separate CheckpointStore/AsyncPostgresSaver connections, two
separate compiled graphs, created one after the other and destroyed in
between -- never a second OS process. What this proves is that
LangGraph's own real PostgreSQL checkpoint state (not Python object
identity) is the sole source of instance B's knowledge of the pending
interrupt and the proposal it is waiting on. The actual separate-
container restart proof is scripts/verify-remediation.sh.
"""

import os
import uuid

import pytest
from langgraph.types import Command

from agent_runtime_service.checkpointer import CheckpointStore
from agent_runtime_service.clients.control_plane import RemediationProposalCreateAmbiguousError
from agent_runtime_service.clients.tool_gateway import ToolGatewayAmbiguousExecutionError, ToolGatewayOutputError, ToolGatewayUnavailableError
from agent_runtime_service.config import CheckpointDbSettings, RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.domain.remediation import RemediationCapability, RemediationExecutionResult, RemediationProposal
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)


def _require_real_db() -> bool:
    return os.environ.get("AGENT_RUNTIME_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


class FakeControlPlaneClient:
    """Succeeds every time. Models exactly the two Phase 8 methods
    this test needs, backed by a trivial in-memory proposal store --
    this is NOT a test of control-plane's own real idempotency/
    atomicity (that is services/control-plane/tests/
    test_remediation_transactions.py's job against the real
    database); it only needs to behave consistently enough for THIS
    test's own real-LangGraph-checkpoint proof."""

    def __init__(self) -> None:
        self.get_incident_calls = 0
        self.create_proposal_calls = 0
        self.get_proposal_calls = 0
        self._proposal: RemediationProposal | None = None

    async def get_incident(self, incident_id):
        self.get_incident_calls += 1
        return IncidentSnapshot.model_validate(incident_json(incident_id=uuid.UUID(incident_id)))

    async def create_remediation_proposal(self, **kwargs):
        self.create_proposal_calls += 1
        if self._proposal is None:
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

    def set_decision(self, status: str) -> None:
        assert self._proposal is not None
        self._proposal = self._proposal.model_copy(update={"status": status})

    async def get_remediation_proposal(self, proposal_id):
        self.get_proposal_calls += 1
        assert self._proposal is not None and str(self._proposal.id) == str(proposal_id)
        return self._proposal


class SucceedingInvestigatorClient:
    async def investigate(self, incident_id):
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(incident_id)))


class FakeToolGatewayClient:
    """`control_plane`, if given, is advanced to "succeeded" on a real
    `execute()` call -- modeling the REAL cross-service coupling
    (tool-gateway's own execution/start+execution/result calls
    genuinely advance control-plane's durable proposal record) a fake
    tool-gateway talking to a logically separate fake control-plane
    object would not otherwise reproduce; without this,
    verify_recovery's own independent re-fetch would see a stale
    'approved' status forever."""

    def __init__(
        self,
        *,
        precondition_met: bool = True,
        target_healthy: bool = True,
        control_plane: "FakeControlPlaneClient | None" = None,
    ) -> None:
        self._precondition_met = precondition_met
        self._target_healthy = target_healthy
        self._control_plane = control_plane
        self.execute_calls = 0

    async def get_capability(self):
        return RemediationCapability.model_validate(
            {
                "action_type": "clear_payment_authorization_fault",
                "target": "payment-service",
                "precondition_met": self._precondition_met,
                "target_healthy": self._target_healthy,
            }
        )

    async def execute(self, proposal_id):
        self.execute_calls += 1
        if self._control_plane is not None:
            self._control_plane.set_decision("succeeded")
        # Models the real tool-gateway/payment-service coupling: a
        # successful execute() genuinely cleared the controlled fault,
        # so an independent capability re-check afterward
        # (verify_recovery) must see precondition_met=False now.
        self._precondition_met = False
        return RemediationExecutionResult.model_validate(
            {"proposal_id": proposal_id, "status": "succeeded", "detail": "fault cleared and verified"}
        )


@pytest.fixture
async def db_settings():
    password = os.environ.get("POSTGRES_PASSWORD", "")
    user = os.environ.get("POSTGRES_USER", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (password and user and database):
        _unavailable(
            "no real POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB configured -- skipping the real "
            "PostgreSQL remediation interrupt/resume durability test"
        )

    runtime_user = os.environ.get("AGENT_RUNTIME_DB_USER", "")
    runtime_password = os.environ.get("AGENT_RUNTIME_DB_PASSWORD", "")
    if not (runtime_user and runtime_password):
        _unavailable(
            "no real AGENT_RUNTIME_DB_USER/AGENT_RUNTIME_DB_PASSWORD configured -- skipping the real "
            "PostgreSQL remediation interrupt/resume durability test (run scripts/init-agent-runtime-db.sh "
            "against the real stack first)"
        )
        return  # pragma: no cover

    settings = CheckpointDbSettings(
        host=os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
        port=int(os.environ.get("AGENT_RUNTIME_DB_PORT", "5432")),
        user=runtime_user,
        password=runtime_password,
        database=database,
        schema="agent_runtime",
        pool_min_size=1,
        pool_max_size=4,
        pool_open_timeout_seconds=10.0,
    )
    try:
        probe = CheckpointStore(settings)
        await probe.open()
        await probe.close()
    except Exception as exc:  # noqa: BLE001
        _unavailable(f"real checkpoint database not reachable: {exc}")

    return settings


def _initial_state(thread_id: str) -> dict:
    return {
        "run_id": thread_id,
        "incident_id": str(SAMPLE_INCIDENT_ID),
        "status": "running",
        "started_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }


async def test_real_interrupt_pauses_durably_and_survives_process_destruction_then_approves(db_settings):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # --- Instance A: runs all the way to the real interrupt ---
    control_plane_a = FakeControlPlaneClient()
    tool_gateway_a = FakeToolGatewayClient(precondition_met=True)
    store_a = CheckpointStore(db_settings)
    saver_a = await store_a.open()
    graph_a = compile_graph(control_plane_a, SucceedingInvestigatorClient(), BOUNDS, saver_a, tool_gateway_a)

    result = await graph_a.ainvoke(_initial_state(thread_id), config=config, durability="sync")
    # ainvoke on an interrupted graph returns the values as of the
    # interrupt, with an `__interrupt__` key present.
    assert "__interrupt__" in result

    snap = await graph_a.aget_state(config)
    assert snap.next == ("await_human_approval",)
    assert len(snap.interrupts) == 1
    proposal_id = snap.values["remediation_proposal_id"]
    assert proposal_id is not None
    assert snap.interrupts[0].value["proposal_id"] == proposal_id
    assert snap.values["remediation_status"] == "pending_approval"

    # --- Destroy instance A completely ---
    await store_a.close()
    del store_a, saver_a, graph_a

    # --- Instance B: brand new connection, SAME thread_id ---
    control_plane_b = FakeControlPlaneClient()
    control_plane_b._proposal = control_plane_a._proposal  # the TRUSTED record control-plane itself would hold
    tool_gateway_b = FakeToolGatewayClient(precondition_met=True, control_plane=control_plane_b)
    store_b = CheckpointStore(db_settings)
    saver_b = await store_b.open()
    graph_b = compile_graph(control_plane_b, SucceedingInvestigatorClient(), BOUNDS, saver_b, tool_gateway_b)

    snap_b = await graph_b.aget_state(config)
    assert snap_b.next == ("await_human_approval",)
    assert len(snap_b.interrupts) == 1
    assert snap_b.values["remediation_proposal_id"] == proposal_id

    # --- Resume with a REAL trusted 'approved' decision ---
    control_plane_b.set_decision("approved")
    final = await graph_b.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["status"] == "completed"
    assert final["approval_decision"] == "approved"
    assert final["remediation_status"] == "succeeded"
    assert final["execution_result"]["status"] == "succeeded"
    assert final["recovery_verification"] == {
        "proposal_succeeded": True,
        "fault_inactive": True,
        "target_healthy": True,
    }
    assert tool_gateway_b.execute_calls == 1

    final_snap = await graph_b.aget_state(config)
    assert final_snap.next == ()  # terminal, never resumable again

    await store_b.close()


async def test_real_interrupt_resumes_to_rejected_without_ever_executing(db_settings):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    store = CheckpointStore(db_settings)
    saver = await store.open()
    graph = compile_graph(control_plane, SucceedingInvestigatorClient(), BOUNDS, saver, tool_gateway)

    await graph.ainvoke(_initial_state(thread_id), config=config, durability="sync")
    snap = await graph.aget_state(config)
    proposal_id = snap.values["remediation_proposal_id"]

    control_plane.set_decision("rejected")
    final = await graph.ainvoke(
        Command(resume={"decision": "rejected", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["status"] == "completed"
    assert final["approval_decision"] == "rejected"
    assert final["remediation_status"] == "rejected"
    # No execution ever attempted -- no tool-gateway call, no
    # execution_result, no recovery_verification.
    assert tool_gateway.execute_calls == 0
    assert final.get("execution_result") is None
    assert final.get("recovery_verification") is None

    await store.close()


async def test_execute_remediation_crash_leaves_thread_resumable_at_the_same_node(db_settings):
    """The real TRANSIENT/RETRYABLE convention extended to Phase 8:
    ToolGatewayUnavailableError is left uncaught by execute_remediation
    -- the checkpoint stays resumable at that exact node, same as
    ControlPlaneUnavailableError/InvestigatorUnavailableError already
    prove for Phase 7's own nodes."""
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    class FlakyToolGatewayClient(FakeToolGatewayClient):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.should_fail = True

        async def execute(self, proposal_id):
            if self.should_fail:
                self.execute_calls += 1
                raise ToolGatewayUnavailableError("simulated transient outage (test-only failure injection)")
            return await super().execute(proposal_id)

    control_plane = FakeControlPlaneClient()
    tool_gateway = FlakyToolGatewayClient(precondition_met=True, control_plane=control_plane)
    store = CheckpointStore(db_settings)
    saver = await store.open()
    graph = compile_graph(control_plane, SucceedingInvestigatorClient(), BOUNDS, saver, tool_gateway)

    await graph.ainvoke(_initial_state(thread_id), config=config, durability="sync")
    snap = await graph.aget_state(config)
    proposal_id = snap.values["remediation_proposal_id"]
    control_plane.set_decision("approved")

    with pytest.raises(ToolGatewayUnavailableError):
        await graph.ainvoke(
            Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
        )

    snap_after_crash = await graph.aget_state(config)
    assert snap_after_crash.next == ("execute_remediation",)
    assert snap_after_crash.values["approval_decision"] == "approved"
    assert tool_gateway.execute_calls == 1

    # Recovery: tool-gateway becomes reachable again -- the SAME
    # thread resumes WITHOUT re-interrupting (the interrupt was
    # already answered; LangGraph does not re-raise it).
    tool_gateway.should_fail = False
    final = await graph.ainvoke(None, config=config, durability="sync")
    assert final["status"] == "completed"
    assert final["remediation_status"] == "succeeded"

    await store.close()


async def test_propose_remediation_create_ambiguous_response_leaves_thread_resumable(db_settings):
    """Phase 8 correction round (finding #2), scenario A -- the
    authoritative, REAL `AsyncPostgresSaver` proof: control-plane's own
    create-proposal endpoint already commits the proposal BEFORE ever
    building its HTTP response, so an ambiguous response (malformed
    body, HTTP 5xx) must never terminalize the run. This must raise
    (never return a terminal 'failed' dict), leaving the REAL
    checkpoint resumable at propose_remediation -- and a retried
    resume (the SAME idempotency_key, since it is derived solely from
    run_id) converges cleanly once control-plane becomes reachable
    again."""
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    class FlakyCreateControlPlaneClient(FakeControlPlaneClient):
        def __init__(self) -> None:
            super().__init__()
            self.should_fail = True

        async def create_remediation_proposal(self, **kwargs):
            if self.should_fail:
                self.create_proposal_calls += 1
                raise RemediationProposalCreateAmbiguousError("malformed create response (simulated, test-only)")
            return await super().create_remediation_proposal(**kwargs)

    control_plane = FlakyCreateControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True, control_plane=control_plane)
    store = CheckpointStore(db_settings)
    saver = await store.open()
    graph = compile_graph(control_plane, SucceedingInvestigatorClient(), BOUNDS, saver, tool_gateway)

    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await graph.ainvoke(_initial_state(thread_id), config=config, durability="sync")

    snap_after_failure = await graph.aget_state(config)
    assert snap_after_failure.next == ("propose_remediation",)
    assert snap_after_failure.values.get("remediation_proposal_id") is None
    assert control_plane.create_proposal_calls == 1

    # Recovery: control-plane becomes reachable again -- the SAME
    # thread resumes and successfully creates the proposal.
    control_plane.should_fail = False
    final = await graph.ainvoke(None, config=config, durability="sync")
    assert "__interrupt__" in final
    assert control_plane.create_proposal_calls == 2
    snap_after_recovery = await graph.aget_state(config)
    assert snap_after_recovery.values["remediation_status"] == "pending_approval"
    assert snap_after_recovery.values.get("remediation_proposal_id") is not None

    await store.close()


async def test_execute_remediation_ambiguous_response_still_in_flight_leaves_thread_resumable(db_settings):
    """Phase 8 correction round (finding #1), scenario A -- the
    authoritative, REAL `AsyncPostgresSaver` proof (never only
    InMemorySaver, per the correction's own explicit requirement):
    tool-gateway's execute() response is ambiguous (ToolGatewayOutputError),
    and on independent reconciliation control-plane's own durable
    proposal record STILL reports 'executing' -- genuinely unknown
    whether the real action has finished. This must raise
    ToolGatewayAmbiguousExecutionError (never return a terminal
    'failed' dict), leaving the REAL checkpoint resumable at the exact
    same node."""
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    class AmbiguousToolGatewayClient(FakeToolGatewayClient):
        async def execute(self, proposal_id):
            self.execute_calls += 1
            raise ToolGatewayOutputError("malformed execute response (simulated, test-only)")

    control_plane = FakeControlPlaneClient()
    tool_gateway = AmbiguousToolGatewayClient(precondition_met=True)
    store = CheckpointStore(db_settings)
    saver = await store.open()
    graph = compile_graph(control_plane, SucceedingInvestigatorClient(), BOUNDS, saver, tool_gateway)

    await graph.ainvoke(_initial_state(thread_id), config=config, durability="sync")
    snap = await graph.aget_state(config)
    proposal_id = snap.values["remediation_proposal_id"]

    # control-plane's own durable record genuinely still says
    # 'executing' (e.g. execution/start already succeeded, but the
    # tool-gateway process crashed/lost connectivity before ever
    # recording a result) -- never "succeeded"/"failed" at this point.
    # This test calls graph.ainvoke directly with an explicit
    # Command(resume=...), the same convention every other test in
    # this file already uses, so control-plane's record is never
    # consulted to BUILD that Command (only api/agent_runs.py does
    # that) -- it only matters for execute_remediation's own
    # reconciliation re-fetch below.
    control_plane.set_decision("executing")

    with pytest.raises(ToolGatewayAmbiguousExecutionError):
        await graph.ainvoke(
            Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
        )

    snap_after = await graph.aget_state(config)
    assert snap_after.next == ("execute_remediation",)
    assert tool_gateway.execute_calls == 1

    await store.close()
