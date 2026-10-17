"""Remediation proposal/audit endpoints (Phase 8).

Three distinct, never-interchangeable Bearer tokens guard three
distinct capabilities here (see api/auth.py's own docstring and
docs/architecture/phase-8-human-approval-remediation.md):

  - `require_remediation_proposal_token` — POST
    /internal/v1/remediation-proposals. Held ONLY by
    agent-runtime-service.
  - `require_remediation_approver_token` — POST
    /api/v1/remediation-proposals/{id}/decision. Held ONLY by a
    human/operator (or a CI acceptance script simulating one).
  - `require_remediation_executor_token` — POST
    /internal/v1/remediation-proposals/{id}/execution/{start,result}.
    Held ONLY by tool-gateway.

Every GET route here is unauthenticated, read-only — the same
local-development policy every other GET route in this service already
follows (api/incidents.py). This is deliberate: it is what lets
tool-gateway independently verify a proposal's real status before
executing anything, and lets agent-runtime-service independently fetch
the trusted human decision before resuming a LangGraph interrupt,
without either of them needing yet another credential.

Route handlers stay thin: request-body validation and response shaping
only. No SQL and no engine/session construction (both are the
repository's job — repositories/remediation_repository.py); no
transition-legality logic either — that lives in the repository, the
single centralized place both this module's decision endpoint and
tool-gateway's own bookkeeping calls rely on.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from control_plane.api.auth import (
    require_remediation_approver_token,
    require_remediation_executor_token,
    require_remediation_proposal_token,
)
from control_plane.api.dependencies import get_incident_repository, get_remediation_repository
from control_plane.domain.remediation import (
    RemediationDecisionRequest,
    RemediationEvent,
    RemediationEventListResponse,
    RemediationExecutionResultRequest,
    RemediationExecutionStartRequest,
    RemediationProposal,
    RemediationProposalCreateRequest,
    RemediationProposalListResponse,
)
from control_plane.repositories.incident_repository import IncidentRepository
from control_plane.repositories.remediation_repository import (
    IdempotencyConflictError,
    IllegalProposalTransitionError,
    RemediationRepository,
)

router = APIRouter()

MAX_EVENTS_PAGE = 100
MAX_PROPOSALS_PAGE = 100


@router.post(
    "/internal/v1/remediation-proposals",
    response_model=RemediationProposal,
    status_code=201,
    dependencies=[Depends(require_remediation_proposal_token)],
)
async def create_remediation_proposal(
    body: RemediationProposalCreateRequest,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> RemediationProposal:
    """Idempotent proposal creation (Phase 8 §PROPOSAL IDEMPOTENCY):
    same idempotency_key + same semantic request returns the existing
    proposal (still 201 — this IS the resource that now exists,
    whether created by this request or an earlier retried one); same
    key + a conflicting request is a 409, never a silent overwrite.
    """
    incident = await incident_repo.get_by_id(body.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    try:
        proposal, _created = await repo.create_proposal(
            incident_id=body.incident_id,
            agent_run_id=body.agent_run_id,
            idempotency_key=body.idempotency_key,
            action_type=body.action_type,
            target=body.target,
            reason=body.reason,
            supporting_evidence_ids=body.supporting_evidence_ids,
            supporting_context_ids=body.supporting_context_ids,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await repo.commit()
    return RemediationProposal.model_validate(proposal)


@router.get("/api/v1/remediation-proposals/{proposal_id}", response_model=RemediationProposal)
async def get_remediation_proposal(
    proposal_id: uuid.UUID,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
) -> RemediationProposal:
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")
    return RemediationProposal.model_validate(proposal)


@router.get("/api/v1/incidents/{incident_id}/remediation-proposals", response_model=RemediationProposalListResponse)
async def list_remediation_proposals_for_incident(
    incident_id: uuid.UUID,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    limit: int = 20,
    offset: int = 0,
) -> RemediationProposalListResponse:
    if limit < 1 or limit > MAX_PROPOSALS_PAGE:
        raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_PROPOSALS_PAGE}")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    incident = await incident_repo.get_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    rows, total = await repo.list_for_incident(incident_id, limit=limit, offset=offset)
    return RemediationProposalListResponse(
        items=[RemediationProposal.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/api/v1/remediation-proposals/{proposal_id}/events", response_model=RemediationEventListResponse)
async def list_remediation_events(
    proposal_id: uuid.UUID,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
    limit: int = 20,
    offset: int = 0,
) -> RemediationEventListResponse:
    if limit < 1 or limit > MAX_EVENTS_PAGE:
        raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_EVENTS_PAGE}")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")

    rows, total = await repo.get_events(proposal_id, limit=limit, offset=offset)
    return RemediationEventListResponse(
        items=[RemediationEvent.model_validate(dict(r)) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "/api/v1/remediation-proposals/{proposal_id}/decision",
    response_model=RemediationProposal,
    dependencies=[Depends(require_remediation_approver_token)],
)
async def decide_remediation_proposal(
    proposal_id: uuid.UUID,
    body: RemediationDecisionRequest,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
) -> RemediationProposal:
    """The human/operator decision endpoint. On approve, this ALSO
    atomically transitions the owning incident investigating ->
    remediating (see repositories/remediation_repository.py::decide).
    If the proposal or the incident has drifted from the expected
    state, this fails 409/404 WITHOUT mutating anything — see that
    method's own docstring for the exact rules.
    """
    try:
        proposal = await repo.decide(
            proposal_id, expected_status=body.expected_status, decision=body.decision, comment=body.comment
        )
    except IllegalProposalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if proposal is None:
        # Ambiguous by construction (see decide()'s own docstring):
        # either the proposal id doesn't exist, or (for an approve)
        # the owning incident was not in 'investigating'. One follow-up
        # read resolves which.
        existing = await repo.get_by_id(proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot approve proposal {proposal_id}: the owning incident is not currently "
                "'investigating' (or was concurrently modified)"
            ),
        )

    await repo.commit()
    return RemediationProposal.model_validate(proposal)


@router.post(
    "/internal/v1/remediation-proposals/{proposal_id}/execution/start",
    response_model=RemediationProposal,
    dependencies=[Depends(require_remediation_executor_token)],
)
async def start_remediation_execution(
    proposal_id: uuid.UUID,
    body: RemediationExecutionStartRequest,  # noqa: ARG001 -- currently empty; kept explicit, see its own docstring
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
) -> RemediationProposal:
    """tool-gateway-only. approved -> executing. Idempotent: calling
    this again while already 'executing' returns the SAME row with no
    duplicate event -- this is what makes the at-least-once execution
    model safe across a crash between 'start' succeeding and the
    actual action running (Phase 8 §TOOL-GATEWAY EXECUTION
    IDEMPOTENCY). pending_approval/rejected/succeeded/failed are all
    returned UNCHANGED (never 409 here) -- tool-gateway's own caller
    (api/remediation-actions/execute) is responsible for refusing to
    proceed for any status other than 'approved'/'executing', using
    this response's own `status` field; this endpoint itself never
    raises for those cases, since they are not malformed requests.
    """
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")

    result = await repo.start_execution(proposal_id)
    await repo.commit()
    return RemediationProposal.model_validate(result)


@router.post(
    "/internal/v1/remediation-proposals/{proposal_id}/execution/result",
    response_model=RemediationProposal,
    dependencies=[Depends(require_remediation_executor_token)],
)
async def record_remediation_execution_result(
    proposal_id: uuid.UUID,
    body: RemediationExecutionResultRequest,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
) -> RemediationProposal:
    """tool-gateway-only. executing -> succeeded|failed. On 'failed',
    also atomically rolls the owning incident back remediating ->
    investigating (Phase 8 §HANDLE FAILED REMEDIATION INCIDENT STATE) —
    see repositories/remediation_repository.py::record_execution_result.
    Idempotent: reporting the SAME outcome again for an
    already-terminal proposal returns it unchanged with no duplicate
    event; reporting a DIFFERENT outcome than what is already recorded
    is a 409 (a genuinely conflicting report, never silently
    overwritten).
    """
    try:
        result = await repo.record_execution_result(proposal_id, outcome=body.outcome, detail=body.detail)
    except IllegalProposalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")

    await repo.commit()
    return RemediationProposal.model_validate(result)
