"""Local mirror of control-plane's existing read API response shapes
(GET /api/v1/incidents, GET /api/v1/incidents/{id},
GET /api/v1/incidents/{id}/events) -- kept consistent BY HAND with
services/control-plane/src/control_plane/domain/incident.py and
incident_event.py, the exact same convention
investigator_service.domain.incident_snapshot already uses. No field
is invented here; every name/type matches control-plane's actual,
already-documented JSON contract (see docs/api/control-plane.md).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["critical", "warning", "info"]
Status = Literal["open", "acknowledged", "investigating", "remediating", "resolved", "closed"]
EventType = Literal["created", "observed", "status_transition"]
ActorType = Literal["alertmanager", "operator"]


class IncidentSnapshot(BaseModel):
    """Shared shape for both GET /api/v1/incidents' list items and
    GET /api/v1/incidents/{id}'s single-incident response."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    source: str
    source_fingerprint: str
    title: str
    description: str | None
    severity: Severity
    status: Status
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentEventSnapshot(BaseModel):
    """GET /api/v1/incidents/{id}/events' per-item shape."""

    model_config = ConfigDict(extra="ignore")

    id: int
    incident_id: uuid.UUID
    event_type: EventType
    actor_type: ActorType
    previous_status: Status | None
    new_status: Status
    occurred_at: datetime
    metadata: dict[str, object]
