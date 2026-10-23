"""Phase 12B-D, Gate 2: the ONE authenticated Kubernetes finding-
ingestion endpoint. Mirrors api/webhook.py's own structure (thin route
handler, all field derivation/occurrence-identity logic in
ingestion/kubernetes_mapping.py and ingestion/kubernetes_service.py).

CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN is a credential distinct from
every other Bearer token this service checks (api/auth.py) -- never
held by Alertmanager, a human operator, agent-runtime-service, or
tool-gateway. This is the ONLY write path into reliability.incidents a
Kubernetes-sourced caller can ever reach; there is no corresponding
"update any incident field" or "delete" capability here or anywhere
else."""

from typing import Annotated

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from control_plane.api.auth import require_kubernetes_ingestion_token
from control_plane.api.dependencies import get_incident_repository
from control_plane.core.authz import (
    ActorContext,
    get_actor_context,
    require_legacy_ingestion_allowed,
    require_same_organization,
)
from control_plane.domain.kubernetes_finding import (
    KubernetesFindingIngestRequest,
    KubernetesFindingIngestResponse,
    KubernetesIncidentEvidence,
)
from control_plane.ingestion.kubernetes_service import KubernetesIngestionRejected, ingest_kubernetes_finding
from control_plane.repositories.incident_repository import IncidentRepository

router = APIRouter()


@router.post(
    "/internal/v1/kubernetes/findings",
    response_model=KubernetesFindingIngestResponse,
    status_code=201,
    dependencies=[Depends(require_kubernetes_ingestion_token), Depends(require_legacy_ingestion_allowed)],
)
async def ingest_kubernetes_finding_endpoint(
    body: KubernetesFindingIngestRequest,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> KubernetesFindingIngestResponse:
    """Turns ONE validated, authenticated Kubernetes detector finding
    into a durable reliability.incidents write -- created, updated (an
    accepted continuing observation of an already-active incident), or
    ignored (a stale/delayed replay -- see
    ingestion/kubernetes_service.py's own occurrence-identity
    docstring). 201 in every one of those three cases: this IS the
    resource that now exists, whether this exact request is what
    created/updated it or an earlier one already did."""
    try:
        incident_id, outcome, severity = await ingest_kubernetes_finding(body, repo)
    except KubernetesIngestionRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return KubernetesFindingIngestResponse(incident_id=incident_id, outcome=outcome, severity=severity)


@router.get(
    "/api/v1/incidents/{incident_id}/kubernetes-evidence",
    response_model=KubernetesIncidentEvidence,
)
async def get_kubernetes_incident_evidence(
    incident_id: uuid.UUID,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
    actor: Annotated[ActorContext | None, Depends(get_actor_context)],
) -> KubernetesIncidentEvidence:
    """Phase 12B-D correction round (Issue 1): the ONE trusted,
    persisted source agent-runtime-service's propose_remediation node
    uses to establish a demonstrable identity relationship between a
    SPECIFIC incident and the allowlisted Deployment -- never a
    caller-supplied claim, never inferred from title/description text.
    Read-only, same local-development policy as every other incident
    GET route when organization-context enforcement is disabled;
    tenant-scoped (Phase 14 correction round, Issue 2: "AWS/Kubernetes
    evidence reads" must be protected) when it is enabled. 404 if the
    incident itself does not exist, belongs to a different
    organization, OR has no recorded Kubernetes-actor evidence at all
    (e.g. an Alertmanager-sourced incident) -- all are real "nothing
    to return here" cases, never fabricated, and never distinguishable
    from each other to an unauthorized caller.
    """
    incident = await repo.get_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    require_same_organization(actor, incident["organization_id"])

    event = await repo.get_latest_kubernetes_evidence_event(incident_id)
    if event is None:
        raise HTTPException(status_code=404, detail="this incident has no recorded Kubernetes evidence")

    metadata = dict(event["metadata"] or {})
    try:
        return KubernetesIncidentEvidence.model_validate(metadata)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500, detail="the incident's own recorded Kubernetes evidence did not match the expected shape"
        ) from exc
