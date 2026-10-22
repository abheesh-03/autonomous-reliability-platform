"""AWS finding -> reliability.incidents field mapping (Phase 13).
Mirrors `ingestion/kubernetes_mapping.py`'s own structure exactly, for
the AWS source instead of Kubernetes.
"""

import hashlib
from datetime import datetime
from typing import TypedDict

from control_plane.domain.aws_finding import AwsFindingIngestRequest

# A confirmed AWS failure is always 'critical' -- a real, direct
# API-confirmed fact; INSUFFICIENT_EVIDENCE is 'warning' -- mirrors
# kubernetes_mapping.py's own severity-by-result discipline exactly.
_SEVERITY_BY_RESULT = {"confirmed": "critical", "insufficient_evidence": "warning"}


def aws_finding_fingerprint(finding: AwsFindingIngestRequest) -> str:
    """Stable deduplication identity: (account_id, region,
    resource_kind, resource_id, detector_id) -- Gate 4's own explicit
    requirement that "the fingerprint must distinguish AWS account,
    Region, resource identity and failure class". Hashed (not the raw
    concatenation), same rationale as kubernetes_finding_fingerprint's
    own docstring -- an identity key, never evidence."""
    raw = f"{finding.account_id}:{finding.region}:{finding.resource_kind}:{finding.resource_id}:{finding.detector_id}"
    return "aws-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class IncidentFields(TypedDict):
    source: str
    source_fingerprint: str
    title: str
    description: str | None
    severity: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_starts_at: datetime


def map_aws_finding_to_incident_fields(finding: AwsFindingIngestRequest, *, ingested_at: datetime) -> IncidentFields:
    # Embeds account/region/resource identity directly into the title
    # -- this service's incident model has no dedicated account/
    # region/service UI field, so (mirroring exactly how the
    # Kubernetes path embeds cluster/namespace/resource into its own
    # title) the EXISTING, already-rendered title field is what gives
    # the web console a meaningful, accurate label with zero UI change
    # required (Gate 5).
    resource_ref = f"aws/{finding.account_id}/{finding.region}/{finding.resource_kind}/{finding.resource_id}"
    title = f"{finding.detector_id}: {resource_ref}"

    return IncidentFields(
        source="aws",
        source_fingerprint=aws_finding_fingerprint(finding),
        title=title,
        description=finding.decision_rationale,
        severity=_SEVERITY_BY_RESULT[finding.result],
        first_seen_at=finding.collected_at,
        last_seen_at=ingested_at,
        occurrence_starts_at=finding.collected_at,
    )


def aws_finding_event_metadata(finding: AwsFindingIngestRequest) -> dict[str, object]:
    """Allowlisted, structured, bounded metadata recorded on the
    'created'/'observed' incident_events row -- mirrors
    kubernetes_finding_event_metadata's own discipline exactly: never a
    raw bearer token or unfiltered request body.

    Correction round, Issue 4: `decision_rationale` and `evidence` are
    now included -- previously omitted entirely, which meant the
    original symptom (why this detector fired) and its supporting
    measurements (CloudWatch state/EC2 status/ECS task counts) were
    accepted at ingestion but then PERMANENTLY LOST -- never written
    to the one place (`incident_events.metadata`) the AWS-evidence GET
    endpoint and, in turn, the investigator's own evidence collector
    read from. Both fields are already bounded/validated by
    AwsFindingIngestRequest itself before ever reaching this function;
    this is allowlisted inclusion of already-trusted-shape data, not a
    new validation boundary."""
    return {
        "account_id": finding.account_id,
        "region": finding.region,
        "resource_kind": finding.resource_kind,
        "resource_id": finding.resource_id,
        "resource_arn": finding.resource_arn,
        "detector_id": finding.detector_id,
        "result": finding.result,
        "collection_completeness": finding.collection_completeness,
        "collected_at": finding.collected_at.isoformat(),
        "decision_rationale": finding.decision_rationale,
        "evidence": dict(finding.evidence),
        "supporting_change_events": list(finding.supporting_change_events),
    }
