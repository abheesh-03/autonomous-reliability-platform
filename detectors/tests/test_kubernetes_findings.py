"""Gate E (Phase 12A): K8sDetectionFinding -> FailureFinding
conversion tests -- reuses catalog.schemas.finding directly, never a
scenario match, groups by resource."""

from detectors.kubernetes.findings import build_findings_from_kubernetes
from detectors.schemas.kubernetes import K8sDetectionFinding, K8sDetectionResult

COLLECTED_AT = "2026-10-21T00:00:00Z"


def _finding(detector_id, resource_name, result=K8sDetectionResult.CONFIRMED, container_name=None):
    return K8sDetectionFinding(
        detector_id=detector_id,
        resource_kind="Pod",
        namespace="reliability-sandbox",
        resource_name=resource_name,
        container_name=container_name,
        result=result,
        evidence={"waiting_reason": "ImagePullBackOff"},
        decision_rationale="test rationale",
    )


def test_empty_input_produces_no_findings():
    assert build_findings_from_kubernetes([], COLLECTED_AT) == []


def test_single_finding_produces_one_failure_finding_with_no_scenario_match():
    findings = build_findings_from_kubernetes([_finding("image_pull_backoff", "pod-a")], COLLECTED_AT)
    assert len(findings) == 1
    f = findings[0]
    assert f.candidate_known_scenario_matches == []
    assert f.unresolved_classification is True
    assert f.observed_service_or_resource == "Pod/reliability-sandbox/pod-a"
    assert f.origin_detector_family_id == "deployment_regressions"


def test_multiple_detector_findings_for_the_same_resource_merge_into_one_finding():
    findings = build_findings_from_kubernetes(
        [_finding("image_pull_backoff", "pod-a"), _finding("pod_readiness_degradation", "pod-a")], COLLECTED_AT
    )
    assert len(findings) == 1
    assert len(findings[0].observations) == 2
    assert findings[0].origin_detector_family_id is None  # mixed families -- never guessed


def test_findings_for_different_resources_stay_separate():
    findings = build_findings_from_kubernetes(
        [_finding("image_pull_backoff", "pod-a"), _finding("oom_killed", "pod-b")], COLLECTED_AT
    )
    assert len(findings) == 2
    assert {f.observed_service_or_resource for f in findings} == {
        "Pod/reliability-sandbox/pod-a",
        "Pod/reliability-sandbox/pod-b",
    }


def test_no_remediation_proposals_are_ever_produced():
    findings = build_findings_from_kubernetes([_finding("oom_killed", "pod-a")], COLLECTED_AT)
    assert all(f.remediation_proposals == [] for f in findings)
    assert all(f.executions == [] for f in findings)


def test_deterministic_across_repeated_calls():
    k8s_findings = [_finding("image_pull_backoff", "pod-a")]
    result_1 = build_findings_from_kubernetes(k8s_findings, COLLECTED_AT)
    result_2 = build_findings_from_kubernetes(k8s_findings, COLLECTED_AT)
    assert [f.model_dump() for f in result_1] == [f.model_dump() for f in result_2]
