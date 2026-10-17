"""Phase 8 node-logic/routing unit tests -- real `build_graph`/node
wiring, `InMemorySaver` (Phase 7 §LANGGRAPH: fine for FOCUSED unit
tests where persistence/HITL-durability itself is not under test --
that real-PostgreSQL proof is test_remediation_durability.py, not
here). Fake control-plane/investigator/tool-gateway client doubles.
"""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_runtime_service.clients.control_plane import (
    ControlPlaneOutputError,
    RemediationProposalConflictError,
    RemediationProposalCreateAmbiguousError,
    RemediationProposalNotFoundError,
)
from agent_runtime_service.clients.tool_gateway import (
    ToolGatewayAmbiguousExecutionError,
    ToolGatewayOutputError,
    ToolGatewayRefusedError,
)
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.domain.remediation import RemediationCapability, RemediationExecutionResult, RemediationProposal
from agent_runtime_service.graph.build import compile_graph
from agent_runtime_service.graph.nodes import (
    _collect_supporting_context_ids,
    _collect_supporting_evidence_ids,
    route_after_await_human_approval,
    route_after_execute_remediation,
    route_after_propose_remediation,
)
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)


class FakeControlPlaneClient:
    def __init__(self, *, incident_overrides=None, create_raise=None, get_raise=None, get_status="succeeded"):
        self._incident_overrides = incident_overrides or {}
        self._create_raise = create_raise
        self._get_raise = get_raise
        # The status get_remediation_proposal reports on the NEXT call
        # -- defaults to "succeeded" (the common case every pre-
        # existing test in this file relies on); tests exercising the
        # ambiguous-execute-response reconciliation path (Phase 8
        # correction round, finding #1) override it via
        # `set_get_status`.
        self._get_status = get_status
        self.create_calls = 0
        self.get_calls = 0
        self._proposal: RemediationProposal | None = None

    def set_get_status(self, status: str) -> None:
        self._get_status = status

    async def get_incident(self, incident_id):
        return IncidentSnapshot.model_validate(
            incident_json(incident_id=uuid.UUID(incident_id), **self._incident_overrides)
        )

    async def create_remediation_proposal(self, **kwargs):
        self.create_calls += 1
        if self._create_raise:
            raise self._create_raise
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

    async def get_remediation_proposal(self, proposal_id):
        self.get_calls += 1
        if self._get_raise:
            raise self._get_raise
        return self._proposal.model_copy(update={"status": self._get_status})


class FakeInvestigatorClient:
    async def investigate(self, incident_id):
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(incident_id)))


class FakeToolGatewayClient:
    def __init__(
        self,
        *,
        precondition_met=True,
        target_healthy=True,
        capability_raise=None,
        execute_raise=None,
        execute_status="succeeded",
        flips_precondition_on_raise=False,
    ):
        self._precondition_met = precondition_met
        self._target_healthy = target_healthy
        self._capability_raise = capability_raise
        self._execute_raise = execute_raise
        self._execute_status = execute_status
        # Only for scenario-B-style tests (Phase 8 correction round,
        # finding #1): the real action genuinely DID happen -- only
        # the response describing it was lost/malformed -- so an
        # independent capability re-check afterward must ALSO see the
        # fault as cleared, even though this fake's own execute() call
        # raises rather than returning normally.
        self._flips_precondition_on_raise = flips_precondition_on_raise
        self.execute_calls = 0

    async def get_capability(self):
        if self._capability_raise:
            raise self._capability_raise
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
        if self._execute_raise:
            if self._flips_precondition_on_raise:
                self._precondition_met = False
            raise self._execute_raise
        if self._execute_status == "succeeded":
            # Models the REAL tool-gateway/payment-service coupling:
            # a successful execute() genuinely cleared the controlled
            # fault, so an independent capability re-check afterward
            # (verify_recovery) must see precondition_met=False now --
            # never the same "fault is active" value it reported
            # beforehand.
            self._precondition_met = False
        return RemediationExecutionResult.model_validate(
            {"proposal_id": proposal_id, "status": self._execute_status, "detail": "ok"}
        )


def _initial_state():
    return {
        "run_id": str(uuid.uuid4()),
        "incident_id": str(SAMPLE_INCIDENT_ID),
        "status": "running",
        "started_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }


async def _run(control_plane, investigator, tool_gateway):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, investigator, BOUNDS, InMemorySaver(), tool_gateway)
    result = await graph.ainvoke(_initial_state(), config=config, durability="sync")
    return graph, config, result


# ---------------------------------------------------------------------
# Deterministic policy
# ---------------------------------------------------------------------


async def test_policy_matches_creates_a_real_proposal_and_interrupts():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)

    assert "__interrupt__" in result
    assert control_plane.create_calls == 1
    snap = await graph.aget_state(config)
    assert snap.next == ("await_human_approval",)
    assert snap.values["remediation_status"] == "pending_approval"
    assert snap.values["remediation_action_type"] == "clear_payment_authorization_fault"
    assert snap.values["remediation_target"] == "payment-service"


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": "manual"},
        {"severity": "warning"},
        {"title": "some other alert entirely"},
    ],
)
async def test_policy_does_not_match_finalizes_as_not_applicable(overrides):
    control_plane = FakeControlPlaneClient(incident_overrides=overrides)
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    _graph, _config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)

    assert result["status"] == "completed"
    assert result["remediation_status"] == "not_applicable"
    assert control_plane.create_calls == 0
    assert "await_human_approval" not in result["completed_nodes"]


async def test_precondition_not_met_finalizes_as_not_applicable_without_creating_a_proposal():
    """Phase 8 §DETERMINISTIC ACTION POLICY: never fabricates a
    proposal merely because the incident/investigation LOOK right --
    tool-gateway's own independent, real precondition report is the
    deciding factor."""
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=False)
    _graph, _config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)

    assert result["remediation_status"] == "not_applicable"
    assert control_plane.create_calls == 0


async def test_tool_gateway_output_error_during_capability_check_is_terminal():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(capability_raise=ToolGatewayOutputError("malformed capability response"))
    _graph, _config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)

    assert result["status"] == "failed"
    assert result["error_code"] == "tool_gateway_output_invalid"


async def test_proposal_idempotency_conflict_is_terminal():
    control_plane = FakeControlPlaneClient(create_raise=RemediationProposalConflictError("idempotency conflict"))
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    _graph, _config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)

    assert result["status"] == "failed"
    assert result["error_code"] == "remediation_proposal_conflict"


async def test_remediation_proposal_create_ambiguous_response_leaves_run_resumable_at_propose_remediation():
    """Phase 8 correction round (finding #2): control-plane's own
    create-proposal endpoint already commits the proposal + its
    'proposed' event BEFORE ever building its HTTP response -- an
    ambiguous response (HTTP 5xx, malformed body, shape-invalid body)
    must NEVER terminalize the run. This must raise (never return a
    terminal 'failed' dict) so the node's checkpoint is never
    committed."""
    control_plane = FakeControlPlaneClient(
        create_raise=RemediationProposalCreateAmbiguousError("malformed create response (simulated, test-only)")
    )
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, FakeInvestigatorClient(), BOUNDS, InMemorySaver(), tool_gateway)

    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await graph.ainvoke(_initial_state(), config=config, durability="sync")

    snap = await graph.aget_state(config)
    assert snap.next == ("propose_remediation",)


async def test_control_plane_output_error_is_not_raised_by_proposal_creation():
    """Documents the correction round's own boundary (finding #2):
    `ControlPlaneOutputError` is reserved for READ-ONLY GET shape
    failures elsewhere in this module (load_incident, verify_recovery)
    -- the real client never raises it from create_remediation_proposal
    any more (only RemediationProposalConflictError or
    RemediationProposalCreateAmbiguousError), so propose_remediation no
    longer catches it for this call at all. A fake that still raised it
    here would propagate uncaught (same as any other unclassified
    exception), which this test demonstrates directly."""
    control_plane = FakeControlPlaneClient(create_raise=ControlPlaneOutputError("shape mismatch"))
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, FakeInvestigatorClient(), BOUNDS, InMemorySaver(), tool_gateway)

    with pytest.raises(ControlPlaneOutputError):
        await graph.ainvoke(_initial_state(), config=config, durability="sync")


# ---------------------------------------------------------------------
# await_human_approval: approve / reject
# ---------------------------------------------------------------------


async def test_approved_resume_executes_and_completes():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["approval_decision"] == "approved"
    assert final["status"] == "completed"
    assert final["execution_result"]["status"] == "succeeded"
    assert final["recovery_verification"] == {
        "proposal_succeeded": True,
        "fault_inactive": True,
        "target_healthy": True,
    }
    assert final["remediation_status"] == "succeeded"
    assert tool_gateway.execute_calls == 1


async def test_rejected_resume_never_executes():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "rejected", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["approval_decision"] == "rejected"
    assert final["remediation_status"] == "rejected"
    assert final["status"] == "completed"
    assert tool_gateway.execute_calls == 0
    assert final.get("execution_result") is None


async def test_malformed_resume_decision_value_is_treated_as_rejected_never_as_approved():
    """Defense in depth: even if something resumed this interrupt with
    a decision value that is neither 'approved' nor 'rejected', the
    node must NEVER default to executing anything."""
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(precondition_met=True)
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "something-unexpected", "proposal_id": proposal_id}),
        config=config,
        durability="sync",
    )

    assert final["approval_decision"] == "rejected"
    assert tool_gateway.execute_calls == 0


# ---------------------------------------------------------------------
# execute_remediation / verify_recovery
# ---------------------------------------------------------------------


async def test_execute_remediation_refused_records_failed_remediation_status_but_run_completes():
    control_plane = FakeControlPlaneClient()
    tool_gateway = FakeToolGatewayClient(
        precondition_met=True, execute_raise=ToolGatewayRefusedError(409, "post-clear verification failed")
    )
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    # A real, understood remediation failure is NOT the same as this
    # agent RUN failing internally -- the run still completed its job.
    assert final["status"] == "completed"
    assert final["remediation_status"] == "failed"
    assert final["execution_result"]["status"] == "failed"
    assert "verification failed" in final["execution_result"]["detail"]
    # verify_recovery still runs (route_after_execute_remediation sends
    # a non-terminal remediation failure straight through to it anyway
    # per the routing table), but there's nothing to independently
    # verify since execution_result.status != "succeeded".
    assert final["recovery_verification"] == {
        "proposal_succeeded": False,
        "fault_inactive": False,
        "target_healthy": False,
    }


async def test_execute_remediation_ambiguous_response_reconciles_to_succeeded_without_reexecuting():
    """Phase 8 correction round (finding #1), scenario B: the execute()
    response itself was lost/malformed, but control-plane's own
    durable record ALREADY says 'succeeded' (e.g. the response was
    lost in transit after execution/result was recorded) -- the agent
    must reconcile to the REAL outcome, never terminalize the run, and
    never invoke a second/destructive action. The real action genuinely
    DID happen in this scenario (only the response was lost), so
    tool-gateway's own independent capability re-check (used by
    verify_recovery, correction round finding #2) must ALSO reflect
    that -- modeled here via `precondition_met=False` from the start,
    since this fake's own `execute()` never returns normally to flip it
    itself."""
    control_plane = FakeControlPlaneClient(get_status="succeeded")
    tool_gateway = FakeToolGatewayClient(
        precondition_met=True,
        execute_raise=ToolGatewayOutputError("malformed execute response"),
        flips_precondition_on_raise=True,
    )
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["status"] == "completed"
    assert final["execution_result"]["status"] == "succeeded"
    assert final["remediation_status"] == "succeeded"
    assert final["recovery_verification"] == {
        "proposal_succeeded": True,
        "fault_inactive": True,
        "target_healthy": True,
    }
    assert tool_gateway.execute_calls == 1  # never retried/re-invoked


async def test_execute_remediation_ambiguous_response_reconciles_to_failed_accurately():
    """Scenario C: the execute() response was ambiguous, and
    control-plane's own durable record says 'failed' -- the real
    durable failure is reported accurately, never masked as a
    terminal agent-run failure."""
    control_plane = FakeControlPlaneClient(get_status="failed")
    tool_gateway = FakeToolGatewayClient(
        precondition_met=True, execute_raise=ToolGatewayOutputError("malformed execute response")
    )
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["status"] == "completed"  # the RUN itself still completed its job
    assert final["execution_result"]["status"] == "failed"
    assert final["remediation_status"] == "failed"


async def test_execute_remediation_ambiguous_response_still_in_flight_raises_and_stays_resumable():
    """Scenario A (unit-level sanity check; the real, authoritative
    proof against a REAL AsyncPostgresSaver checkpoint lives in
    test_remediation_durability.py per Phase 8's own explicit
    requirement): control-plane still reports 'executing' -- genuinely
    unknown whether the action has finished -- so this must raise
    (never return a terminal 'failed' dict) so the node's checkpoint
    is never committed."""
    control_plane = FakeControlPlaneClient(get_status="executing")
    tool_gateway = FakeToolGatewayClient(
        precondition_met=True, execute_raise=ToolGatewayOutputError("malformed execute response")
    )
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    with pytest.raises(ToolGatewayAmbiguousExecutionError):
        await graph.ainvoke(
            Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
        )

    snap = await graph.aget_state(config)
    assert snap.next == ("execute_remediation",)


async def test_execute_remediation_control_plane_not_found_during_reconciliation_is_terminal():
    control_plane = FakeControlPlaneClient(get_raise=RemediationProposalNotFoundError("gone"))
    tool_gateway = FakeToolGatewayClient(
        precondition_met=True, execute_raise=ToolGatewayOutputError("malformed execute response")
    )
    graph, config, result = await _run(control_plane, FakeInvestigatorClient(), tool_gateway)
    proposal_id = (await graph.aget_state(config)).values["remediation_proposal_id"]

    final = await graph.ainvoke(
        Command(resume={"decision": "approved", "proposal_id": proposal_id}), config=config, durability="sync"
    )

    assert final["status"] == "failed"
    assert final["error_code"] == "remediation_proposal_not_found"


# ---------------------------------------------------------------------
# Provenance extraction (Phase 8 correction round, finding #5)
# ---------------------------------------------------------------------


def _provenance_report() -> dict:
    return {
        "observations": [{"statement": "a confirmed fact", "evidence_ids": ["E1"]}],
        "hypotheses": [
            {
                "statement": "a plausible cause",
                "supporting_evidence_ids": ["E2"],
                "conflicting_evidence_ids": ["E3"],
                "supporting_context_ids": ["K1"],
                "conflicting_context_ids": ["H1"],
                "confidence": "medium",
            }
        ],
        "retrieval_context": {
            "knowledge": [{"context_id": "K1"}, {"context_id": "K2"}],
            "historical_incidents": [{"context_id": "H1"}, {"context_id": "H2"}],
            "outcome": "ok",
        },
    }


def test_collect_supporting_evidence_ids_includes_observations_and_hypothesis_support_only():
    assert _collect_supporting_evidence_ids(_provenance_report()) == ["E1", "E2"]


def test_collect_supporting_context_ids_includes_only_hypothesis_supporting_context():
    # K2/H1/H2 are retrieved (or, for H1, explicitly CONFLICTING) but
    # never declared as SUPPORTING by any hypothesis -- never included.
    assert _collect_supporting_context_ids(_provenance_report()) == ["K1"]


def test_collect_supporting_evidence_ids_handles_no_report():
    assert _collect_supporting_evidence_ids(None) == []


def test_collect_supporting_context_ids_handles_no_report():
    assert _collect_supporting_context_ids(None) == []


def test_collect_supporting_evidence_ids_deduplicates_across_observations_and_hypotheses():
    report = {
        "observations": [{"evidence_ids": ["E1", "E1"]}],
        "hypotheses": [{"supporting_evidence_ids": ["E1", "E2"]}],
    }
    assert _collect_supporting_evidence_ids(report) == ["E1", "E2"]


# ---------------------------------------------------------------------
# Routing functions -- pure, direct
# ---------------------------------------------------------------------


def test_route_after_propose_remediation():
    assert route_after_propose_remediation({"remediation_proposal_id": "p1"}) == "await_human_approval"
    assert route_after_propose_remediation({"remediation_status": "not_applicable"}) == "finalize"
    assert route_after_propose_remediation({"status": "failed", "remediation_proposal_id": "p1"}) == "finalize"


def test_route_after_await_human_approval():
    assert route_after_await_human_approval({"approval_decision": "approved"}) == "execute_remediation"
    assert route_after_await_human_approval({"approval_decision": "rejected"}) == "finalize"
    assert route_after_await_human_approval({}) == "finalize"


def test_route_after_execute_remediation():
    assert route_after_execute_remediation({"status": "running"}) == "verify_recovery"
    assert route_after_execute_remediation({"status": "failed"}) == "finalize"
