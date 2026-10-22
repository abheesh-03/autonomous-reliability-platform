"""Kubernetes finding -> reliability.incidents field mapping (Phase
12B-D). Mirrors ingestion/mapping.py's own structure exactly, for the
Kubernetes source instead of Alertmanager.
"""

import hashlib
from datetime import datetime
from typing import TypedDict

from control_plane.domain.kubernetes_finding import KubernetesFindingIngestRequest

# A confirmed Kubernetes failure is always 'critical' -- it is a real,
# direct API-confirmed fact (detectors.schemas.kubernetes.
# K8sDetectionResult.CONFIRMED's own documented bar), never a guess.
# INSUFFICIENT_EVIDENCE is 'warning' -- a real, suspicious signal, but
# explicitly not strong enough to confirm on its own (mirrors the
# detector's own epistemic honesty into incident severity, rather than
# treating every ingested finding as equally severe).
_SEVERITY_BY_RESULT = {"confirmed": "critical", "insufficient_evidence": "warning"}


def kubernetes_finding_fingerprint(finding: KubernetesFindingIngestRequest) -> str:
    """Stable deduplication identity: (cluster, namespace, resource_kind,
    resource_name, detector_id) -- deliberately NEVER resource_uid (a
    recreated resource exhibiting the SAME failure class is still the
    SAME ongoing operational concern for this fingerprint's purposes;
    UID is tracked separately, in incident_events.metadata, for honest
    identity-change auditing -- see
    ingestion/kubernetes_service.py's own docstring). Hashed (not the
    raw concatenation) purely to keep source_fingerprint short and free
    of any character that could collide with the ':' separator; this is
    an identity key, never evidence, so collision-resistance (SHA-256)
    is what matters, not reversibility."""
    raw = f"{finding.cluster}:{finding.namespace}:{finding.resource_kind}:{finding.resource_name}:{finding.detector_id}"
    return "k8s-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class IncidentFields(TypedDict):
    source: str
    source_fingerprint: str
    title: str
    description: str | None
    severity: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_starts_at: datetime


def map_kubernetes_finding_to_incident_fields(
    finding: KubernetesFindingIngestRequest, *, ingested_at: datetime
) -> IncidentFields:
    resource_ref = f"{finding.resource_kind}/{finding.namespace}/{finding.resource_name}"
    title = f"{finding.detector_id}: {resource_ref}"

    return IncidentFields(
        source="kubernetes",
        source_fingerprint=kubernetes_finding_fingerprint(finding),
        title=title,
        description=finding.decision_rationale,
        severity=_SEVERITY_BY_RESULT[finding.result],
        first_seen_at=finding.collected_at,
        last_seen_at=ingested_at,
        # The occurrence-identity watermark (same column, same role as
        # Alertmanager's startsAt -- database/migrations/
        # V2__add_occurrence_watermark.sql): this finding's own
        # collection instant, never the ingestion-request's own
        # wall-clock arrival time.
        occurrence_starts_at=finding.collected_at,
    )


def kubernetes_finding_event_metadata(finding: KubernetesFindingIngestRequest) -> dict[str, object]:
    """Allowlisted, structured, bounded metadata recorded on the
    'created'/'observed' incident_events row -- NEVER a raw bearer
    token or unfiltered request body (same discipline
    repositories/incident_repository.py already applies to the
    Alertmanager path). Includes resource_uid specifically so a
    reviewer reading the incident's own audit trail can see, in plain
    sight, every UID this fingerprint has ever been observed under --
    the honest, auditable record of "recovered and newly recreated
    resources" (Gate 2) that this round deliberately does NOT use to
    auto-resolve or auto-split an incident."""
    return {
        "cluster": finding.cluster,
        "namespace": finding.namespace,
        "resource_kind": finding.resource_kind,
        "resource_name": finding.resource_name,
        "resource_uid": finding.resource_uid,
        "detector_id": finding.detector_id,
        "result": finding.result,
        "collection_completeness": finding.collection_completeness,
        "collected_at": finding.collected_at.isoformat(),
    }
