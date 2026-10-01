"""Incident response models.

Field set and vocabulary match database/migrations/V1__create_incident_schema.sql
exactly (reliability.incidents) — that migration is Flyway-owned and is
never modified or re-derived from here; this module is kept consistent
with it by hand, not by schema reflection or an ORM mapping.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Exact vocabulary from the incidents_severity_check / incidents_status_check
# CHECK constraints in V1__create_incident_schema.sql.
Severity = Literal["critical", "warning", "info"]
Status = Literal["open", "acknowledged", "investigating", "remediating", "resolved", "closed"]

VALID_SEVERITIES: frozenset[str] = frozenset(Severity.__args__)
VALID_STATUSES: frozenset[str] = frozenset(Status.__args__)


class Incident(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class IncidentListResponse(BaseModel):
    items: list[Incident]
    total: int
    limit: int
    offset: int
