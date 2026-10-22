"""Phase 13, Gate 4: the ONE authenticated AWS finding-ingestion
endpoint. Mirrors `api/kubernetes.py`'s own structure exactly (thin
route handler, all field derivation/occurrence-identity logic in
ingestion/aws_mapping.py and ingestion/aws_service.py).

CONTROL_PLANE_AWS_INGESTION_TOKEN is a credential distinct from EVERY
other Bearer token this service checks (api/auth.py) -- including
CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN (Gate 4: "Do not reuse the
Kubernetes ingestion token"). Never held by Alertmanager, a human
operator, agent-runtime-service, tool-gateway, or the Kubernetes
observation pipeline. This is the ONLY write path into
reliability.incidents an AWS-sourced caller can ever reach."""

from typing import Annotated

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from control_plane.api.auth import require_aws_ingestion_token
from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.aws_finding import AwsFindingIngestRequest, AwsFindingIngestResponse, AwsIncidentEvidence
from control_plane.ingestion.aws_service import AwsIngestionRejected, ingest_aws_finding
from control_plane.repositories.incident_repository import IncidentRepository

router = APIRouter()


@router.post(
    "/internal/v1/aws/findings",
    response_model=AwsFindingIngestResponse,
    status_code=201,
    dependencies=[Depends(require_aws_ingestion_token)],
)
async def ingest_aws_finding_endpoint(
    body: AwsFindingIngestRequest,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> AwsFindingIngestResponse:
    """Turns ONE validated, authenticated AWS detector finding into a
    durable reliability.incidents write -- created, updated, or
    ignored (see ingestion/aws_service.py's own occurrence-identity
    docstring). 201 in every one of those three cases."""
    try:
        incident_id, outcome, severity = await ingest_aws_finding(body, repo)
    except AwsIngestionRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AwsFindingIngestResponse(incident_id=incident_id, outcome=outcome, severity=severity)


@router.get(
    "/api/v1/incidents/{incident_id}/aws-evidence",
    response_model=AwsIncidentEvidence,
)
async def get_aws_incident_evidence(
    incident_id: uuid.UUID,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> AwsIncidentEvidence:
    """The ONE trusted, persisted source agent-runtime-service and
    investigator-service use to establish a demonstrable identity
    relationship between a SPECIFIC incident and a real AWS resource --
    never a caller-supplied claim, never inferred from title/
    description text. Read-only/unauthenticated, same local-development
    policy as every other incident GET route. 404 if the incident
    itself does not exist, OR if it has no recorded AWS-actor evidence
    at all."""
    incident = await repo.get_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    event = await repo.get_latest_aws_evidence_event(incident_id)
    if event is None:
        raise HTTPException(status_code=404, detail="this incident has no recorded AWS evidence")

    metadata = dict(event["metadata"] or {})
    try:
        return AwsIncidentEvidence.model_validate(metadata)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500, detail="the incident's own recorded AWS evidence did not match the expected shape"
        ) from exc
