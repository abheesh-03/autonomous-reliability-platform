"""Phase 16 Gate 6: the smallest real detector that turns elevated,
REAL, authenticated telemetry into a REAL, tenant-scoped incident --
evaluated synchronously, inline, immediately after each accepted
telemetry batch (api/telemetry_ingest.py), not a separate polling
service. This is a deliberate scope choice for this round: it avoids
building new scheduling/polling infrastructure while still being a
genuine, reactive detector (an elevated error rate is reflected in the
dashboard and as a real incident within one ingestion cycle, not after
an arbitrary polling delay).

Reuses incident_repository.py's own existing upsert/resolve/fingerprint
machinery UNCHANGED -- this is explicitly NOT a parallel incident
system (Gate 6: "Do not create a parallel incident system"). The
fingerprint is `(source="otel-telemetry", source_fingerprint=
"service:<service_id>")` -- `service_id` is a real, globally-unique
UUID (reliability.services.id), so this fingerprint can never collide
across two different organizations' services even without an explicit
organization_id filter on the underlying lookup (get_active_incident),
exactly like every other ingestion path's own source+fingerprint
scoping.

The passed `organization_id` is ALWAYS the one already verified by
api/telemetry_ingest.py from the authenticated integration credential
-- this module has no code path that accepts one from anywhere else,
and never derives one from the telemetry payload itself (Gate 6: "Do
not accept an attacker-supplied organization ID as authorization").
"""

from datetime import UTC, datetime

from control_plane.repositories.incident_repository import IncidentRepository

TELEMETRY_INCIDENT_SOURCE = "otel-telemetry"

# Gate 6: a real, documented, deliberately simple threshold -- not a
# statistical anomaly model (detectors/anomaly/ already owns that
# class of detector for the platform's own internal services; Phase 16
# does not extend it to externally submitted telemetry this round).
# Requires BOTH a minimum sample size (so one or two real failed
# requests out of one real success never fires) AND a minimum error
# RATE within that window.
ERROR_RATE_THRESHOLD = 0.5
MIN_REQUESTS_FOR_EVALUATION = 3


def _fingerprint_for(service_id: str) -> str:
    return f"service:{service_id}"


async def evaluate_and_upsert(
    repo: IncidentRepository,
    *,
    organization_id: str,
    service_id: str,
    service_name: str,
    window_request_count: int,
    window_error_count: int,
    window_minutes: int,
    now: datetime | None = None,
) -> None:
    """Called once per accepted telemetry batch, after the batch's own
    rows are already durably written. Never raises for a healthy
    window -- an elevated-but-now-recovered window is handled by
    actively RESOLVING any still-active incident for this exact
    fingerprint (mirrors the platform's own existing "monitoring-
    resolved" pattern -- see ingestion/service.py's own Alertmanager
    resolution handling), so a real, if brief, incident never lingers
    open once its triggering condition has genuinely cleared."""
    reference_now = now or datetime.now(UTC)
    fingerprint = _fingerprint_for(service_id)

    error_rate = (window_error_count / window_request_count) if window_request_count > 0 else 0.0
    breached = window_request_count >= MIN_REQUESTS_FOR_EVALUATION and error_rate >= ERROR_RATE_THRESHOLD

    if breached:
        await repo.upsert_firing_incident(
            source=TELEMETRY_INCIDENT_SOURCE,
            source_fingerprint=fingerprint,
            title=f"{service_name} is returning an elevated error rate",
            description=(
                f"{window_error_count} of {window_request_count} requests "
                f"({error_rate:.0%}) in the last {window_minutes} minute(s) "
                "returned an HTTP 5xx response, as reported by this service's "
                "own authenticated OpenTelemetry integration."
            ),
            severity="critical" if error_rate >= 0.9 else "warning",
            first_seen_at=reference_now,
            last_seen_at=reference_now,
            occurrence_starts_at=reference_now,
            actor_type="otel-telemetry",
            organization_id=organization_id,
        )
        # upsert_firing_incident deliberately never commits itself (see
        # its own docstring) -- every real caller (ingestion/service.py's
        # own webhook path included) is responsible for committing its
        # own transaction explicitly.
        await repo.commit()
        return

    active = await repo.get_active_incident(source=TELEMETRY_INCIDENT_SOURCE, source_fingerprint=fingerprint)
    if active is not None:
        await repo.resolve_active_incident_for_fingerprint(
            active["id"],
            resolved_at=reference_now,
            actor_type="otel-telemetry",
            resolution_source="otel_telemetry_threshold",
        )
        await repo.commit()
