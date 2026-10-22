"""Phase 12B-D correction round (Issue 6B): the opt-in, authenticated
Kubernetes finding -> control-plane publish path. Real httpx.MockTransport
-backed HTTP, never a mocked function returning a preset final answer."""

import json
from datetime import UTC, datetime

import httpx

from detectors.kubernetes.publisher import PublishResult, publish_kubernetes_findings
from detectors.schemas.kubernetes import CollectionOutcome, CollectionResult, K8sDetectionFinding, K8sDetectionResult

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides) -> K8sDetectionFinding:
    fields = dict(
        detector_id="crash_loop_backoff",
        resource_kind="Pod",
        namespace="reliability-sandbox",
        resource_name="crashloop-demo-abc",
        resource_uid="uid-1",
        result=K8sDetectionResult.CONFIRMED,
        decision_rationale="waiting.reason == CrashLoopBackOff",
        evidence={"restart_count": "6"},
    )
    fields.update(overrides)
    return K8sDetectionFinding(**fields)


def _collection_results(pod_outcome=CollectionOutcome.SUCCESS, deployment_outcome=CollectionOutcome.SUCCESS):
    return [
        CollectionResult(outcome=pod_outcome, resource_kind="Pod", namespace="reliability-sandbox", detail="x"),
        CollectionResult(outcome=deployment_outcome, resource_kind="Deployment", namespace="reliability-sandbox", detail="x"),
    ]


async def test_publish_sends_the_expected_request_body_and_handles_outcomes():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["cluster"] == "kind-reliability-lab"
        assert body["namespace"] == "reliability-sandbox"
        assert body["resource_uid"] == "uid-1"
        assert body["detector_id"] == "crash_loop_backoff"
        assert body["result"] == "confirmed"
        assert body["collection_completeness"] == "complete"
        assert body["collected_at"] == NOW.isoformat()
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created", "severity": "critical"})

    results = await publish_kubernetes_findings(
        [_finding()], _collection_results(), cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert len(captured) == 1
    assert results == [
        PublishResult(
            detector_id="crash_loop_backoff", resource_kind="Pod", namespace="reliability-sandbox",
            resource_name="crashloop-demo-abc", outcome="created", incident_id="inc-1", detail="",
        )
    ]


async def test_publish_marks_completeness_partial_when_collection_was_partial():
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created", "severity": "critical"})

    await publish_kubernetes_findings(
        [_finding()], _collection_results(pod_outcome=CollectionOutcome.PARTIAL),
        cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert captured_bodies[0]["collection_completeness"] == "partial"


async def test_publish_no_matching_collection_result_defaults_to_partial():
    """Never a false 'complete' claim when, for whatever reason, this
    run's own collection results don't include the relevant resource
    kind at all."""
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created", "severity": "critical"})

    await publish_kubernetes_findings(
        [_finding()], [], cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert captured_bodies[0]["collection_completeness"] == "partial"


async def test_publish_network_failure_never_invents_an_incident_id():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    results = await publish_kubernetes_findings(
        [_finding()], _collection_results(), cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert len(results) == 1
    assert results[0].outcome == "failed"
    assert results[0].incident_id is None


async def test_publish_non_201_response_never_invents_an_incident_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "rejected"})

    results = await publish_kubernetes_findings(
        [_finding()], _collection_results(), cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert results[0].outcome == "failed"
    assert results[0].incident_id is None
    assert "422" in results[0].detail


async def test_publish_malformed_201_response_never_invents_an_incident_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"unexpected": "shape"})

    results = await publish_kubernetes_findings(
        [_finding()], _collection_results(), cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert results[0].outcome == "failed"
    assert results[0].incident_id is None


async def test_one_failed_finding_does_not_abort_publishing_the_rest():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        if body["resource_name"] == "bad-pod":
            return httpx.Response(500)
        return httpx.Response(201, json={"incident_id": "inc-2", "outcome": "created", "severity": "critical"})

    results = await publish_kubernetes_findings(
        [_finding(resource_name="bad-pod"), _finding(resource_name="good-pod")],
        _collection_results(), cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert call_count["n"] == 2
    assert results[0].outcome == "failed"
    assert results[1].outcome == "created"


async def test_insufficient_evidence_findings_are_also_published():
    """A weaker signal is still real, structured evidence worth a
    durable record -- never silently dropped from publishing."""
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"incident_id": "inc-3", "outcome": "created", "severity": "warning"})

    results = await publish_kubernetes_findings(
        [_finding(result=K8sDetectionResult.INSUFFICIENT_EVIDENCE)], _collection_results(),
        cluster="kind-reliability-lab", collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert captured_bodies[0]["result"] == "insufficient_evidence"
    assert results[0].outcome == "created"
