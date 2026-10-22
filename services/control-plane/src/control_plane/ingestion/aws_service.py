"""Orchestrates turning a validated, authenticated AWS finding into a
reliability.incidents write (Phase 13, Gate 4). Mirrors
`ingestion/kubernetes_service.py`'s own structure, occurrence-identity
primitives, and freshness bounds exactly -- never a second, parallel
ingestion architecture. Like the Kubernetes path, there is no
`_process_resolved_finding` here either: a detector's absence of a
finding (or CloudWatch reporting OK, or an AWS API returning an empty
response) is never positive evidence of recovery (Gate 4: "Never
resolve an incident merely because an alarm disappears or a source
returns an empty response"). Incident resolution for an AWS-sourced
incident remains exclusively the authenticated operator lifecycle
endpoint's job, same as Kubernetes.
"""

from datetime import UTC, datetime
from typing import Literal, Protocol

from control_plane.domain.aws_finding import AwsFindingIngestRequest
from control_plane.ingestion.aws_mapping import (
    aws_finding_event_metadata,
    aws_finding_fingerprint,
    map_aws_finding_to_incident_fields,
)

IngestOutcome = Literal["created", "updated", "ignored"]

# Same bounds, same rationale as kubernetes_service.py's own
# MAX_FUTURE_SKEW_SECONDS/MAX_PAST_STALENESS_SECONDS -- kept as
# separate constants (not imported from kubernetes_service.py) so each
# ingestion domain's freshness policy can be tuned independently in the
# future without any cross-module coupling.
MAX_FUTURE_SKEW_SECONDS = 300
MAX_PAST_STALENESS_SECONDS = 1800


class AwsIngestionRejected(Exception):
    """The finding itself is well-formed per its own Pydantic model,
    but this service rejects it on a freshness/clock-skew ground the
    domain model cannot check on its own. The caller (api/aws.py) turns
    this into HTTP 422."""


class SupportsAwsIngestion(Protocol):
    async def get_active_incident(self, **kwargs: object) -> object: ...
    async def get_most_recent_incident(self, **kwargs: object) -> object: ...
    async def acquire_fingerprint_lock(self, **kwargs: object) -> None: ...
    async def upsert_firing_incident(self, **fields: object) -> tuple[object, bool]: ...
    async def commit(self) -> None: ...


async def ingest_aws_finding(
    finding: AwsFindingIngestRequest,
    repo: SupportsAwsIngestion,
    *,
    now: datetime | None = None,
) -> tuple[str, IngestOutcome, str]:
    """Returns (incident_id, outcome, severity). Commits once, exactly
    like ingest_kubernetes_finding -- a single, all-or-nothing
    transaction per finding."""
    now = now or datetime.now(UTC)
    if (finding.collected_at - now).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
        raise AwsIngestionRejected(
            f"collected_at ({finding.collected_at.isoformat()}) is implausibly far in the future "
            f"relative to this server's own clock -- rejected, never accepted as current evidence"
        )
    if (now - finding.collected_at).total_seconds() > MAX_PAST_STALENESS_SECONDS:
        raise AwsIngestionRejected(
            f"collected_at ({finding.collected_at.isoformat()}) is more than {MAX_PAST_STALENESS_SECONDS} seconds "
            f"old relative to this server's own clock -- too stale to establish a current failure, rejected"
        )

    fingerprint = aws_finding_fingerprint(finding)
    await repo.acquire_fingerprint_lock(source="aws", source_fingerprint=fingerprint)

    fields = map_aws_finding_to_incident_fields(finding, ingested_at=now)
    extra_metadata = aws_finding_event_metadata(finding)

    active = await repo.get_active_incident(source="aws", source_fingerprint=fingerprint)
    if active is not None:
        if finding.collected_at < active["occurrence_starts_at"]:
            await repo.commit()
            return str(active["id"]), "ignored", active["severity"]
        incident_id, _created = await repo.upsert_firing_incident(**fields, actor_type="aws", extra_metadata=extra_metadata)
        await repo.commit()
        return str(incident_id), "updated", fields["severity"]

    most_recent = await repo.get_most_recent_incident(source="aws", source_fingerprint=fingerprint)
    if most_recent is not None and finding.collected_at <= most_recent["occurrence_starts_at"]:
        await repo.commit()
        return str(most_recent["id"]), "ignored", most_recent["severity"]

    incident_id, _created = await repo.upsert_firing_incident(**fields, actor_type="aws", extra_metadata=extra_metadata)
    await repo.commit()
    return str(incident_id), "created", fields["severity"]
