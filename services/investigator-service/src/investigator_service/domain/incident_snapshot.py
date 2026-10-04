"""Local mirrors of control-plane's existing read API response shapes
(GET /api/v1/incidents/{id}, GET /api/v1/incidents/{id}/events).

This is a SEPARATE service/deployable, so it cannot import
control-plane's Python package directly — these models are kept
consistent BY HAND with
services/control-plane/src/control_plane/domain/incident.py and
incident_event.py, the same way those two files are themselves kept
consistent by hand with the underlying Flyway-owned schema, not by
code sharing or schema reflection. No field is invented here: every
name/type below matches control-plane's actual, already-documented
JSON contract (see docs/api/control-plane.md).
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
    """GET /api/v1/incidents/{id}'s exact response shape."""

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
