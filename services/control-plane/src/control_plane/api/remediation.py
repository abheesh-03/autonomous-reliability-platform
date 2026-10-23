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

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from control_plane.api.auth import (
    require_remediation_approver_token,
    require_remediation_executor_token,
    require_remediation_proposal_token,
)
from control_plane.api.dependencies import (
    get_auth_membership_repository,
    get_incident_repository,
    get_remediation_repository,
)
from control_plane.core.authz import (
    ROLES_THAT_MAY_DECIDE_REMEDIATION,
    ActorContext,
    InternalServiceContext,
    get_actor_context,
    get_actor_or_tool_gateway_reader,
    require_same_organization,
    require_tool_gateway_proposal_access,
)
from control_plane.repositories.auth_membership_repository import AuthMembershipRepository
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

logger = logging.getLogger("control_plane.api.remediation")

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
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
) -> RemediationProposal:
    """Idempotent proposal creation (Phase 8 §PROPOSAL IDEMPOTENCY):
    same idempotency_key + same semantic request returns the existing
    proposal (still 201 — this IS the resource that now exists,
    whether created by this request or an earlier retried one); same
    key + a conflicting request is a 409, never a silent overwrite.

    Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C:
    `require_remediation_proposal_token` (the route decorator) remains
    REQUIRED, unchanged — this is additive, never a replacement. When
    organization-context enforcement is on, agent-runtime-service
    relays the real actor its own API boundary already verified for
    this request (`sign_derivative_assertion`, same mechanism Blocker
    1 built), and that actor's organization MUST match the target
    incident's real organization before any proposal is created —
    "prevent a machine credential from creating... an unrelated
    tenant's remediation proposal." A mismatch is 404 (not found),
    never a 403 that would confirm the incident exists in another org.
    """
    incident = await incident_repo.get_by_id(body.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    require_same_organization(actor, incident["organization_id"])

    try:
        proposal, _created = await repo.create_proposal(
            incident_id=body.incident_id,
            agent_run_id=body.agent_run_id,
            idempotency_key=body.idempotency_key,
            action_type=body.action_type,
            target=body.target,
            target_cluster=body.target_cluster,
            expected_resource_uid=body.expected_resource_uid,
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
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | InternalServiceContext | None, Depends(get_actor_or_tool_gateway_reader)],
) -> RemediationProposal:
    """Phase 14 correction round, Blocker 1: the ONLY remediation-
    proposal route that still accepts `InternalServiceContext` (bound
    to tool-gateway's own token specifically, and ONLY for an
    already-decided proposal -- see
    `require_tool_gateway_proposal_access`'s own docstring). Every
    other caller (web-console, agent-runtime-service forwarding a real
    actor) is a real, tenant-matched `ActorContext`.
    """
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")
    if actor is not None:
        owning_incident = await incident_repo.get_by_id(proposal["incident_id"])
        if owning_incident is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        require_tool_gateway_proposal_access(
            actor, resource_organization_id=owning_incident["organization_id"], proposal_status=proposal["status"]
        )
    return RemediationProposal.model_validate(proposal)


@router.get("/api/v1/incidents/{incident_id}/remediation-proposals", response_model=RemediationProposalListResponse)
async def list_remediation_proposals_for_incident(
    incident_id: uuid.UUID,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
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
    require_same_organization(actor, incident["organization_id"])

    rows, total = await repo.list_for_incident(incident_id, limit=limit, offset=offset)
    return RemediationProposalListResponse(
        items=[RemediationProposal.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/api/v1/remediation-proposals/{proposal_id}/events", response_model=RemediationEventListResponse)
async def list_remediation_events(
    proposal_id: uuid.UUID,
    repo: Annotated[RemediationRepository, Depends(get_remediation_repository)],
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
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
    if actor is not None:
        owning_incident = await incident_repo.get_by_id(proposal["incident_id"])
        if owning_incident is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        require_same_organization(actor, owning_incident["organization_id"])

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
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    auth_membership_repo: Annotated[AuthMembershipRepository, Depends(get_auth_membership_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
) -> RemediationProposal:
    """The human/operator decision endpoint. On approve, this ALSO
    atomically transitions the owning incident investigating ->
    remediating (see repositories/remediation_repository.py::decide).
    If the proposal or the incident has drifted from the expected
    state, this fails 409/404 WITHOUT mutating anything — see that
    method's own docstring for the exact rules.

    Phase 14 Gate 7 (security-critical): CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
    (the route decorator above) remains REQUIRED, unchanged -- this is
    additive, not a replacement. When organization-context enforcement
    is ALSO on, the server-wide approver token is no longer sufficient
    BY ITSELF: the real actor behind the request must independently
    hold a role in ROLES_THAT_MAY_DECIDE_REMEDIATION (OWNER or
    INCIDENT_APPROVER -- Gate 3: ADMIN does not implicitly bypass
    remediation approval policy) AND that actor's organization must
    match the proposal's owning incident's organization -- "Approval
    for Organization A must never authorize an action involving
    Organization B." Both checks run BEFORE any mutation.

    Phase 14 correction round, BLOCKER 4 (security-critical): the
    assertion's own `role` claim is only ever as fresh as the moment
    web-console minted it (up to its own 60s expiry window) -- it is
    NOT, by itself, proof that the actor is STILL a member with that
    role right now. Immediately before deciding, this handler
    independently re-reads the actor's CURRENT role straight from
    Better Auth's own `auth.member` table (`AuthMembershipRepository`,
    a live, read-only cross-schema lookup -- never a cache, never
    derived from the assertion). A recently revoked/demoted member is
    rejected here even if their still-unexpired assertion claims
    otherwise, and NOTHING is mutated before this check passes.
    """
    if actor is not None:
        proposal_for_tenant_check = await repo.get_by_id(proposal_id)
        if proposal_for_tenant_check is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        owning_incident = await incident_repo.get_by_id(proposal_for_tenant_check["incident_id"])
        if owning_incident is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        require_same_organization(actor, owning_incident["organization_id"])

        # BLOCKER 4: the live re-check. Deliberately AFTER the tenant
        # check above (so a cross-tenant attempt still gets the
        # existence-hiding 404, never a 403/401 that would confirm the
        # resource is merely in a different org) but BEFORE anything
        # is read from or written to the proposal itself.
        current_role = await auth_membership_repo.get_current_role(
            user_id=actor.user_id, organization_id=actor.organization_id
        )
        if current_role is None:
            # Removed/revoked since the assertion was minted -- fail
            # closed, exactly as if no actor had ever been presented.
            logger.warning(
                "rejected a remediation decision: actor %s is no longer a member of organization %s",
                actor.user_id,
                actor.organization_id,
            )
            raise HTTPException(status_code=403, detail="forbidden")
        if current_role not in ROLES_THAT_MAY_DECIDE_REMEDIATION:
            # Still a member, but no longer (or never) holding a role
            # that may decide -- e.g. demoted from INCIDENT_APPROVER to
            # VIEWER after the assertion was minted.
            raise HTTPException(status_code=403, detail="forbidden")

    try:
        proposal = await repo.decide(
            proposal_id,
            expected_status=body.expected_status,
            decision=body.decision,
            comment=body.comment,
            decided_by_user_id=actor.user_id if actor is not None else None,
            decided_by_organization_id=actor.organization_id if actor is not None else None,
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
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
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

    Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C:
    `require_remediation_executor_token` remains REQUIRED, unchanged —
    additive, never a replacement. When organization-context
    enforcement is on, tool-gateway relays the SAME assertion agent-
    runtime-service gave it for this exact proposal/execution (see
    core/authz.py::get_actor_or_tool_gateway_reader's own Issue B
    docstring; services/tool-gateway/internal/api/execute.go forwards
    it unverified by tool-gateway itself to this call too), and that
    actor's organization MUST match the proposal's real owning
    incident's organization BEFORE the idempotent state transition
    below runs — "prevent a machine credential from... advancing an
    unrelated tenant's remediation proposal." Checked BEFORE
    `repo.start_execution` so a tenant mismatch never mutates anything,
    matching every other tenant-check-before-mutation boundary in this
    module.
    """
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")
    if actor is not None:
        owning_incident = await incident_repo.get_by_id(proposal["incident_id"])
        if owning_incident is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        require_same_organization(actor, owning_incident["organization_id"])

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
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
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

    Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C: same
    additive tenant check as start_remediation_execution, above —
    checked BEFORE the idempotent/atomic transition below runs, so a
    tenant mismatch never mutates anything (and never rolls back an
    unrelated tenant's incident).
    """
    if actor is not None:
        proposal_for_tenant_check = await repo.get_by_id(proposal_id)
        if proposal_for_tenant_check is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        owning_incident = await incident_repo.get_by_id(proposal_for_tenant_check["incident_id"])
        if owning_incident is None:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        require_same_organization(actor, owning_incident["organization_id"])

    try:
        result = await repo.record_execution_result(proposal_id, outcome=body.outcome, detail=body.detail)
    except IllegalProposalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="remediation proposal not found")

    await repo.commit()
    return RemediationProposal.model_validate(result)
