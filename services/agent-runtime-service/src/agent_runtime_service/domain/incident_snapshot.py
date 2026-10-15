"""Local mirror of control-plane's existing read API response shape
(GET /api/v1/incidents/{id}) -- kept consistent BY HAND with
services/control-plane/src/control_plane/domain/incident.py, the exact
same convention investigator_service.domain.incident_snapshot and
retrieval_service.domain.incident_snapshot already establish for their
own separate deployables. No field is invented here; every name/type
matches control-plane's actual, already-documented JSON contract (see
docs/api/control-plane.md).

node_load_incident.py only ever calls GET /api/v1/incidents/{id} (not
the /events endpoint) -- this service's graph state stores a bounded
snapshot of the incident itself, not its audit history (that remains
investigator-service's own evidence-collection responsibility, Phase
5/6, never duplicated here).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["critical", "warning", "info"]
Status = Literal["open", "acknowledged", "investigating", "remediating", "resolved", "closed"]


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
