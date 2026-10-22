"""Phase 13, Gate 3/4: `detectors.aws.publisher` -- a real HTTP contract
test via httpx.MockTransport, mirroring `test_kubernetes_publisher.py`.
Never a live network call."""

from datetime import UTC, datetime

import httpx

from detectors.aws.publisher import publish_aws_findings
from detectors.schemas.aws import AwsCollectionOutcome, AwsCollectionResult, AwsDetectionFinding, AwsDetectionResult

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
NOW = datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC)


def _finding(**overrides) -> AwsDetectionFinding:
    fields = {
        "detector_id": "cloudwatch_alarm_in_alarm_state",
        "resource_kind": "CloudWatchAlarm",
        "account_id": ACCOUNT_ID,
        "region": REGION,
        "resource_id": "checkout-high-error-rate",
        "result": AwsDetectionResult.CONFIRMED,
        "evidence": {"state_value": "ALARM"},
        "decision_rationale": "alarm is in ALARM state",
    }
    fields.update(overrides)
    return AwsDetectionFinding(**fields)


def _collection_results() -> list[AwsCollectionResult]:
    return [
        AwsCollectionResult(
            outcome=AwsCollectionOutcome.SUCCESS, resource_kind="CloudWatchAlarm",
            account_id=ACCOUNT_ID, region=REGION, detail="ok", items_count=1,
        )
    ]


async def test_publish_success_records_the_real_incident_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created"})

    results = await publish_aws_findings(
        [_finding()], _collection_results(), collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    assert len(results) == 1
    assert results[0].outcome == "created"
    assert results[0].incident_id == "inc-1"
    assert captured["auth"] == "Bearer test-token"


async def test_publish_never_fabricates_an_incident_id_on_non_201():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "stale evidence"})

    results = await publish_aws_findings(
        [_finding()], _collection_results(), collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    assert results[0].outcome == "failed"
    assert results[0].incident_id is None
    assert "stale evidence" in results[0].detail


async def test_publish_network_failure_is_reported_never_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    results = await publish_aws_findings(
        [_finding()], _collection_results(), collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    assert results[0].outcome == "failed"
    assert results[0].incident_id is None


async def test_publish_sends_the_expected_bounded_body_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.read())
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created"})

    await publish_aws_findings(
        [_finding()], _collection_results(), collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    body = captured["body"]
    assert body["account_id"] == ACCOUNT_ID
    assert body["region"] == REGION
    assert body["resource_kind"] == "CloudWatchAlarm"
    assert body["resource_id"] == "checkout-high-error-rate"
    assert body["collection_completeness"] == "complete"
    assert body["collected_at"] == NOW.isoformat()


async def test_partial_collection_is_reported_as_partial_completeness():
    partial_results = [
        AwsCollectionResult(
            outcome=AwsCollectionOutcome.PARTIAL, resource_kind="CloudWatchAlarm",
            account_id=ACCOUNT_ID, region=REGION, detail="bounded page limit reached", items_count=1,
        )
    ]
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.read())
        return httpx.Response(201, json={"incident_id": "inc-1", "outcome": "created"})

    await publish_aws_findings(
        [_finding()], partial_results, collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    assert captured["body"]["collection_completeness"] == "partial"


async def test_one_bad_finding_never_aborts_publishing_the_rest():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(201, json={"incident_id": "inc-2", "outcome": "created"})

    findings = [_finding(resource_id="alarm-a"), _finding(resource_id="alarm-b")]
    results = await publish_aws_findings(
        findings, _collection_results(), collected_at=NOW,
        control_plane_url="http://control-plane.invalid", ingestion_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    assert len(results) == 2
    assert results[0].outcome == "failed"
    assert results[1].outcome == "created"
