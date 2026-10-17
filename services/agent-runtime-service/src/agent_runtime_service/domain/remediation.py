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

from pydantic import BaseModel, ConfigDict

ActionType = Literal["clear_payment_authorization_fault"]
Target = Literal["payment-service"]
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


class RemediationExecutionResult(BaseModel):
    """tool-gateway's POST /api/v1/remediation-actions/execute 200
    response shape."""

    model_config = ConfigDict(extra="ignore")

    proposal_id: str
    status: Literal["succeeded", "failed"]
    detail: str | None = None
