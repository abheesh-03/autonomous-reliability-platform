"""Orchestrates turning a validated, authenticated Kubernetes finding
into a reliability.incidents write (Phase 12B-D, Gate 2).

Deliberately structured as the Kubernetes-specific analogue of
ingestion/service.py's own `_process_firing_alert`, reusing the EXACT
same occurrence-identity primitives (get_active_incident/
get_most_recent_incident/acquire_fingerprint_lock/upsert_firing_incident)
-- never a second, parallel ingestion architecture. The one structural
difference: there is no Kubernetes analogue of an Alertmanager
"resolved" notification (a detector's absence of a finding is never
positive evidence of recovery -- Gate 2: "missing signals never mean
healthy"), so this module has no `_process_resolved_finding` at all.
Incident resolution for a Kubernetes-sourced incident is Gate 7's own
responsibility (independent, fresh recovery verification), reached
exclusively through the existing authenticated operator lifecycle
endpoint (api/incidents.py, CONTROL_PLANE_LIFECYCLE_TOKEN) -- never
through this ingestion path.

Occurrence identity
--------------------
`collected_at` (the detector's own observation-collection instant)
plays EXACTLY the role Alertmanager's `startsAt` plays in
ingestion/service.py, reusing the SAME `occurrence_starts_at` watermark
column (database/migrations/V2__add_occurrence_watermark.sql):

  - An active incident exists for this fingerprint and the incoming
    `collected_at` is older than its current watermark -> a stale/
    delayed replay of evidence that predates what this row now
    represents; IGNORED, never regresses the active incident.
  - An active incident exists and `collected_at` is at or after the
    watermark -> accepted as a continuing observation of the SAME
    ongoing failure; UPDATED (last_seen_at/occurrence_starts_at
    advance, title/description/severity refresh to this finding's own
    values).
  - No active incident, and the most recent historical row for this
    fingerprint (any status) has a watermark at or after this
    `collected_at` -> a stale replay of an occurrence this fingerprint
    has already moved past; IGNORED, never reopens history.
  - No active incident, and either no history at all or the most
    recent historical row's watermark is strictly older -> a genuinely
    new (possibly recurring) occurrence; CREATED.

Resource identity (UID) is never part of the fingerprint (see
ingestion/kubernetes_mapping.py's own docstring) -- a resource
recreated under the same name, still exhibiting the same failure
class, continues to update the SAME incident row. Every accepted
UID this fingerprint is ever observed under is still recorded, plainly
and honestly, in incident_events.metadata -- auditable, never silently
discarded, but never used here to auto-split or auto-resolve an
incident (Gate 2: "recovered and newly recreated resources must be
distinguishable" is satisfied by the audit trail, not by this module
inventing a second incident for the same operational concern)."""

from datetime import UTC, datetime
from typing import Literal, Protocol

from control_plane.domain.kubernetes_finding import KubernetesFindingIngestRequest
from control_plane.ingestion.kubernetes_mapping import (
    kubernetes_finding_event_metadata,
    kubernetes_finding_fingerprint,
    map_kubernetes_finding_to_incident_fields,
)

IngestOutcome = Literal["created", "updated", "ignored"]

# A generous, but real, bound on how far "in the future" a caller's own
# `collected_at` may be relative to this server's wall clock -- large
# enough to tolerate ordinary clock skew between this process and
# whatever ran the detector pipeline, small enough that it can never be
# mistaken for "evidence from the future is trustworthy." A finding
# whose collected_at exceeds this is rejected outright (422, never
# silently clamped or silently accepted) -- Gate 2: "a previous stale
# event must not establish current failure" has a symmetric sibling
# here: a FUTURE-dated event must not establish one either.
MAX_FUTURE_SKEW_SECONDS = 300

# Correction round (Issue 6): a symmetric PAST bound -- "old detector
# observations cannot create a new active incident as though the
# failure is current". A finding collected long enough ago that it can
# no longer be trusted to describe CURRENT cluster state is rejected
# outright (422), regardless of whether this would create a new
# incident or update/ignore an existing one -- this check runs BEFORE
# any occurrence-identity decision. Deliberately more generous than
# MAX_FUTURE_SKEW_SECONDS: a legitimate detector-pipeline-to-ingestion
# delay (collection, CLI processing, network) is expected to take real
# seconds-to-low-minutes, never hours; 30 minutes is a real, bounded
# freshness requirement, not an arbitrary cosmetic one.
MAX_PAST_STALENESS_SECONDS = 1800


class KubernetesIngestionRejected(Exception):
    """The finding itself is well-formed per its own Pydantic model,
    but this service rejects it on a freshness/clock-skew ground the
    domain model cannot check on its own (it has no access to "now").
    The caller (api/kubernetes.py) turns this into HTTP 422."""


class SupportsKubernetesIngestion(Protocol):
    async def get_active_incident(self, **kwargs: object) -> object: ...
    async def get_most_recent_incident(self, **kwargs: object) -> object: ...
    async def acquire_fingerprint_lock(self, **kwargs: object) -> None: ...
    async def upsert_firing_incident(self, **fields: object) -> tuple[object, bool]: ...
    async def commit(self) -> None: ...


async def ingest_kubernetes_finding(
    finding: KubernetesFindingIngestRequest,
    repo: SupportsKubernetesIngestion,
    *,
    now: datetime | None = None,
) -> tuple[str, IngestOutcome, str]:
    """Returns (incident_id, outcome, severity). Commits once, exactly
    like ingest_alertmanager_webhook -- a single, all-or-nothing
    transaction per finding."""
    now = now or datetime.now(UTC)
    if (finding.collected_at - now).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
        raise KubernetesIngestionRejected(
            f"collected_at ({finding.collected_at.isoformat()}) is implausibly far in the future "
            f"relative to this server's own clock -- rejected, never accepted as current evidence"
        )
    if (now - finding.collected_at).total_seconds() > MAX_PAST_STALENESS_SECONDS:
        # Correction round (Issue 6): an old detector observation must
        # never create (or update) an incident as though the failure
        # is CURRENT -- this is checked unconditionally, before any
        # active/most-recent incident lookup, so it applies equally to
        # what would otherwise become a brand-new incident (which has
        # no existing watermark to compare staleness against at all).
        raise KubernetesIngestionRejected(
            f"collected_at ({finding.collected_at.isoformat()}) is more than {MAX_PAST_STALENESS_SECONDS} seconds "
            f"old relative to this server's own clock -- too stale to establish a current failure, rejected"
        )

    fingerprint = kubernetes_finding_fingerprint(finding)
    await repo.acquire_fingerprint_lock(source="kubernetes", source_fingerprint=fingerprint)

    fields = map_kubernetes_finding_to_incident_fields(finding, ingested_at=now)
    extra_metadata = kubernetes_finding_event_metadata(finding)

    active = await repo.get_active_incident(source="kubernetes", source_fingerprint=fingerprint)
    if active is not None:
        if finding.collected_at < active["occurrence_starts_at"]:
            await repo.commit()
            return str(active["id"]), "ignored", active["severity"]
        incident_id, _created = await repo.upsert_firing_incident(
            **fields, actor_type="kubernetes", extra_metadata=extra_metadata
        )
        await repo.commit()
        return str(incident_id), "updated", fields["severity"]

    most_recent = await repo.get_most_recent_incident(source="kubernetes", source_fingerprint=fingerprint)
    if most_recent is not None and finding.collected_at <= most_recent["occurrence_starts_at"]:
        await repo.commit()
        return str(most_recent["id"]), "ignored", most_recent["severity"]

    incident_id, _created = await repo.upsert_firing_incident(
        **fields, actor_type="kubernetes", extra_metadata=extra_metadata
    )
    await repo.commit()
    return str(incident_id), "created", fields["severity"]
