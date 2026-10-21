"""Gate F: converts the raw, already-collected detection evidence
(anomaly results, dependency graph, propagation paths, invariant
reports, correlation groups) into `FailureFinding` records -- reusing
Phase 11A's `catalog.schemas.finding` models directly rather than
inventing a second, incompatible incident schema.

Pure and deterministic: given the same `RawPipelineResult`, this
module always produces the same findings (byte-identical after JSON
serialization) -- no wall-clock reads, no randomness. `finding_id` is
derived from a stable hash of its own content, never a counter whose
value depends on dict/set iteration order.
"""

import hashlib

from catalog.schemas.finding import (
    DiagnosticCheck,
    EvidenceProvenance as FindingEvidenceProvenance,
    FailureFinding,
    Hypothesis,
    MeasuredSignal,
    Observation,
)
from detectors.schemas.anomaly import AnomalyDetectionResult, DetectionResult
from detectors.schemas.invariant import InvariantCheckReport, InvariantCheckResult


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _observation_from_anomaly(result: AnomalyDetectionResult) -> Observation:
    evidence = FindingEvidenceProvenance(
        source_system=result.evidence.source_system,
        source_identifier=result.evidence.query,
        collected_at=result.evidence.collected_at,
        collection_method="bounded Prometheus query_range (read-only)",
    )
    signals = [
        MeasuredSignal(
            signal_name=f"{result.metric_key}:observation_median",
            observed_value=str(result.observation.median) if result.observation.median is not None else "n/a",
            expected_or_baseline_value=str(result.baseline.median) if result.baseline.median is not None else "n/a",
            evidence=evidence,
        )
    ]
    return Observation(
        observation_id=_stable_id("obs", result.detector_id, result.service, result.metric_key, result.observation.window_start),
        observed_service_or_resource=result.service,
        observation_window_start=result.observation.window_start,
        observation_window_end=result.observation.window_end,
        measured_signals=signals,
        expected_or_baseline_behavior=f"baseline median={result.baseline.median}, MAD={result.baseline.mad}",
        actual_behavior=result.decision_rationale,
        anomaly_or_invariant_evidence=result.result.value,
        evidence=evidence,
    )


def build_findings_from_anomalies(
    anomaly_results: list[AnomalyDetectionResult],
    propagation_paths: list,  # list[PropagationPath]
    correlation_group_by_item_id: dict[str, str],
) -> list[FailureFinding]:
    """One `FailureFinding` per service that has at least one
    ANOMALY_DETECTED result -- never a required scenario match, never
    an invented root cause. A service with only NO_ANOMALY/
    INSUFFICIENT_DATA/TELEMETRY_UNAVAILABLE results produces no finding
    here (that information is still preserved -- see the pipeline's
    own full `anomaly_results` output, never discarded)."""
    by_service: dict[str, list[AnomalyDetectionResult]] = {}
    for r in anomaly_results:
        if r.result == DetectionResult.ANOMALY_DETECTED:
            by_service.setdefault(r.service, []).append(r)

    findings: list[FailureFinding] = []
    for service in sorted(by_service):
        results = by_service[service]
        observations = [_observation_from_anomaly(r) for r in results]
        window_start = min(r.observation.window_start for r in results)
        window_end = max(r.observation.window_end for r in results)

        hypotheses: list[Hypothesis] = []
        diagnostic_checks: list[DiagnosticCheck] = []
        suggested_checks: list[str] = []
        for path in propagation_paths:
            if path.services_in_path[0] != service:
                continue
            item_id = f"anomaly:{results[0].detector_id}:{service}"
            group_id = correlation_group_by_item_id.get(item_id)
            hyp_id = _stable_id("hyp", path.path_id, service)
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=hyp_id,
                    statement=path.rationale,
                    supporting_observation_ids=[o.observation_id for o in observations],
                    confidence=path.confidence,
                    likely_affected_dependencies=[path.candidate_root_cause_service] if path.candidate_root_cause_service else [],
                    correlated_alert_identifiers=[group_id] if group_id else [],
                    uncertainty_notes="candidate propagation path, not an established root cause",
                )
            )
            check_description = (
                f"re-run the anomaly detectors directly against {path.candidate_root_cause_service} to "
                "independently confirm whether it is itself degraded"
            )
            diagnostic_checks.append(
                DiagnosticCheck(
                    check_id=_stable_id("check", hyp_id),
                    hypothesis_id=hyp_id,
                    description=check_description,
                    expected_evidence_if_hypothesis_true=(
                        f"{path.candidate_root_cause_service} would itself show an ANOMALY_DETECTED result"
                    ),
                )
            )
            suggested_checks.append(check_description)

        evidence_provenance = [
            FindingEvidenceProvenance(
                source_system=r.evidence.source_system,
                source_identifier=r.evidence.query,
                collected_at=r.evidence.collected_at,
                collection_method="bounded Prometheus query_range (read-only)",
            )
            for r in results
        ]

        findings.append(
            FailureFinding(
                finding_id=_stable_id("finding", service, window_start, window_end, *(r.detector_id for r in results)),
                origin_detector_family_id=_family_id_for_detector(results[0].detector_id),
                observed_service_or_resource=service,
                observation_window_start=window_start,
                observation_window_end=window_end,
                observations=observations,
                hypotheses=hypotheses,
                diagnostic_checks=diagnostic_checks,
                candidate_known_scenario_matches=[],  # never required -- see module docstring
                unresolved_classification=True,
                classification_uncertainty_notes=(
                    "produced by Phase 11B's general-purpose detection pipeline; no catalog scenario match was attempted or required"
                ),
                evidence_provenance=evidence_provenance,
                suggested_read_only_diagnostic_checks=suggested_checks,
            )
        )
    return findings


_DETECTOR_TO_FAMILY = {
    "error_rate_deviation": "api_error_rates",
    "latency_deviation": "latency_anomalies",
    "telemetry_pipeline_health": None,  # no exact-fit registered family -- see architecture doc
}


def _family_id_for_detector(detector_id: str) -> str | None:
    return _DETECTOR_TO_FAMILY.get(detector_id)


def build_findings_from_invariant_violations(reports: list[InvariantCheckReport]) -> list[FailureFinding]:
    findings: list[FailureFinding] = []
    for report in reports:
        if report.result != InvariantCheckResult.VIOLATED:
            continue
        observations = [
            Observation(
                observation_id=_stable_id("obs", report.invariant_id, v.subject_id, str(i)),
                observed_service_or_resource="control-plane",
                observation_window_start=report.checked_observation_window_start,
                observation_window_end=report.checked_observation_window_end,
                actual_behavior=v.explanation,
                anomaly_or_invariant_evidence="violated",
                evidence=FindingEvidenceProvenance(
                    source_system="control-plane",
                    source_identifier=v.evidence_reference,
                    collected_at=report.checked_observation_window_end,
                    collection_method="bounded GET /api/v1/incidents/{id}/events (read-only)",
                ),
            )
            for i, v in enumerate(report.violations)
        ]
        findings.append(
            FailureFinding(
                finding_id=_stable_id("finding", "invariant", report.invariant_id, report.checked_observation_window_start, report.checked_observation_window_end),
                origin_detector_family_id="business_invariant_violations",
                observed_service_or_resource="control-plane",
                observation_window_start=report.checked_observation_window_start,
                observation_window_end=report.checked_observation_window_end,
                observations=observations,
                candidate_known_scenario_matches=[],
                unresolved_classification=True,
                classification_uncertainty_notes=f"invariant {report.invariant_id!r} violation -- see observations for each specific violation",
                evidence_provenance=[o.evidence for o in observations],
                suggested_read_only_diagnostic_checks=[
                    "re-fetch the same incident's full event history independently to confirm the violation persists"
                ],
            )
        )
    return findings
