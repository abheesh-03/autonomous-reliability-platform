"""Incident endpoints.

The GET endpoints remain exactly as read-only and unauthenticated as
Phase 3B left them — no change here. As of Phase 3D, this module also
exposes ONE authenticated write path,
`PATCH /api/v1/incidents/{incident_id}/status`, for explicit, validated
human/operator lifecycle transitions (never a generic arbitrary
incident-editing endpoint — only this one status-transition shape
exists). Route handlers stay thin: query-parameter/body validation and
response shaping only. No SQL and no engine/session construction — both
are the repository's job (control_plane/repositories/incident_repository.py);
no transition-legality logic either — that lives in
control_plane/domain/lifecycle.py, the single centralized state
machine both this endpoint and the Alertmanager-driven automatic
resolution path (ingestion/service.py) rely on.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from control_plane.api.auth import require_lifecycle_token
from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.incident import (
    VALID_SEVERITIES,
    VALID_STATUSES,
    Incident,
    IncidentListResponse,
    IncidentStatusTransitionRequest,
)
from control_plane.domain.lifecycle import entering_resolved, is_transition_allowed
from control_plane.repositories.incident_repository import IncidentRepository

router = APIRouter(prefix="/api/v1")


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    status: Annotated[str | None, Query(description="Filter by incident status")] = None,
    severity: Annotated[str | None, Query(description="Filter by incident severity")] = None,
    source: Annotated[str | None, Query(description="Filter by originating monitoring system")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> IncidentListResponse:
    # FastAPI/Pydantic already enforce limit/offset's numeric bounds
    # (ge=1/le=100/ge=0) and return 422 automatically on violation.
    # status/severity are free-form query strings, so their vocabulary
    # is checked explicitly here, also returning 422 — consistent
    # treatment for every invalid query parameter, not just the
    # numeric ones.
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"invalid status filter: {status!r}")
    if severity is not None and severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=422, detail=f"invalid severity filter: {severity!r}")

    rows, total = await repo.list_incidents(
        status=status, severity=severity, source=source, limit=limit, offset=offset
    )
    return IncidentListResponse(
        items=[Incident.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/{incident_id}", response_model=Incident)
async def get_incident(
    incident_id: uuid.UUID,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> Incident:
    # `incident_id: uuid.UUID` on the path parameter makes FastAPI
    # reject a malformed UUID with 422 before this body ever runs.
    row = await repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return Incident.model_validate(dict(row))


@router.patch(
    "/incidents/{incident_id}/status",
    response_model=Incident,
    dependencies=[Depends(require_lifecycle_token)],
)
async def transition_incident_status(
    incident_id: uuid.UUID,
    body: IncidentStatusTransitionRequest,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> Incident:
    """Explicit, validated incident lifecycle transitions — see
    domain/lifecycle.py for the full state machine. `expected_status`
    is mandatory optimistic-concurrency protection: the transition is
    only applied if the incident's actual current status still matches
    it at the moment of the atomic UPDATE (repo.transition_incident_status),
    never a separate read-then-write.
    """
    expected = body.expected_status
    target = body.target_status

    if expected == target:
        # Documented no-op (domain/lifecycle.py's module docstring):
        # targeting the status the caller already believes is current
        # never mutates anything — not even updated_at — it only
        # confirms that belief (or, if it has since gone stale,
        # reports 409 exactly as a real transition attempt would).
        row = await repo.get_by_id(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if row["status"] != expected:
            raise HTTPException(
                status_code=409,
                detail=f"stale expected_status: incident is currently {row['status']!r}, not {expected!r}",
            )
        return Incident.model_validate(dict(row))

    if not is_transition_allowed(expected, target):
        # Illegal per the state machine regardless of concurrency or
        # the incident's actual current status — rejected before any
        # database write is attempted, so the row is guaranteed
        # unchanged.
        raise HTTPException(status_code=409, detail=f"illegal transition: {expected!r} -> {target!r} is not permitted")

    resolved_at = datetime.now(UTC) if entering_resolved(target) else None
    row = await repo.transition_incident_status(
        incident_id, expected_status=expected, target_status=target, resolved_at=resolved_at
    )
    if row is not None:
        # Every successful transition commits once — without this, the
        # UPDATE's own RETURNING clause still reflects the change
        # within the transaction (so the response would look correct),
        # but the session closing without a commit at the end of the
        # request would silently roll it back, leaving the database
        # completely unchanged despite the 200 response. Caught by a
        # real-PostgreSQL smoke test before this script existed — a
        # mocked-repository unit test cannot catch this class of bug at
        # all, since the fake has no real transaction to roll back.
        await repo.commit()
        return Incident.model_validate(dict(row))

    # Zero rows affected is ambiguous by construction (see
    # IncidentRepository.transition_incident_status's own docstring) —
    # resolve it with one follow-up read: either the id doesn't exist
    # at all (404), or it exists but its actual status no longer
    # matches expected_status (409, stale — someone else transitioned
    # it first).
    existing = await repo.get_by_id(incident_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="incident not found")
    raise HTTPException(
        status_code=409,
        detail=f"stale expected_status: incident is currently {existing['status']!r}, not {expected!r}",
    )
