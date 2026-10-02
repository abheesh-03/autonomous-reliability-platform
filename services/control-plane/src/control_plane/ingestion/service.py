"""Orchestrates turning a validated Alertmanager webhook payload into
reliability.incidents writes.

Phase 3C handles incoming FIRING observations only. For each alert in
the batch whose status == "resolved": its envelope has already been
validated by Pydantic (domain/alertmanager_webhook.py) and it is
counted in the acknowledgement response, but it is never written
anywhere — no incident is created from a resolved-only notification,
no existing incident's status/resolved_at is touched, nothing is
deleted, and nothing is auto-reopened. That is a deliberate, temporary
Phase 3C boundary, not an oversight: Phase 3D owns the incident state
machine, including what a resolved Alertmanager notification should
actually do to an incident's lifecycle.

All SQL lives in the repository (repositories/incident_repository.py);
all field derivation lives in ingestion/mapping.py; this module only
sequences them and commits once.
"""

from datetime import UTC, datetime
from typing import Protocol

from control_plane.domain.alertmanager_webhook import AlertmanagerWebhookPayload, WebhookAckResponse
from control_plane.ingestion.mapping import map_firing_alert_to_incident_fields


class SupportsIngestion(Protocol):
    async def upsert_firing_incident(self, **fields: object) -> tuple[object, bool]: ...
    async def commit(self) -> None: ...


async def ingest_alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    repo: SupportsIngestion,
) -> WebhookAckResponse:
    firing = [a for a in payload.alerts if a.status == "firing"]
    resolved_count = sum(1 for a in payload.alerts if a.status == "resolved")

    # One ingestion timestamp for the whole batch ("the time of
    # accepted firing ingestion"), not each alert's own startsAt.
    ingested_at = datetime.now(UTC)

    created = 0
    updated = 0
    # Processed sequentially, within the ONE transaction `repo.commit()`
    # closes below. If Alertmanager (or a retried delivery) includes
    # the same fingerprint twice in a single batch, each occurrence is
    # just another sequential UPSERT against the same row — the last
    # occurrence in the list wins for title/description/severity/
    # last_seen_at, exactly as two separate webhook deliveries would
    # behave. No separate in-memory dedup pass is needed.
    for alert in firing:
        fields = map_firing_alert_to_incident_fields(alert, ingested_at=ingested_at)
        _, was_created = await repo.upsert_firing_incident(**fields)
        if was_created:
            created += 1
        else:
            updated += 1

    # Single transaction for the whole batch: if any upsert above
    # raised, we never reach this commit, and the underlying session's
    # implicit rollback-on-close (db/session.py) means NONE of this
    # batch's upserts are persisted — never a partial write. A raised
    # SQLAlchemyError propagates to main.py's global handler, which
    # returns 503 so Alertmanager retries delivery.
    await repo.commit()

    return WebhookAckResponse(
        firing_processed=len(firing),
        resolved_ignored=resolved_count,
        incidents_created=created,
        incidents_updated=updated,
    )
