"""Phase 15 dashboard summary endpoint.

ONE new, read-only, organization-scoped, bounded aggregate endpoint --
exactly the kind of server-side aggregate Phase 15 Gate 10 calls for
("Prevent unbounded incident fetching merely to compute a dashboard
chart. Use server-side aggregates when necessary.") instead of having
the web console fetch every incident and compute counts/charts
client-side. Every number this returns is a real count of real rows;
see repositories/dashboard_repository.py for the exact bounded query
behind each field.

Phase 15 independent-review correction round, BLOCKER 1: tenant
scoping no longer follows incidents.py's own legacy-tolerant pattern.
Like /api/v1/services (Gate 7), this is a brand-new Phase 15 resource
with no pre-Phase-14 unscoped precedent to preserve -- there is no
"fall back to the one shared legacy organization" behavior that would
ever be correct for a dashboard a real user is viewing today. This
endpoint ALWAYS requires a real, verified actor via
`require_actor_context` (never the nullable `get_actor_context`,
which skips verification entirely whenever
CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is disabled -- this
platform's own real local-development default; see
core/authz.py::require_actor_context's own docstring, and
api/services.py, which established this exact pattern first). Every
query below is unconditionally scoped to the verified actor's own
organization_id -- never `None`, never unscoped, regardless of the
organization-context enforcement flag.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from control_plane.api.dependencies import get_dashboard_repository
from control_plane.core.authz import ActorContext, require_actor_context
from control_plane.domain.dashboard import (
    ActivityPoint,
    AttentionIncident,
    DashboardSummary,
    PendingApproval,
    RecentEvent,
    StatusCounts,
)
from control_plane.repositories.dashboard_repository import DashboardRepository

router = APIRouter(prefix="/api/v1")

_ACTIVITY_WINDOW_DAYS_DEFAULT = 14
_ACTIVITY_WINDOW_DAYS_MAX = 90


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    repo: Annotated[DashboardRepository, Depends(get_dashboard_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
    activity_days: Annotated[
        int, Query(ge=1, le=_ACTIVITY_WINDOW_DAYS_MAX, description="Width of the activity window, in days")
    ] = _ACTIVITY_WINDOW_DAYS_DEFAULT,
) -> DashboardSummary:
    organization_id = actor.organization_id

    status_counts, active_critical, pending_approvals_count, attention_rows, approval_rows, event_rows = (
        await _gather(repo, organization_id)
    )

    # `activity_days` calendar days INCLUDING today -- today - (N-1)
    # through today, inclusive, N dates total. `since` is midnight UTC
    # on the first of those days; `until` is the real current moment
    # (never midnight tomorrow), so today's own not-yet-complete data
    # is correctly included rather than excluded for being "in the
    # future" relative to a day boundary.
    until = datetime.now(UTC)
    today = until.date()
    first_day = today - timedelta(days=activity_days - 1)
    since = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    activity_rows = await repo.get_daily_severity_activity(organization_id, since=since, until=until)

    # Fills every day in [first_day, today] inclusive explicitly -- a
    # day with zero incidents is a REAL zero, present in the response,
    # never simply absent (which a chart would otherwise be unable to
    # distinguish from "no data collected for that day at all").
    by_day: dict[str, ActivityPoint] = {}
    cursor = first_day
    while cursor <= today:
        by_day[cursor.isoformat()] = ActivityPoint(day=cursor)
        cursor += timedelta(days=1)
    for row in activity_rows:
        key = row["day"].date().isoformat()
        point = by_day.get(key)
        if point is None:
            # The query's own window bounds already constrain this,
            # but never trust that alone -- an out-of-window row is
            # dropped rather than silently widening the chart.
            continue
        severity = row["severity"]
        if severity == "critical":
            point.critical = row["count"]
        elif severity == "warning":
            point.warning = row["count"]
        elif severity == "info":
            point.info = row["count"]

    return DashboardSummary(
        generated_at=until,
        counts=StatusCounts(**status_counts, active_critical=active_critical),
        # Independent-review correction round, BLOCKER 3 bug B: a real,
        # unbounded SQL COUNT -- NEVER len(pending_approvals), which is
        # silently wrong whenever more than list_pending_approvals's own
        # `limit=8` are actually pending. `pending_approvals` below
        # remains the bounded, display-only list for the "needs
        # attention" section; this count is the ONLY source for the
        # "Pending approvals" metric card.
        pending_approvals_count=pending_approvals_count,
        attention_incidents=[AttentionIncident.model_validate(dict(row)) for row in attention_rows],
        pending_approvals=[PendingApproval.model_validate(dict(row)) for row in approval_rows],
        activity=sorted(by_day.values(), key=lambda point: point.day),
        recent_events=[RecentEvent.model_validate(dict(row)) for row in event_rows],
    )


async def _gather(repo: DashboardRepository, organization_id: object):
    # Sequential, not asyncio.gather: every query above shares ONE
    # request-scoped AsyncSession (api/dependencies.py), and a single
    # asyncpg connection cannot run more than one query concurrently --
    # see db/session.py's own pooling model. Six small, independently
    # bounded queries in sequence is still far cheaper than fetching
    # every incident and aggregating in Python.
    status_counts = await repo.get_status_counts(organization_id)
    active_critical = await repo.get_active_critical_count(organization_id)
    pending_approvals_count = await repo.get_pending_approvals_count(organization_id)
    attention_rows = await repo.list_attention_incidents(organization_id)
    # Gate 7 visual polish: the dashboard's OWN "recent activity" card
    # shows at most 8 items (never the full 20 the bounded query
    # supports) -- no genuine supporting "view full history" page
    # exists yet, so this is reduced at the query level rather than
    # fetched-then-truncated client-side with a link to nowhere.
    event_rows = await repo.list_recent_events(organization_id, limit=8)
    approval_rows = await repo.list_pending_approvals(organization_id)
    return status_counts, active_critical, pending_approvals_count, attention_rows, approval_rows, event_rows
