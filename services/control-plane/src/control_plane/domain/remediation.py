"""Phase 8 remediation proposal/event response + request models.

Field set matches database/migrations/V6__create_remediation_schema.sql
exactly -- maintained by hand, like domain/incident.py and
domain/incident_event.py, not by schema reflection or an ORM mapping.

Phase 8 scope note: `action_type`/`target` are closed, single-value
Literals -- never a free-form string -- exactly mirroring the V6 CHECK
constraints. A future phase that adds a second real action must widen
both the Literal here and the CHECK constraint in a new additive
migration together; this module never accepts an arbitrary action/
target pair on trust.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ActionType = Literal["clear_payment_authorization_fault"]
Target = Literal["payment-service"]
ProposalStatus = Literal["pending_approval", "approved", "rejected", "executing", "succeeded", "failed"]
RemediationEventType = Literal[
    "proposed", "approved", "rejected", "execution_started", "execution_succeeded", "execution_failed"
]
RemediationActorType = Literal["agent", "operator", "executor"]

# Bounds enforced here too (not only by V6's own CHECK constraints) so
# an invalid request is rejected with a clear 422 before ever reaching
# the database -- the same "defense in depth, not a substitute"
# convention every other bounded field in this platform already
# follows.
MAX_REASON_CHARS = 1000
MAX_COMMENT_CHARS = 1000
MAX_EVIDENCE_IDS = 50
MAX_ID_CHARS = 200

# Phase 8 correction round (finding #6): V6's own migration comments
# document that each individual evidence/context id is bounded to
# MAX_ID_CHARS in application code -- a prior version of this module
# only bounded the LIST length (`max_length=MAX_EVIDENCE_IDS`), never
# each individual string, so that documented claim was not actually
# true. `BoundedId` makes it true: every element of
# supporting_evidence_ids/supporting_context_ids is now itself
# `min_length=1` (never an empty id) and `max_length=MAX_ID_CHARS`,
# rejected with a 422 before ever reaching the database.
BoundedId = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ID_CHARS)]

# Phase 8 correction round (finding #5, second pass): V6's own CHECK
# constraint bounds each array by BOTH `cardinality(...) <= 50` AND
# `char_length(array_to_string(..., ',')) <= 5000` -- the second is an
# AGGREGATE joined-string bound, never implied by "50 elements of at
# most 200 chars each" (50 * 200 = 10000 > 5000). Without this, a
# payload of many near-200-char ids could pass every per-element and
# per-list-length check here and only be discovered as a PostgreSQL
# CHECK violation. `_max_joined_ids_chars` mirrors
# `array_to_string(ids, ',')`'s exact semantics for a list of
# non-empty strings (BoundedId already forbids empty/NULL elements):
# the joined length is `sum(len(i) for i in ids) + (len(ids) - 1)`
# separator commas, i.e. `len(",".join(ids))`.
MAX_IDS_JOINED_CHARS = 5000


def _validate_joined_length(ids: list[str], *, field_name: str) -> list[str]:
    joined_length = len(",".join(ids))
    if joined_length > MAX_IDS_JOINED_CHARS:
        raise ValueError(
            f"{field_name}: joined length ({joined_length} chars, comma-separated) exceeds the "
            f"maximum of {MAX_IDS_JOINED_CHARS} chars"
        )
    return ids


class RemediationProposalCreateRequest(BaseModel):
    """POST /internal/v1/remediation-proposals request body -- the
    agent-proposal-token-only internal endpoint. `idempotency_key` is
    mandatory, never generated server-side: agent-runtime-service
    derives it deterministically from its own durable run id
    ("phase8-proposal:<run_id>"), so a retried request (crash before
    checkpoint commit, Phase 7's own documented reality) converges on
    the SAME proposal rather than creating a duplicate."""

    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    idempotency_key: str = Field(..., min_length=1, max_length=200)
    action_type: ActionType
    target: Target
    reason: str = Field(..., max_length=MAX_REASON_CHARS)
    supporting_evidence_ids: list[BoundedId] = Field(default_factory=list, max_length=MAX_EVIDENCE_IDS)
    supporting_context_ids: list[BoundedId] = Field(default_factory=list, max_length=MAX_EVIDENCE_IDS)

    @field_validator("supporting_evidence_ids", "supporting_context_ids")
    @classmethod
    def _bound_joined_length(cls, ids: list[str], info) -> list[str]:
        return _validate_joined_length(ids, field_name=info.field_name)


class RemediationProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    idempotency_key: str
    action_type: ActionType
    target: Target
    reason: str
    supporting_evidence_ids: list[str]
    supporting_context_ids: list[str]
    status: ProposalStatus
    proposed_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    decision_comment: str | None
    execution_started_at: datetime | None
    execution_completed_at: datetime | None


class RemediationProposalListResponse(BaseModel):
    items: list[RemediationProposal]
    total: int
    limit: int
    offset: int


class RemediationEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposal_id: uuid.UUID
    event_type: RemediationEventType
    actor_type: RemediationActorType
    occurred_at: datetime
    metadata: dict[str, object]


class RemediationEventListResponse(BaseModel):
    items: list[RemediationEvent]
    total: int
    limit: int
    offset: int


Decision = Literal["approve", "reject"]


class RemediationDecisionRequest(BaseModel):
    """POST /api/v1/remediation-proposals/{id}/decision request body --
    the human-approver-token-only endpoint. `expected_status` is
    mandatory optimistic-concurrency protection, exactly like
    IncidentStatusTransitionRequest's own `expected_status` (Phase 3D)
    -- the decision is only applied if the proposal's actual current
    status still matches it at the moment of the atomic UPDATE."""

    model_config = ConfigDict(extra="forbid")

    expected_status: ProposalStatus
    decision: Decision
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_CHARS)


class RemediationExecutionStartRequest(BaseModel):
    """POST /internal/v1/remediation-proposals/{id}/execution/start --
    the executor-token-only endpoint. No body fields beyond what the
    path already carries; kept as an explicit (if currently empty)
    model, not a bare `None`, so a future field never has to change the
    route signature itself."""

    model_config = ConfigDict(extra="forbid")


ExecutionOutcome = Literal["succeeded", "failed"]


class RemediationExecutionResultRequest(BaseModel):
    """POST /internal/v1/remediation-proposals/{id}/execution/result --
    the executor-token-only endpoint. `detail` is bounded, structured
    metadata only -- never a raw HTTP response body, exception
    traceback, or secret (tool-gateway's own responsibility to bound
    before calling this -- see services/tool-gateway)."""

    model_config = ConfigDict(extra="forbid")

    outcome: ExecutionOutcome
    detail: str | None = Field(default=None, max_length=MAX_COMMENT_CHARS)
