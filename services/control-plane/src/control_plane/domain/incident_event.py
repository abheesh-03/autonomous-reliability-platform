"""Incident audit-event response models (Phase 3E).

Field set matches database/migrations/V3__create_incident_audit.sql
exactly — maintained by hand, like domain/incident.py, not by schema
reflection or an ORM mapping. `previous_status`/`new_status` reuse the
exact same `Status` vocabulary as the incident resource itself (the
underlying column CHECK constraints are identical).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from control_plane.domain.incident import Status

EventType = Literal["created", "observed", "status_transition"]
ActorType = Literal["alertmanager", "operator"]


class IncidentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: uuid.UUID
    event_type: EventType
    actor_type: ActorType
    previous_status: Status | None
    new_status: Status
    occurred_at: datetime
    # A minimal, allowlisted, structured object — never a Bearer token,
    # an Authorization header, or a raw webhook payload. See
    # repositories/incident_repository.py for the exact, narrow set of
    # keys this service ever writes here.
    metadata: dict[str, object]


class IncidentEventListResponse(BaseModel):
    items: list[IncidentEvent]
    total: int
    limit: int
    offset: int
