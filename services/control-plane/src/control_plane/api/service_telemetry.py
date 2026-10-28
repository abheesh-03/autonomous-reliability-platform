"""Phase 16 Gate 5: the Services page's real telemetry-summary
endpoint. ALWAYS requires a real, verified actor (require_actor_context,
unconditional -- same pattern every Phase 15/16 services-registry route
already uses); the returned window is scoped to the actor's own
organization AND the specific service id, both checked via
ServiceRepository.get_by_id_for_organization before any telemetry query
ever runs -- a service id belonging to a different organization 404s,
exactly like every other cross-tenant lookup in this service.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from control_plane.api.dependencies import (
    get_integration_credential_repository,
    get_service_repository,
    get_telemetry_repository,
)
from control_plane.core.authz import ActorContext, require_actor_context
from control_plane.domain.telemetry import ConnectionStatus, TelemetrySummary
from control_plane.repositories.integration_credential_repository import IntegrationCredentialRepository
from control_plane.repositories.service_repository import ServiceRepository
from control_plane.repositories.telemetry_repository import TelemetryRepository

router = APIRouter(prefix="/api/v1")

# Gate 5: "Use bounded time-window queries." Default/max both modest --
# this is a live operator dashboard, not a historical analytics tool.
DEFAULT_WINDOW_MINUTES = 15
MAX_WINDOW_MINUTES = 180

# Gate 5: the exact dividing line between RECEIVING_TELEMETRY (fresh)
# and STALE_DATA (was connected, has gone quiet) -- a real instrumented
# client exporting every few seconds to a couple of minutes would never
# naturally cross this during normal operation.
STALE_AFTER = timedelta(minutes=10)


def _derive_status(
    *, has_any_credential: bool, all_revoked: bool, last_observed_at: datetime | None, now: datetime
) -> ConnectionStatus:
    # Gate 5's own required state machine, in the order it must be
    # evaluated: REVOKED and NOT_CONFIGURED are absolute (no credential
    # at all, or every credential this service has ever had is
    # revoked, overrides everything else); only then does the
    # presence/recency of real telemetry distinguish the remaining
    # three states. "A registered service is not automatically
    # healthy. Missing telemetry is not proof of availability."
    if not has_any_credential:
        return "not_configured"
    if all_revoked:
        return "revoked"
    if last_observed_at is None:
        return "configured_awaiting_data"
    if now - last_observed_at > STALE_AFTER:
        return "stale_data"
    return "receiving_telemetry"


@router.get("/services/{service_id}/telemetry-summary", response_model=TelemetrySummary)
async def get_service_telemetry_summary(
    service_id: str,
    services: Annotated[ServiceRepository, Depends(get_service_repository)],
    credentials: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    telemetry: Annotated[TelemetryRepository, Depends(get_telemetry_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
    window_minutes: Annotated[int, Query(ge=1, le=MAX_WINDOW_MINUTES)] = DEFAULT_WINDOW_MINUTES,
) -> TelemetrySummary:
    service = await services.get_by_id_for_organization(actor.organization_id, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="service not found")

    integration_rows = await credentials.list_for_service(actor.organization_id, service_id)
    has_any_credential = len(integration_rows) > 0
    all_revoked = has_any_credential and all(row["status"] == "revoked" for row in integration_rows)

    now = datetime.now(UTC)
    since = now - timedelta(minutes=window_minutes)
    aggregate = await telemetry.get_window_aggregate(
        organization_id=actor.organization_id, service_id=service_id, since=since, until=now
    )
    last_observed_at = await telemetry.get_last_observed_at(
        organization_id=actor.organization_id, service_id=service_id
    )

    status = _derive_status(
        has_any_credential=has_any_credential,
        all_revoked=all_revoked,
        last_observed_at=last_observed_at,
        now=now,
    )

    request_count = int(aggregate["request_count"] or 0)
    error_count = int(aggregate["error_count"] or 0)

    return TelemetrySummary(
        service_id=str(service_id),
        status=status,
        window_minutes=window_minutes,
        request_count=request_count,
        error_count=error_count,
        request_rate_per_minute=round(request_count / window_minutes, 4) if window_minutes > 0 else 0.0,
        error_rate=round(error_count / request_count, 4) if request_count > 0 else None,
        mean_latency_seconds=aggregate["mean_latency_seconds"],
        last_observed_at=last_observed_at,
    )
