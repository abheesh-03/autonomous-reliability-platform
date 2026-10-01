"""Read-only incident endpoints.

Phase 3B is explicitly read-only at the HTTP API level — there is no
POST/PATCH/DELETE here, and none is planned until later phases (alert
ingestion is Phase 3C; lifecycle transitions are Phase 3D). Route
handlers stay thin: query-parameter validation and response shaping
only, no SQL and no engine/session construction — both are the
repository's job (control_plane/repositories/incident_repository.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.incident import VALID_SEVERITIES, VALID_STATUSES, Incident, IncidentListResponse
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
