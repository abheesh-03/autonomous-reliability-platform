"""Phase 15 dashboard summary response models.

Every field here is sourced from a real, bounded, organization-scoped
SQL query in repositories/dashboard_repository.py -- never fabricated,
never an unbounded fetch aggregated in Python. See that module's own
docstring for the query-level guarantees this model's fields rest on.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from control_plane.domain.incident import Severity, Status


class StatusCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: int = 0
    acknowledged: int = 0
    investigating: int = 0
    remediating: int = 0
    resolved: int = 0
    closed: int = 0
    # Derived (active_critical_count's own query), not a sum of the
    # fields above -- "critical AND not yet resolved/closed",
    # independent of which active status it is currently in.
    active_critical: int = 0


class AttentionIncident(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    severity: Severity
    status: Status
    source: str
    last_seen_at: datetime


class PendingApproval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proposal_id: uuid.UUID
    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    incident_title: str
    incident_severity: Severity
    action_type: str
    target: str
    proposed_at: datetime


class ActivityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    critical: int = 0
    warning: int = 0
    info: int = 0


class RecentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: uuid.UUID
    incident_title: str
    incident_severity: Severity
    event_type: str
    actor_type: str
    previous_status: Status | None
    new_status: Status
    occurred_at: datetime


class DashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    counts: StatusCounts
    # Independent-review correction round, BLOCKER 3 bug B: a real,
    # unbounded COUNT -- distinct from len(pending_approvals), which is
    # bounded to 8 for display purposes only. This field is the single
    # source of truth for any UI element claiming a TOTAL pending-
    # approval count.
    pending_approvals_count: int
    attention_incidents: list[AttentionIncident]
    pending_approvals: list[PendingApproval]
    activity: list[ActivityPoint]
    recent_events: list[RecentEvent]
