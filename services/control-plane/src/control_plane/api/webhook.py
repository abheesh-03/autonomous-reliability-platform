"""Alertmanager webhook ingestion (Phase 3C) — the one trusted,
authenticated WRITE endpoint in this service. Every other route here
remains read-only and unauthenticated (see api/incidents.py,
api/health.py); see docs/api/control-plane.md's security-limitations
section for why that split is intentional.

Kept thin: authentication is a router-level dependency
(api/webhook_auth.py, runs before this body executes and therefore
before any incident write), the request-body size guard is separate
ASGI middleware registered in main.py (api/webhook_limits.py — it MUST
be ASGI middleware rather than a dependency here; see that module's
own docstring for why), payload shape/vocabulary validation is
Pydantic (domain/alertmanager_webhook.py), alert-to-incident field
derivation is ingestion/mapping.py, and the actual atomic
create-or-update SQL lives in the repository
(repositories/incident_repository.py) — this module only wires them
together. No SQL and no engine/session construction here, same
convention as api/incidents.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from control_plane.api.dependencies import get_incident_repository
from control_plane.api.webhook_auth import require_webhook_token
from control_plane.domain.alertmanager_webhook import AlertmanagerWebhookPayload, WebhookAckResponse
from control_plane.ingestion.service import ingest_alertmanager_webhook
from control_plane.repositories.incident_repository import IncidentRepository

router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_webhook_token)])


@router.post("/alertmanager/webhook", response_model=WebhookAckResponse)
async def alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> WebhookAckResponse:
    return await ingest_alertmanager_webhook(payload, repo)
