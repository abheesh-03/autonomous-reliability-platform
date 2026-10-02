"""Orchestrates turning a validated Alertmanager webhook payload into
reliability.incidents writes.

Phase 3C handled FIRING observations only; resolved alerts were
validated and acknowledged but never acted on. Phase 3D now also
implements real, source-driven automatic resolution — see
docs/architecture/phase-3d-incident-lifecycle.md for the full design
and the "remaining limitations" section for what the Alertmanager
webhook event model does not let this service verify with absolute
certainty.

All SQL lives in the repository (repositories/incident_repository.py);
all field derivation lives in ingestion/mapping.py; this module
sequences them, applies the occurrence-identity (stale/recurrence)
decision logic, and commits once per batch.

Occurrence identity and the stale/recurrence decision
-------------------------------------------------------
Alertmanager's webhook model gives each alert a `fingerprint` (stable
across the lifetime of one occurrence) and a `startsAt` (fixed at
when that occurrence began firing, unchanged across every redelivery
of it).

Post-review correction: the first version of this module compared an
incoming alert's `startsAt` against the matching incident's
`first_seen_at`. That is wrong whenever an active incident accepts a
NEWER firing observation without having been resolved first (see the
"accepted newer firing" branch below) — `first_seen_at` is deliberately
immutable, so after that happens it no longer reflects which
occurrence the row actually represents. Independent review reproduced
the resulting regression directly: a delayed resolved notification for
the ORIGINAL (superseded) occurrence could incorrectly resolve the
incident, and a delayed duplicate firing replay of the occurrence it
now represents, arriving after that occurrence genuinely resolved,
could be mistaken for a brand new recurrence and spawn a second,
spurious incident. The fix: a second, durable column,
`occurrence_starts_at` (database/migrations/V2__add_occurrence_watermark.sql,
repositories/incident_repository.py), records the LATEST accepted
firing `startsAt` for a fingerprint's row, separately from
`first_seen_at` (which keeps meaning exactly what it always meant: when
THIS row was first created). Every comparison below is against this
watermark, never against `first_seen_at`.

This module treats (source, fingerprint, startsAt) as an occurrence's
identity — incoming `startsAt` is compared against the matching
incident's `occurrence_starts_at` watermark to tell apart:

  - A repeat delivery of the CURRENTLY ACTIVE occurrence
    (startsAt == active incident's occurrence_starts_at) -> update it
    (the watermark does not need to move; it is already correct).
  - A firing delivery NEWER than the currently active incident's
    watermark (startsAt > occurrence_starts_at) -> also update it, AND
    advance the watermark to this startsAt (repositories/incident_repository.py's
    upsert_firing_incident does this via GREATEST). The partial unique
    index guarantees this can only happen while the existing row is
    still active, so it can never be confused with a genuine
    resolved-then-recurred occurrence (which always goes through the
    "no active incident" branch below, since the prior one is resolved
    by the time a true recurrence fires) — it means the active row was
    never resolved (a missed/delayed resolved notification, or simply a
    prior delivery predating this logic) but Alertmanager is reporting
    newer firing activity for it regardless. Updating keeps the
    incident current rather than stranding it on stale data
    indefinitely; first_seen_at/status are never touched by the update
    either way.
  - A firing delivery OLDER than the currently active incident's
    watermark (startsAt < occurrence_starts_at) -> a stale/delayed
    replay of an occurrence that predates the one the row now
    represents; ignored, never regresses the active incident or its
    watermark.
  - A stale/delayed replay of an occurrence that has ALREADY been
    resolved (no active incident exists, but the most recent
    historical row for this fingerprint has occurrence_starts_at >=
    startsAt) -> ignore it; never reopen or recreate. This is exactly
    the case the original first_seen_at-based comparison got wrong: a
    resolved row's watermark reflects the LATEST occurrence it ever
    accepted while active, not merely the first one, so a delayed
    replay of that latest occurrence is correctly recognized as stale
    even though it may be newer than the row's own (unchanged)
    first_seen_at.
  - A genuinely NEW occurrence (no active incident exists, and startsAt
    is strictly newer than the most-recent-historical row's watermark)
    -> create a new incident, leaving prior history untouched.
  - A resolved alert is only ever applied to the currently active
    incident, and only if its startsAt EXACTLY MATCHES that incident's
    current watermark. Strictly older -> a stale notification for an
    occurrence the row has since moved past (protects it from being
    resolved by a replay of the occurrence it superseded). Strictly
    newer -> a resolved notification for an occurrence that was never
    observed firing at all; this service has no basis for concluding it
    pertains to the currently active occurrence rather than some future
    one it hasn't seen yet, so it is also ignored rather than "blindly"
    resolving an older incident (a documented limitation — see
    docs/architecture/phase-3d-incident-lifecycle.md). Only an exact
    watermark match resolves it.

Concurrency
-----------
Every alert in a batch is processed only after a transaction-scoped
PostgreSQL advisory lock (repositories/incident_repository.py's
acquire_fingerprint_lock) has been acquired for its (source,
fingerprint) — ALL distinct fingerprints touched by the batch are
locked up front, in a stable sorted order, before any of them are
processed, to avoid a deadlock against another concurrent batch
touching an overlapping fingerprint set in a different order. The
actual writes themselves (upsert_firing_incident,
resolve_active_incident_for_fingerprint) are each a single atomic
conditional statement, independently race-free against a concurrent
operator PATCH on the same row even without the advisory lock — the
lock's job is specifically to protect the multi-step SELECT-then-decide
sequence the stale/recurrence logic above requires, which a single SQL
statement cannot express.
"""

from datetime import UTC, datetime
from typing import Protocol

from control_plane.domain.alertmanager_webhook import AlertmanagerAlert, AlertmanagerWebhookPayload, WebhookAckResponse
from control_plane.ingestion.mapping import map_firing_alert_to_incident_fields


class SupportsIngestion(Protocol):
    async def get_active_incident(self, **kwargs: object) -> object: ...
    async def get_most_recent_incident(self, **kwargs: object) -> object: ...
    async def acquire_fingerprint_lock(self, **kwargs: object) -> None: ...
    async def upsert_firing_incident(self, **fields: object) -> tuple[object, bool]: ...
    async def resolve_active_incident_for_fingerprint(self, incident_id: object, **kwargs: object) -> object: ...
    async def commit(self) -> None: ...


async def _process_firing_alert(repo: SupportsIngestion, alert: AlertmanagerAlert, *, ingested_at: datetime) -> str:
    """Returns one of "created", "updated", "ignored"."""
    active = await repo.get_active_incident(source="alertmanager", source_fingerprint=alert.fingerprint)

    if active is not None:
        if alert.startsAt < active["occurrence_starts_at"]:
            # A firing delivery OLDER than the occurrence watermark
            # currently active for this fingerprint — a stale/delayed
            # replay of an occurrence that predates the one the row now
            # represents. An active row already exists and the partial
            # unique index would block a second one, so the safe
            # choice is to leave the active incident (and its
            # watermark) untouched rather than regress it with older
            # data.
            return "ignored"
        # startsAt == active's occurrence_starts_at: a genuine repeat
        # delivery of the exact same occurrence.
        # startsAt > active's occurrence_starts_at: the active incident
        # was never resolved (e.g. a resolved notification was missed,
        # or simply predates this capability existing at all) but
        # Alertmanager is reporting this exact fingerprint firing with a
        # LATER startsAt than our watermark. The partial unique index
        # means this can only be reached while the old row is still
        # active, so this can never be confused with a genuine
        # resolved-then-recurred B (which always goes through the "no
        # active" branch below, since A is resolved by the time B
        # fires). Treating it as an update — never create, never
        # ignore — keeps the incident current rather than stranding it
        # on stale data indefinitely; first_seen_at and status are
        # never touched by the upsert, but occurrence_starts_at DOES
        # advance to this alert's startsAt (via the repository's
        # GREATEST) — that advancement is exactly what lets a later
        # resolved notification FOR THIS SAME newer occurrence (not the
        # original one) go on to match and resolve it correctly.
        fields = map_firing_alert_to_incident_fields(alert, ingested_at=ingested_at)
        await repo.upsert_firing_incident(**fields)
        return "updated"

    most_recent = await repo.get_most_recent_incident(source="alertmanager", source_fingerprint=alert.fingerprint)
    if most_recent is not None and alert.startsAt <= most_recent["occurrence_starts_at"]:
        # A stale/delayed replay of an occurrence that has already been
        # resolved (or closed) — at or before the most recent known
        # occurrence's own watermark — never reopen it, never create a
        # duplicate. Comparing against the watermark here (not the
        # historical row's immutable first_seen_at) is what correctly
        # rejects a delayed replay of whatever occurrence that row most
        # recently accepted while it was still active, even when that
        # watermark is newer than the row's own first_seen_at. A
        # genuinely new occurrence always carries a startsAt strictly
        # newer than the watermark and is handled by the branch below.
        return "ignored"

    # No active incident, and either no history at all for this
    # fingerprint or the most recent historical row's watermark is
    # older than this delivery — a genuinely new (possibly recurring)
    # occurrence.
    fields = map_firing_alert_to_incident_fields(alert, ingested_at=ingested_at)
    await repo.upsert_firing_incident(**fields)
    return "created"


async def _process_resolved_alert(repo: SupportsIngestion, alert: AlertmanagerAlert) -> str:
    """Returns one of "resolved", "ignored"."""
    active = await repo.get_active_incident(source="alertmanager", source_fingerprint=alert.fingerprint)

    if active is None:
        # Safe, idempotent no-op: nothing is currently active for this
        # fingerprint (already resolved by an earlier delivery or a
        # concurrent operator PATCH, or this fingerprint was never
        # ingested at all).
        return "ignored"

    if alert.startsAt != active["occurrence_starts_at"]:
        # Only an EXACT watermark match resolves the active incident —
        # not "equal or newer", which is what the original (incorrect)
        # first_seen_at-based comparison effectively allowed once
        # first_seen_at could no longer move. Two distinct unsafe cases
        # this equality check rejects:
        #   - strictly OLDER than the watermark: a delayed resolved
        #     notification for an occurrence this incident has since
        #     moved past (e.g. resolved notification for A arriving
        #     after a newer firing B already updated this same row and
        #     advanced the watermark) — must never resolve the incident
        #     using stale evidence for the occurrence it superseded.
        #   - strictly NEWER than the watermark: a resolved notification
        #     for an occurrence that was never observed firing at all.
        #     This service cannot distinguish "this really is the
        #     currently active occurrence, just a notification we never
        #     saw fire" from "this is for some future occurrence that
        #     hasn't happened yet" — it has no positive evidence either
        #     way, so it conservatively refuses to resolve rather than
        #     blindly resolving an incident that might not actually
        #     correspond to it. Documented limitation, not a gap: see
        #     docs/architecture/phase-3d-incident-lifecycle.md.
        return "ignored"

    # endsAt is guaranteed present, tz-aware, and >= startsAt by
    # domain/alertmanager_webhook.py's own validation for every
    # resolved alert reaching this point.
    resolved_row = await repo.resolve_active_incident_for_fingerprint(active["id"], resolved_at=alert.endsAt)
    if resolved_row is None:
        # Lost a race to a concurrent operator PATCH (or another
        # resolved delivery) that resolved/closed this exact row
        # between our SELECT above and this UPDATE — already resolved
        # by someone else; treat as an idempotent no-op, not an error.
        return "ignored"
    return "resolved"


async def ingest_alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    repo: SupportsIngestion,
) -> WebhookAckResponse:
    firing = [a for a in payload.alerts if a.status == "firing"]
    resolved = [a for a in payload.alerts if a.status == "resolved"]

    # Deterministic lock ordering across the WHOLE batch (firing and
    # resolved alike): every distinct fingerprint this batch will touch
    # is locked up front, sorted, before any of them are processed —
    # see this module's own docstring on why, and
    # repositories/incident_repository.py's acquire_fingerprint_lock
    # docstring for the locking mechanism itself.
    distinct_fingerprints = sorted({a.fingerprint for a in firing} | {a.fingerprint for a in resolved})
    for fingerprint in distinct_fingerprints:
        await repo.acquire_fingerprint_lock(source="alertmanager", source_fingerprint=fingerprint)

    # One ingestion timestamp for the whole batch ("the time of
    # accepted firing ingestion"), not each alert's own startsAt.
    ingested_at = datetime.now(UTC)

    created = updated = resolved_count = ignored = 0

    # Processed sequentially within the ONE transaction `repo.commit()`
    # closes below — every lock needed is already held (acquired
    # above), so processing order here cannot introduce a deadlock.
    for alert in firing:
        outcome = await _process_firing_alert(repo, alert, ingested_at=ingested_at)
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        else:
            ignored += 1

    for alert in resolved:
        outcome = await _process_resolved_alert(repo, alert)
        if outcome == "resolved":
            resolved_count += 1
        else:
            ignored += 1

    # Single transaction for the whole batch: if anything above raised,
    # we never reach this commit, and the underlying session's implicit
    # rollback-on-close (db/session.py) means NONE of this batch's
    # writes are persisted — never a partial write. A raised
    # SQLAlchemyError/OSError propagates to main.py's global handlers,
    # which return 503 so Alertmanager retries delivery.
    await repo.commit()

    return WebhookAckResponse(
        firing_processed=len(firing),
        resolved_processed=len(resolved),
        incidents_created=created,
        incidents_updated=updated,
        incidents_resolved=resolved_count,
        incidents_ignored=ignored,
    )
