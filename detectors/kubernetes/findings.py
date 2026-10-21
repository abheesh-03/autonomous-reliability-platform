"""Gate E (Phase 12A): converts `K8sDetectionFinding` records into
`FailureFinding` -- reusing Phase 11A/11B's `catalog.schemas.finding`
models directly, exactly mirroring `detectors.pipeline.findings`'s own
pattern (never a second, incompatible incident schema). Grouped by
resource (kind, namespace, name) -- a pod with findings from multiple
detectors gets ONE `FailureFinding` with multiple `Observation`s,
never one finding object per detector."""

import hashlib

from catalog.schemas.finding import (
    EvidenceProvenance as FindingEvidenceProvenance,
    FailureFinding,
    MeasuredSignal,
    Observation,
)
from detectors.schemas.kubernetes import K8sDetectionFinding, K8sDetectionResult


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _observation_from_k8s_finding(finding: K8sDetectionFinding, collected_at: str) -> Observation:
    evidence = FindingEvidenceProvenance(
        source_system="kubernetes",
        source_identifier=f"{finding.resource_kind}/{finding.namespace}/{finding.resource_name}"
        + (f"/{finding.container_name}" if finding.container_name else ""),
        collected_at=collected_at,
        collection_method="bounded Kubernetes REST API GET (read-only)",
    )
    signals = [
        MeasuredSignal(signal_name=key, observed_value=value, evidence=evidence)
        for key, value in sorted(finding.evidence.items())
    ]
    return Observation(
        observation_id=_stable_id(
            "k8s-obs", finding.detector_id, finding.resource_kind, finding.namespace, finding.resource_name,
            finding.container_name or "", finding.result.value,
        ),
        observed_service_or_resource=f"{finding.resource_kind}/{finding.namespace}/{finding.resource_name}",
        observation_window_start=collected_at,
        observation_window_end=collected_at,
        measured_signals=signals,
        actual_behavior=finding.decision_rationale,
        anomaly_or_invariant_evidence=finding.result.value,
        evidence=evidence,
    )


_DETECTOR_TO_FAMILY = {
    "image_pull_backoff": "deployment_regressions",
    "crash_loop_backoff": "process_service_health",
    "oom_killed": "resource_saturation",
    "deployment_rollout_failure": "deployment_regressions",
    "pod_readiness_degradation": "process_service_health",
}


def build_findings_from_kubernetes(k8s_findings: list[K8sDetectionFinding], collected_at: str) -> list[FailureFinding]:
    """Only CONFIRMED and INSUFFICIENT_EVIDENCE `K8sDetectionFinding`
    records are ever passed in (a detector never emits a finding
    object for a healthy resource at all) -- `candidate_known_
    scenario_matches` is always `[]` and `unresolved_classification`
    is always `True`, exactly like Phase 11B's own Prometheus/Tempo
    findings: a Kubernetes observation never requires matching one of
    the 800 catalogued reference scenarios."""
    by_resource: dict[tuple[str, str, str], list[K8sDetectionFinding]] = {}
    for f in k8s_findings:
        by_resource.setdefault((f.resource_kind, f.namespace, f.resource_name), []).append(f)

    findings: list[FailureFinding] = []
    for (kind, namespace, name), items in sorted(by_resource.items()):
        observations = [_observation_from_k8s_finding(item, collected_at) for item in items]
        detector_ids = sorted({item.detector_id for item in items})
        family_ids = {_DETECTOR_TO_FAMILY.get(d) for d in detector_ids}
        origin_family = next(iter(family_ids)) if len(family_ids) == 1 else None

        confirmed_count = sum(1 for item in items if item.result == K8sDetectionResult.CONFIRMED)
        insufficient_count = sum(1 for item in items if item.result == K8sDetectionResult.INSUFFICIENT_EVIDENCE)
        notes = (
            f"produced by Phase 12A's Kubernetes observer; no catalog scenario match was attempted or required "
            f"({confirmed_count} confirmed, {insufficient_count} insufficient-evidence detector result(s) for this resource)"
        )

        findings.append(
            FailureFinding(
                finding_id=_stable_id("k8s-finding", kind, namespace, name, collected_at, *detector_ids),
                origin_detector_family_id=origin_family,
                observed_service_or_resource=f"{kind}/{namespace}/{name}",
                observation_window_start=collected_at,
                observation_window_end=collected_at,
                observations=observations,
                candidate_known_scenario_matches=[],
                unresolved_classification=True,
                classification_uncertainty_notes=notes,
                evidence_provenance=[o.evidence for o in observations],
                suggested_read_only_diagnostic_checks=[
                    f"re-fetch {kind}/{namespace}/{name} directly to confirm the {item.detector_id} finding still holds"
                    for item in items
                ],
            )
        )
    return findings
