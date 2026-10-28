"""Database access for Phase 15's dashboard summary.

Deliberately NOT an ORM-mapped declarative model -- same bare
`sa.table()`/`sa.column()` Core-table convention
repositories/incident_repository.py already establishes. Reuses that
module's own `incidents_table`/`incident_events_table` and
remediation_repository.py's own `remediation_proposals_table` rather
than redefining them -- there is exactly one Core-table definition per
real table anywhere in this service.

Every query below is organization-scoped and bounded (a fixed LIMIT,
never an unbounded SELECT the application then aggregates in Python --
Phase 15 Gate 10: "Prevent unbounded incident fetching merely to
compute a dashboard chart. Use server-side aggregates when
necessary."). When `organization_id` is None (organization-context
enforcement disabled), every query below is intentionally unscoped --
identical to every other read endpoint's own legacy-mode behavior
elsewhere in this service, never a separate, weaker code path.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.repositories.incident_repository import incident_events_table, incidents_table
from control_plane.repositories.remediation_repository import remediation_proposals_table

# Matches domain/incident.py's own Severity Literal order exactly --
# used only to rank severity for the "needs attention" ordering below
# (critical first), never persisted or exposed as a new vocabulary.
_SEVERITY_RANK = sa.case(
    {"critical": 0, "warning": 1, "info": 2},
    value=incidents_table.c.severity,
    else_=3,
)

_ACTIVE_STATUSES = ("open", "acknowledged", "investigating", "remediating")


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_status_counts(self, organization_id: uuid.UUID | str | None) -> Mapping[str, int]:
        """One GROUP BY query -- never a `len()` over a fetched list."""
        stmt = sa.select(incidents_table.c.status, sa.func.count().label("count")).group_by(incidents_table.c.status)
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        rows = (await self._session.execute(stmt)).mappings().all()
        return {row["status"]: row["count"] for row in rows}

    async def get_active_critical_count(self, organization_id: uuid.UUID | str | None) -> int:
        stmt = sa.select(sa.func.count()).where(
            incidents_table.c.severity == "critical",
            incidents_table.c.status.in_(_ACTIVE_STATUSES),
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).scalar_one()

    async def list_attention_incidents(
        self, organization_id: uuid.UUID | str | None, limit: int = 8
    ) -> Sequence[Mapping]:
        """The highest-priority still-open incidents: severity first
        (critical, then warning, then info), most recently active
        within each severity. Bounded by `limit` -- this is the ENTIRE
        query the "needs attention" dashboard section ever runs, never
        a larger fetch trimmed down in application code."""
        stmt = (
            sa.select(incidents_table)
            .where(incidents_table.c.status.in_(_ACTIVE_STATUSES))
            .order_by(_SEVERITY_RANK.asc(), incidents_table.c.last_seen_at.desc())
            .limit(limit)
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).mappings().all()

    async def get_pending_approvals_count(self, organization_id: uuid.UUID | str | None) -> int:
        """Independent-review correction round, BLOCKER 3 bug B: a real
        SQL COUNT over EVERY pending proposal -- never `len()` of
        `list_pending_approvals`'s own bounded (`limit=8`) display list,
        which under-reports whenever more than 8 are actually pending.
        This is the dashboard's ONLY source for the "Pending approvals"
        metric card; the bounded list below remains for the "needs
        attention" section's display purposes only."""
        stmt = (
            sa.select(sa.func.count())
            .select_from(remediation_proposals_table)
            .join(incidents_table, incidents_table.c.id == remediation_proposals_table.c.incident_id)
            .where(remediation_proposals_table.c.status == "pending_approval")
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).scalar_one()

    async def list_pending_approvals(
        self, organization_id: uuid.UUID | str | None, limit: int = 8
    ) -> Sequence[Mapping]:
        """Pending remediation proposals, oldest-first (the longest-
        waiting approval is the most urgent), joined to their owning
        incident for display context in one round trip."""
        stmt = (
            sa.select(
                remediation_proposals_table.c.id.label("proposal_id"),
                remediation_proposals_table.c.incident_id,
                remediation_proposals_table.c.agent_run_id,
                remediation_proposals_table.c.action_type,
                remediation_proposals_table.c.target,
                remediation_proposals_table.c.proposed_at,
                incidents_table.c.title.label("incident_title"),
                incidents_table.c.severity.label("incident_severity"),
            )
            .join(incidents_table, incidents_table.c.id == remediation_proposals_table.c.incident_id)
            .where(remediation_proposals_table.c.status == "pending_approval")
            .order_by(remediation_proposals_table.c.proposed_at.asc())
            .limit(limit)
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).mappings().all()

    async def get_daily_severity_activity(
        self, organization_id: uuid.UUID | str | None, since: datetime, until: datetime
    ) -> Sequence[Mapping]:
        """One GROUP BY query over `first_seen_at::date, severity` --
        the incident-activity chart's entire data source. Bounded by
        the caller-supplied [since, until) window (Phase 15 Gate 4:
        "Never fabricate historical time-series points" -- every point
        this returns is a real count of real rows, and a day with zero
        incidents simply has no row at all, which the caller fills in
        as zero rather than this query inventing one)."""
        day = sa.func.date_trunc("day", incidents_table.c.first_seen_at).label("day")
        stmt = (
            sa.select(day, incidents_table.c.severity, sa.func.count().label("count"))
            .where(incidents_table.c.first_seen_at >= since, incidents_table.c.first_seen_at < until)
            .group_by(day, incidents_table.c.severity)
            .order_by(day.asc())
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).mappings().all()

    async def list_recent_events(
        self, organization_id: uuid.UUID | str | None, limit: int = 20
    ) -> Sequence[Mapping]:
        """The most recent incident-lifecycle audit events across every
        incident this organization owns, newest first -- the "recent
        activity" feed's entire data source. A single bounded,
        organization-filtered join; never a per-incident fan-out."""
        stmt = (
            sa.select(
                incident_events_table.c.id,
                incident_events_table.c.incident_id,
                incident_events_table.c.event_type,
                incident_events_table.c.actor_type,
                incident_events_table.c.previous_status,
                incident_events_table.c.new_status,
                incident_events_table.c.occurred_at,
                incidents_table.c.title.label("incident_title"),
                incidents_table.c.severity.label("incident_severity"),
            )
            .join(incidents_table, incidents_table.c.id == incident_events_table.c.incident_id)
            .order_by(incident_events_table.c.occurred_at.desc(), incident_events_table.c.id.desc())
            .limit(limit)
        )
        if organization_id is not None:
            stmt = stmt.where(incidents_table.c.organization_id == str(organization_id))
        return (await self._session.execute(stmt)).mappings().all()
