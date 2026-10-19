"""Fake control-plane/investigator/tool-gateway client doubles --
duck-typed to the real client classes' own async method signatures
(agent_runtime_service.clients.{control_plane,investigator,tool_gateway}),
never a subclass of them and never a mock of any internal detail."""

import uuid

from agent_runtime_service.clients.control_plane import RemediationProposalNotFoundError
from agent_runtime_service.clients.tool_gateway import ToolGatewayRefusedError
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.domain.remediation import RemediationCapability, RemediationExecutionResult, RemediationProposal


class FakeControlPlaneClient:
    """`get_status` mirrors agent-runtime-service's own
    tests/test_remediation_graph.py::FakeControlPlaneClient convention
    exactly: `get_remediation_proposal` always reports THIS configured
    status (default "succeeded" -- the common case), independent of
    whatever `create_remediation_proposal` itself stored. In the real
    system, tool-gateway's own execute() call is what causes
    control-plane to durably record "succeeded"/"failed" on the
    proposal -- this fake does not model that cross-service write;
    callers who need a DIFFERENT status set `get_status` explicitly
    (e.g. "rejected" is set by the graph's own state locally, never
    read back through this method)."""

    def __init__(self, *, incident: dict, create_raise: Exception | None = None, get_status: str = "succeeded"):
        self._incident = incident
        self._create_raise = create_raise
        self._get_status = get_status
        self.create_calls = 0
        self.get_calls = 0
        self._proposal: RemediationProposal | None = None

    async def get_incident(self, incident_id):
        return IncidentSnapshot.model_validate({**self._incident, "id": uuid.UUID(str(incident_id))})

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
        if self._proposal is None:
            raise RemediationProposalNotFoundError(f"no proposal {proposal_id} was ever created by this fake")
        return self._proposal.model_copy(update={"status": self._get_status})


class FakeInvestigatorClient:
    def __init__(self, *, report: dict):
        self._report = report

    async def investigate(self, incident_id):
        return InvestigationReport.model_validate({**self._report, "incident_id": uuid.UUID(str(incident_id))})


class FakeToolGatewayClient:
    """`precondition_met` mirrors the REAL fault's own current state:
    True means the controlled fault IS currently active (the real
    precondition propose_remediation's own policy requires). A
    successful `execute()` genuinely clears the real fault in
    production (tool-gateway's own real action), so this fake flips
    `precondition_met` to False afterward -- verify_recovery's own
    independent, FRESH `get_capability()` re-read must observe that
    real state change exactly like the real system does; a fake that
    left this constant would make `fault_inactive` permanently false
    and every successful execution falsely report recovery as
    'failed'."""

    def __init__(self, *, precondition_met: bool = True, target_healthy: bool = True, execute_status: str = "succeeded"):
        self._precondition_met = precondition_met
        self._target_healthy = target_healthy
        self._execute_status = execute_status
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
        if self._execute_status == "refused":
            raise ToolGatewayRefusedError(409, "refused by fake tool-gateway")
        if self._execute_status == "succeeded":
            # Simulates the real action's own real-world side effect --
            # the fault is now genuinely cleared, so a later, fresh
            # get_capability() call (verify_recovery) must observe it.
            self._precondition_met = False
        return RemediationExecutionResult.model_validate(
            {"proposal_id": proposal_id, "status": self._execute_status, "detail": None}
        )
