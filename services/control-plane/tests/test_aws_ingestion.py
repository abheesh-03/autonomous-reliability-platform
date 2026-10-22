"""Phase 13, Gate 4: the AWS finding-ingestion domain model, mapping,
occurrence-identity service logic, and the authenticated endpoint's
auth boundary. Mirrors `test_kubernetes_ingestion.py`'s own structure
exactly, for the AWS source instead of Kubernetes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.aws_finding import AwsFindingIngestRequest
from control_plane.ingestion.aws_mapping import aws_finding_fingerprint, map_aws_finding_to_incident_fields
from control_plane.ingestion.aws_service import AwsIngestionRejected, ingest_aws_finding
from control_plane.main import app
from tests.conftest import (
    AWS_INGESTION_TOKEN,
    KUBERNETES_INGESTION_TOKEN,
    LIFECYCLE_TOKEN,
    REMEDIATION_APPROVER_TOKEN,
    REMEDIATION_EXECUTOR_TOKEN,
    REMEDIATION_PROPOSAL_TOKEN,
    WEBHOOK_TOKEN,
    FakeIncidentRepository,
)

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
AUTH = {"Authorization": f"Bearer {AWS_INGESTION_TOKEN}"}
ACCOUNT_ID = "123456789012"
REGION = "us-east-1"


def _finding(**overrides) -> AwsFindingIngestRequest:
    fields = {
        "account_id": ACCOUNT_ID,
        "region": REGION,
        "resource_kind": "CloudWatchAlarm",
        "resource_id": "checkout-high-error-rate",
        "resource_arn": f"arn:aws:cloudwatch:{REGION}:{ACCOUNT_ID}:alarm:checkout-high-error-rate",
        "detector_id": "cloudwatch_alarm_in_alarm_state",
        "result": "confirmed",
        "collection_completeness": "complete",
        "collected_at": NOW,
        "decision_rationale": "CloudWatch alarm currently reports StateValue=ALARM",
        "evidence": {"state_value": "ALARM"},
        "supporting_change_events": ["UpdateAlarm by alice at 2026-10-21T11:59:00Z"],
    }
    fields.update(overrides)
    return AwsFindingIngestRequest(**fields)


def _finding_body(**overrides) -> dict:
    body = {
        "account_id": ACCOUNT_ID,
        "region": REGION,
        "resource_kind": "CloudWatchAlarm",
        "resource_id": "checkout-high-error-rate",
        "detector_id": "cloudwatch_alarm_in_alarm_state",
        "result": "confirmed",
        "collection_completeness": "complete",
        "collected_at": datetime.now(UTC).isoformat(),
        "decision_rationale": "CloudWatch alarm currently reports StateValue=ALARM",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------
# Domain validation
# ---------------------------------------------------------------------


def test_valid_finding_parses_cleanly():
    f = _finding()
    assert f.account_id == ACCOUNT_ID


@pytest.mark.parametrize("bad_account_id", ["12345", "abcdefghijkl", "", "123456789012 "])
def test_invalid_account_id_is_rejected(bad_account_id):
    with pytest.raises(ValidationError):
        _finding(account_id=bad_account_id)


@pytest.mark.parametrize("bad_region", ["US-EAST-1", "useast1", ""])
def test_invalid_region_is_rejected(bad_region):
    with pytest.raises(ValidationError):
        _finding(region=bad_region)


def test_naive_collected_at_is_rejected():
    with pytest.raises(ValidationError):
        AwsFindingIngestRequest(
            account_id=ACCOUNT_ID, region=REGION, resource_kind="CloudWatchAlarm", resource_id="x",
            detector_id="cloudwatch_alarm_in_alarm_state", result="confirmed", collection_completeness="complete",
            collected_at=datetime(2026, 1, 1), decision_rationale="x",
        )


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        _finding(unexpected_field="x")


def test_oversized_evidence_value_is_rejected():
    with pytest.raises(ValidationError):
        _finding(evidence={"k": "x" * 3000})


# ---------------------------------------------------------------------
# Fingerprint / mapping
# ---------------------------------------------------------------------


def test_fingerprint_distinguishes_account_region_resource_and_detector():
    base = aws_finding_fingerprint(_finding())
    different_account = aws_finding_fingerprint(_finding(account_id="999999999999"))
    different_region = aws_finding_fingerprint(_finding(region="us-west-2"))
    different_resource = aws_finding_fingerprint(_finding(resource_id="other-alarm"))
    different_detector = aws_finding_fingerprint(_finding(detector_id="ec2_failed_status_check"))
    assert len({base, different_account, different_region, different_resource, different_detector}) == 5


def test_fingerprint_is_stable_across_different_arns_and_timestamps():
    a = _finding(resource_arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:a", collected_at=NOW)
    b = _finding(resource_arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:b", collected_at=NOW + timedelta(minutes=10))
    assert aws_finding_fingerprint(a) == aws_finding_fingerprint(b)


def test_mapping_severity_reflects_detector_result():
    confirmed = map_aws_finding_to_incident_fields(_finding(result="confirmed"), ingested_at=NOW)
    insufficient = map_aws_finding_to_incident_fields(_finding(result="insufficient_evidence"), ingested_at=NOW)
    assert confirmed["severity"] == "critical"
    assert insufficient["severity"] == "warning"


def test_mapping_title_embeds_account_region_and_resource():
    fields = map_aws_finding_to_incident_fields(_finding(), ingested_at=NOW)
    assert ACCOUNT_ID in fields["title"]
    assert REGION in fields["title"]
    assert "checkout-high-error-rate" in fields["title"]


def test_mapping_occurrence_watermark_is_the_findings_own_collected_at():
    fields = map_aws_finding_to_incident_fields(_finding(), ingested_at=NOW + timedelta(minutes=1))
    assert fields["occurrence_starts_at"] == NOW
    assert fields["source"] == "aws"


# ---------------------------------------------------------------------
# Service: occurrence-identity decision logic
# ---------------------------------------------------------------------


async def test_new_finding_creates_an_incident():
    repo = FakeIncidentRepository([])
    incident_id, outcome, severity = await ingest_aws_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    assert outcome == "created"
    assert severity == "critical"
    assert repo.commit_count == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["source"] == "aws"
    assert repo.events[-1]["actor_type"] == "aws"
    assert repo.events[-1]["event_type"] == "created"


async def test_repeat_ingestion_updates_not_duplicates():
    repo = FakeIncidentRepository([])
    await ingest_aws_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    _id2, outcome2, _ = await ingest_aws_finding(_finding(collected_at=NOW + timedelta(minutes=1)), repo, now=NOW + timedelta(minutes=2))
    assert outcome2 == "updated"
    assert len(repo.rows) == 1


async def test_unrelated_finding_creates_a_separate_incident():
    repo = FakeIncidentRepository([])
    await ingest_aws_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    await ingest_aws_finding(_finding(resource_id="other-alarm", collected_at=NOW), repo, now=NOW + timedelta(seconds=1))
    assert len(repo.rows) == 2


async def test_stale_replay_against_an_active_incident_is_ignored():
    repo = FakeIncidentRepository([])
    await ingest_aws_finding(_finding(collected_at=NOW), repo, now=NOW + timedelta(seconds=1))
    _id, outcome, _ = await ingest_aws_finding(
        _finding(collected_at=NOW - timedelta(minutes=5)), repo, now=NOW + timedelta(seconds=2)
    )
    assert outcome == "ignored"
    assert len(repo.rows) == 1
    assert repo.rows[0]["occurrence_starts_at"] == NOW


async def test_future_dated_evidence_is_rejected_never_accepted_as_current():
    repo = FakeIncidentRepository([])
    with pytest.raises(AwsIngestionRejected):
        await ingest_aws_finding(_finding(collected_at=NOW + timedelta(hours=1)), repo, now=NOW)
    assert repo.rows == []
    assert repo.commit_count == 0


async def test_old_detector_observation_cannot_create_a_new_active_incident():
    from control_plane.ingestion.aws_service import MAX_PAST_STALENESS_SECONDS

    repo = FakeIncidentRepository([])
    stale_collected_at = NOW - timedelta(seconds=MAX_PAST_STALENESS_SECONDS + 1)
    with pytest.raises(AwsIngestionRejected):
        await ingest_aws_finding(_finding(collected_at=stale_collected_at), repo, now=NOW)
    assert repo.rows == []
    assert repo.commit_count == 0


async def test_insufficient_evidence_result_still_ingests_as_a_weaker_severity():
    repo = FakeIncidentRepository([])
    _id, outcome, severity = await ingest_aws_finding(
        _finding(result="insufficient_evidence", collection_completeness="partial"), repo, now=NOW + timedelta(seconds=1)
    )
    assert outcome == "created"
    assert severity == "warning"
    assert repo.events[-1]["metadata"]["collection_completeness"] == "partial"


async def test_an_alarm_disappearing_never_resolves_the_incident():
    """Gate 4: 'Never resolve an incident merely because an alarm
    disappears or a source returns an empty response.' There is no
    ingestion-driven resolution path at all for AWS findings -- this
    asserts the incident created above stays 'open' through repeated
    CONFIRMED observations; only the separate, authenticated operator
    lifecycle endpoint can ever transition it."""
    repo = FakeIncidentRepository([])
    await ingest_aws_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    await ingest_aws_finding(_finding(collected_at=NOW + timedelta(minutes=1)), repo, now=NOW + timedelta(minutes=2))
    assert repo.rows[0]["status"] == "open"


# ---------------------------------------------------------------------
# API auth boundary: no public unauthenticated write; cross-token
# rejection -- explicitly including the Kubernetes ingestion token
# (Gate 4: "Do not reuse the Kubernetes ingestion token").
# ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_fake_repository(client):
    fake = FakeIncidentRepository([])
    app.dependency_overrides[get_incident_repository] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_incident_repository, None)


def test_missing_token_returns_401(client):
    response = client.post("/internal/v1/aws/findings", json=_finding_body())
    assert response.status_code == 401


def test_incorrect_token_returns_401(client):
    response = client.post("/internal/v1/aws/findings", headers={"Authorization": "Bearer wrong-token"}, json=_finding_body())
    assert response.status_code == 401


@pytest.mark.parametrize(
    "other_token",
    [WEBHOOK_TOKEN, LIFECYCLE_TOKEN, REMEDIATION_PROPOSAL_TOKEN, REMEDIATION_APPROVER_TOKEN, REMEDIATION_EXECUTOR_TOKEN, KUBERNETES_INGESTION_TOKEN],
)
def test_every_other_token_is_rejected(client, other_token):
    response = client.post("/internal/v1/aws/findings", headers={"Authorization": f"Bearer {other_token}"}, json=_finding_body())
    assert response.status_code == 401


def test_aws_token_is_rejected_by_the_kubernetes_endpoint(client):
    """The symmetric cross-token check (Gate 4: 'Do not reuse the
    Kubernetes ingestion token'): the AWS ingestion token must NOT be
    able to authorize the Kubernetes finding-ingestion endpoint
    either."""
    response = client.post(
        "/internal/v1/kubernetes/findings",
        headers={"Authorization": f"Bearer {AWS_INGESTION_TOKEN}"},
        json={
            "cluster": "kind-reliability-lab", "namespace": "reliability-sandbox", "resource_kind": "Pod",
            "resource_name": "x", "detector_id": "crash_loop_backoff", "result": "confirmed",
            "collection_completeness": "complete", "collected_at": datetime.now(UTC).isoformat(),
            "decision_rationale": "x",
        },
    )
    assert response.status_code == 401


def test_correct_token_creates_an_incident(client):
    response = client.post("/internal/v1/aws/findings", headers=AUTH, json=_finding_body())
    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "created"
    assert body["severity"] == "critical"


def test_malformed_body_is_rejected_with_422(client):
    response = client.post("/internal/v1/aws/findings", headers=AUTH, json=_finding_body(account_id="not-an-account"))
    assert response.status_code == 422


# ---------------------------------------------------------------------
# GET /api/v1/incidents/{id}/aws-evidence
# ---------------------------------------------------------------------


def test_aws_evidence_404_for_unknown_incident(client):
    response = client.get(f"/api/v1/incidents/{uuid.uuid4()}/aws-evidence")
    assert response.status_code == 404


def test_aws_evidence_404_for_incident_with_no_aws_evidence(client):
    create = client.post("/internal/v1/aws/findings", headers=AUTH, json=_finding_body())
    assert create.status_code == 201
    other_incident_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/incidents/{other_incident_id}/aws-evidence")
    assert response.status_code == 404


def test_aws_evidence_returns_the_latest_trusted_evidence(client):
    create = client.post("/internal/v1/aws/findings", headers=AUTH, json=_finding_body())
    assert create.status_code == 201
    incident_id = create.json()["incident_id"]

    response = client.get(f"/api/v1/incidents/{incident_id}/aws-evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == ACCOUNT_ID
    assert body["region"] == REGION
    assert body["resource_kind"] == "CloudWatchAlarm"
    assert body["resource_id"] == "checkout-high-error-rate"
    assert body["detector_id"] == "cloudwatch_alarm_in_alarm_state"
    assert body["result"] == "confirmed"


def test_aws_evidence_preserves_decision_rationale_and_measured_evidence(client):
    """Correction round, Issue 4: the original symptom
    (decision_rationale) and supporting measurements (evidence dict --
    e.g. CloudWatch state_value/state_reason) must survive the full
    round trip -- ingestion -> persisted incident_events.metadata ->
    GET /api/v1/incidents/{id}/aws-evidence -- never silently
    dropped."""
    create = client.post(
        "/internal/v1/aws/findings", headers=AUTH,
        json=_finding_body(
            decision_rationale="CloudWatch alarm currently reports StateValue=ALARM (updated 2026-10-21T11:59:00Z)",
            evidence={
                "state_value": "ALARM", "state_reason": "Threshold Crossed: 1 datapoint was greater than 5.0",
                "namespace": "AWS/ApplicationELB", "metric_name": "HTTPCode_Target_5XX_Count",
            },
        ),
    )
    assert create.status_code == 201
    incident_id = create.json()["incident_id"]

    response = client.get(f"/api/v1/incidents/{incident_id}/aws-evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["decision_rationale"] == "CloudWatch alarm currently reports StateValue=ALARM (updated 2026-10-21T11:59:00Z)"
    assert body["evidence"]["state_value"] == "ALARM"
    assert body["evidence"]["state_reason"] == "Threshold Crossed: 1 datapoint was greater than 5.0"
    assert body["evidence"]["namespace"] == "AWS/ApplicationELB"
    assert body["evidence"]["metric_name"] == "HTTPCode_Target_5XX_Count"


def test_aws_evidence_reflects_the_most_recent_observation(client):
    create = client.post("/internal/v1/aws/findings", headers=AUTH, json=_finding_body())
    incident_id = create.json()["incident_id"]
    later = client.post(
        "/internal/v1/aws/findings", headers=AUTH,
        json=_finding_body(result="insufficient_evidence", collected_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat()),
    )
    assert later.status_code == 201
    assert later.json()["incident_id"] == incident_id

    response = client.get(f"/api/v1/incidents/{incident_id}/aws-evidence")
    assert response.status_code == 200
    assert response.json()["result"] == "insufficient_evidence"
