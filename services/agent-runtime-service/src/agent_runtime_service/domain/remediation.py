"""Local mirrors of control-plane's and tool-gateway's Phase 8
response shapes -- the same "kept consistent BY HAND, no field
invented" convention domain/incident_snapshot.py and
domain/investigation.py already establish for their own upstreams.

`extra="ignore"` throughout: this service only needs a small, stable
subset of each upstream's response; neither upstream adding more
fields later can break this client.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActionType = Literal["clear_payment_authorization_fault", "restart_allowlisted_deployment"]
Target = Literal["payment-service", "Deployment/reliability-sandbox/crashloop-demo"]
ProposalStatus = Literal["pending_approval", "approved", "rejected", "executing", "succeeded", "failed"]


class RemediationProposal(BaseModel):
    """control-plane's GET/POST remediation-proposal response shape --
    only the fields this service actually reads from it."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    action_type: ActionType
    target: Target
    target_cluster: str | None = None
    expected_resource_uid: str | None = None
    status: ProposalStatus
    decided_at: datetime | None = None
    decision_comment: str | None = None


class RemediationCapability(BaseModel):
    """tool-gateway's GET /api/v1/remediation-capabilities response
    shape. `target_healthy` (Phase 8 correction round, finding #2) is
    tool-gateway's own independent GET /health check of payment-service
    -- never inferred from any prior execute() response -- which is
    what lets verify_recovery re-derive recovery from a FRESH read
    instead of merely re-trusting execute_remediation's own synchronous
    result."""

    model_config = ConfigDict(extra="ignore")

    action_type: str
    target: str
    precondition_met: bool
    target_healthy: bool


class KubernetesIncidentEvidence(BaseModel):
    """control-plane's GET /api/v1/incidents/{id}/kubernetes-evidence
    response shape (Phase 12B-D correction round, Issue 1) -- the ONE
    trusted, persisted source of a SPECIFIC incident's own Kubernetes
    resource identity. Never inferred from incident title/description
    text, and never trusted from any other source."""

    model_config = ConfigDict(extra="ignore")

    cluster: str
    namespace: str
    resource_kind: str
    resource_name: str
    resource_uid: str | None = None
    detector_id: str
    result: Literal["confirmed", "insufficient_evidence"]
    collection_completeness: Literal["complete", "partial"]
    collected_at: datetime


class KubernetesRemediationCapability(BaseModel):
    """tool-gateway's GET /api/v1/remediation-capabilities/kubernetes
    response shape (Phase 12B-D) -- the Kubernetes analogue of
    RemediationCapability above. `deployment_uid` is the CURRENT,
    freshly-read Deployment UID -- this is what propose_remediation
    passes through as expected_resource_uid when creating a proposal
    (Gate 4/6's own identity-binding requirement: the UID is captured
    at proposal-creation time, then independently rechecked by
    tool-gateway immediately before any write)."""

    model_config = ConfigDict(extra="ignore")

    action_type: str
    target: str
    target_cluster: str
    precondition_met: bool
    deployment_uid: str | None = None
    # Correction round (Issue 1): the UID of every pod CURRENTLY owned
    # by the target Deployment and reporting a confirmed targeted
    # failure reason -- lets propose_remediation demonstrate that a
    # SPECIFIC incident's own evidence corresponds to a pod this
    # Deployment actually, currently owns.
    failing_pod_uids: list[str] = Field(default_factory=list)
    # Correction round (Issue 5): genuine, freshly-observed readiness/
    # availability evidence -- the SAME facts tool-gateway's own
    # checkRecoveryOnce already requires for VERIFIED_RECOVERED. Lets
    # verify_recovery independently confirm REAL recovery rather than
    # merely inferring health from the absence of a confirmed targeted
    # failure reason (precondition_met alone does not prove the
    # Deployment is otherwise healthy -- e.g. Pending/scaling for an
    # unrelated reason).
    generation_caught_up: bool = False
    ready_replicas: int = 0
    replicas: int = 0
    available_replicas: int = 0
    available: bool = False


class RemediationExecutionResult(BaseModel):
    """tool-gateway's POST /api/v1/remediation-actions/execute 200
    response shape."""

    model_config = ConfigDict(extra="ignore")

    proposal_id: str
    status: Literal["succeeded", "failed"]
    detail: str | None = None
