"""Phase 13, Gate 2/3: converts `AwsDetectionFinding` records into
`FailureFinding` -- reusing Phase 11A/11B's `catalog.schemas.finding`
models directly, exactly mirroring `detectors.kubernetes.findings`'s
own pattern (never a second, incompatible incident schema). Grouped by
resource (account, region, resource_kind, resource_id) -- a resource
with findings from multiple detectors gets ONE `FailureFinding` with
multiple `Observation`s.
"""

import hashlib

from catalog.schemas.finding import (
    EvidenceProvenance as FindingEvidenceProvenance,
    FailureFinding,
    MeasuredSignal,
    Observation,
)
from detectors.schemas.aws import AwsDetectionFinding, AwsDetectionResult


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _observation_from_aws_finding(finding: AwsDetectionFinding, collected_at: str) -> Observation:
    source_identifier = f"aws/{finding.account_id}/{finding.region}/{finding.resource_kind}/{finding.resource_id}"
    evidence = FindingEvidenceProvenance(
        source_system="aws",
        source_identifier=source_identifier,
        collected_at=collected_at,
        collection_method="bounded AWS read-only API call (CloudWatch/EC2/ECS)",
    )
    signals = [
        MeasuredSignal(signal_name=key, observed_value=value, evidence=evidence)
        for key, value in sorted(finding.evidence.items())
    ]
    return Observation(
        observation_id=_stable_id(
            "aws-obs", finding.detector_id, finding.account_id, finding.region, finding.resource_kind,
            finding.resource_id, finding.result.value,
        ),
        observed_service_or_resource=source_identifier,
        observation_window_start=collected_at,
        observation_window_end=collected_at,
        measured_signals=signals,
        actual_behavior=finding.decision_rationale,
        anomaly_or_invariant_evidence=finding.result.value,
        evidence=evidence,
    )


def build_findings_from_aws(aws_findings: list[AwsDetectionFinding], collected_at: str) -> list[FailureFinding]:
    """Only CONFIRMED and INSUFFICIENT_EVIDENCE `AwsDetectionFinding`
    records are ever passed in -- `candidate_known_scenario_matches` is
    always `[]` and `unresolved_classification` is always `True`,
    exactly like Phase 12A's own Kubernetes findings: an AWS
    observation never requires matching one of the 800 catalogued
    reference scenarios."""
    by_resource: dict[tuple[str, str, str, str], list[AwsDetectionFinding]] = {}
    for f in aws_findings:
        by_resource.setdefault((f.account_id, f.region, f.resource_kind, f.resource_id), []).append(f)

    findings: list[FailureFinding] = []
    for (account_id, region, kind, resource_id), items in sorted(by_resource.items()):
        observations = [_observation_from_aws_finding(item, collected_at) for item in items]
        detector_ids = sorted({item.detector_id for item in items})

        confirmed_count = sum(1 for item in items if item.result == AwsDetectionResult.CONFIRMED)
        insufficient_count = sum(1 for item in items if item.result == AwsDetectionResult.INSUFFICIENT_EVIDENCE)
        notes = (
            f"produced by Phase 13's AWS observer; no catalog scenario match was attempted or required "
            f"({confirmed_count} confirmed, {insufficient_count} insufficient-evidence detector result(s) for this resource)"
        )

        source_identifier = f"aws/{account_id}/{region}/{kind}/{resource_id}"
        findings.append(
            FailureFinding(
                finding_id=_stable_id("aws-finding", account_id, region, kind, resource_id, collected_at, *detector_ids),
                # No exact-fit registered detector family for any AWS
                # detector in this round -- mirrors
                # detectors.pipeline.findings's own "telemetry_pipeline_
                # health" precedent of leaving this None rather than
                # forcing a mismatched family.
                origin_detector_family_id=None,
                observed_service_or_resource=source_identifier,
                observation_window_start=collected_at,
                observation_window_end=collected_at,
                observations=observations,
                candidate_known_scenario_matches=[],
                unresolved_classification=True,
                classification_uncertainty_notes=notes,
                evidence_provenance=[o.evidence for o in observations],
                suggested_read_only_diagnostic_checks=[
                    f"re-fetch {source_identifier} directly to confirm the {item.detector_id} finding still holds"
                    for item in items
                ],
            )
        )
    return findings
