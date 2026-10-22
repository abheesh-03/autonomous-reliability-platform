"""Phase 12B-D, Gate 2 + Gate 8 (categories A/B/C/D/F/Y): the
Kubernetes finding-ingestion domain model, mapping, occurrence-identity
service logic, and the authenticated endpoint's auth boundary. Mirrors
test_webhook.py's own structure for the Alertmanager path."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.kubernetes_finding import KubernetesFindingIngestRequest
from control_plane.ingestion.kubernetes_mapping import (
    kubernetes_finding_fingerprint,
    map_kubernetes_finding_to_incident_fields,
)
from control_plane.ingestion.kubernetes_service import (
    KubernetesIngestionRejected,
    ingest_kubernetes_finding,
)
from control_plane.main import app
from tests.conftest import (
    KUBERNETES_INGESTION_TOKEN,
    LIFECYCLE_TOKEN,
    REMEDIATION_APPROVER_TOKEN,
    REMEDIATION_EXECUTOR_TOKEN,
    REMEDIATION_PROPOSAL_TOKEN,
    WEBHOOK_TOKEN,
    FakeIncidentRepository,
    make_incident_row,
)

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
AUTH = {"Authorization": f"Bearer {KUBERNETES_INGESTION_TOKEN}"}


def _finding(**overrides) -> KubernetesFindingIngestRequest:
    fields = {
        "cluster": "kind-reliability-lab",
        "namespace": "reliability-sandbox",
        "resource_kind": "Pod",
        "resource_name": "crashloop-demo-abc123",
        "resource_uid": "uid-1",
        "detector_id": "crash_loop_backoff",
        "result": "confirmed",
        "collection_completeness": "complete",
        "collected_at": NOW,
        "decision_rationale": "container app has waiting.reason == 'CrashLoopBackOff'",
        "evidence": {"restart_count": "6"},
        "supporting_event_reasons": ["BackOff"],
    }
    fields.update(overrides)
    return KubernetesFindingIngestRequest(**fields)


def _finding_body(**overrides) -> dict:
    # These bodies go through the REAL HTTP endpoint (client.post),
    # which always evaluates freshness against the REAL wall clock
    # (datetime.now(UTC) -- there is no way to inject a fixed "now"
    # through the HTTP API layer, unlike the pure-function tests below
    # which call ingest_kubernetes_finding(..., now=NOW) directly).
    # collected_at must therefore be close to real "now" by default, or
    # the correction round's own MAX_PAST_STALENESS_SECONDS bound
    # (ingestion/kubernetes_service.py) would reject it as stale.
    body = {
        "cluster": "kind-reliability-lab",
        "namespace": "reliability-sandbox",
        "resource_kind": "Pod",
        "resource_name": "crashloop-demo-abc123",
        "resource_uid": "uid-1",
        "detector_id": "crash_loop_backoff",
        "result": "confirmed",
        "collection_completeness": "complete",
        "collected_at": datetime.now(UTC).isoformat(),
        "decision_rationale": "container app has waiting.reason == 'CrashLoopBackOff'",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------
# Domain validation: bounded fields, real Kubernetes identity patterns,
# prevent cross-namespace injection
# ---------------------------------------------------------------------


def test_valid_finding_parses_cleanly():
    f = _finding()
    assert f.cluster == "kind-reliability-lab"


@pytest.mark.parametrize(
    "bad_namespace", ["Reliability-Sandbox", "../etc", "ns; rm -rf /", "", "UPPER", "ns/../other"]
)
def test_invalid_namespace_is_rejected(bad_namespace):
    with pytest.raises(ValidationError):
        _finding(namespace=bad_namespace)


def test_naive_collected_at_is_rejected():
    with pytest.raises(ValidationError):
        KubernetesFindingIngestRequest(
            cluster="kind-reliability-lab",
            namespace="reliability-sandbox",
            resource_kind="Pod",
            resource_name="x",
            detector_id="crash_loop_backoff",
            result="confirmed",
            collection_completeness="complete",
            collected_at=datetime(2026, 1, 1),  # no tzinfo
            decision_rationale="x",
        )


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        _finding(unexpected_field="x")


def test_oversized_evidence_value_is_rejected():
    with pytest.raises(ValidationError):
        _finding(evidence={"k": "x" * 3000})


# ---------------------------------------------------------------------
# Fingerprint / mapping: stable dedup identity, never includes UID
# ---------------------------------------------------------------------


def test_fingerprint_is_stable_across_different_uids_and_timestamps():
    """Category D: a recreated resource (different UID) with the SAME
    identity/detector still maps to the SAME fingerprint -- the
    ongoing operational concern is tracked as one incident, never
    silently split."""
    a = _finding(resource_uid="uid-1", collected_at=NOW)
    b = _finding(resource_uid="uid-2", collected_at=NOW + timedelta(minutes=10))
    assert kubernetes_finding_fingerprint(a) == kubernetes_finding_fingerprint(b)


def test_fingerprint_differs_for_different_resources_or_detectors():
    """Category C: unrelated failures must not be blindly merged."""
    base = kubernetes_finding_fingerprint(_finding())
    different_name = kubernetes_finding_fingerprint(_finding(resource_name="other-pod"))
    different_detector = kubernetes_finding_fingerprint(_finding(detector_id="oom_killed"))
    different_namespace = kubernetes_finding_fingerprint(_finding(namespace="other-namespace"))
    assert len({base, different_name, different_detector, different_namespace}) == 4


def test_mapping_severity_reflects_detector_result():
    confirmed = map_kubernetes_finding_to_incident_fields(_finding(result="confirmed"), ingested_at=NOW)
    insufficient = map_kubernetes_finding_to_incident_fields(
        _finding(result="insufficient_evidence"), ingested_at=NOW
    )
    assert confirmed["severity"] == "critical"
    assert insufficient["severity"] == "warning"


def test_mapping_occurrence_watermark_is_the_findings_own_collected_at():
    fields = map_kubernetes_finding_to_incident_fields(_finding(), ingested_at=NOW + timedelta(minutes=1))
    assert fields["occurrence_starts_at"] == NOW
    assert fields["first_seen_at"] == NOW
    assert fields["last_seen_at"] == NOW + timedelta(minutes=1)


# ---------------------------------------------------------------------
# Service: occurrence-identity decision logic (categories A, B, C, D, F)
# ---------------------------------------------------------------------


async def test_new_finding_creates_an_incident():
    """Category A: detection -> durable incident ingestion."""
    repo = FakeIncidentRepository([])
    incident_id, outcome, severity = await ingest_kubernetes_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    assert outcome == "created"
    assert severity == "critical"
    assert repo.commit_count == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["source"] == "kubernetes"
    assert repo.events[-1]["actor_type"] == "kubernetes"
    assert repo.events[-1]["event_type"] == "created"


async def test_repeat_ingestion_of_the_same_finding_updates_not_duplicates():
    """Category B: duplicate ingestion and idempotency -- never a
    second incident for the same ongoing failure."""
    repo = FakeIncidentRepository([])
    await ingest_kubernetes_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    incident_id_2, outcome_2, _ = await ingest_kubernetes_finding(
        _finding(collected_at=NOW + timedelta(minutes=1)), repo, now=NOW + timedelta(minutes=2)
    )
    assert outcome_2 == "updated"
    assert len(repo.rows) == 1  # still exactly one incident


async def test_unrelated_finding_creates_a_separate_incident():
    """Category C: separate incidents for unrelated failures."""
    repo = FakeIncidentRepository([])
    await ingest_kubernetes_finding(_finding(), repo, now=NOW + timedelta(seconds=1))
    await ingest_kubernetes_finding(
        _finding(resource_name="other-pod", collected_at=NOW), repo, now=NOW + timedelta(seconds=1)
    )
    assert len(repo.rows) == 2


async def test_recreated_resource_with_different_uid_updates_the_same_incident_and_records_it_honestly():
    """Category D: incident identity and resource UID changes -- the
    SAME incident is updated (never silently split), but the NEW uid
    is honestly recorded in the audit trail."""
    repo = FakeIncidentRepository([])
    await ingest_kubernetes_finding(_finding(resource_uid="uid-1"), repo, now=NOW + timedelta(seconds=1))
    await ingest_kubernetes_finding(
        _finding(resource_uid="uid-2", collected_at=NOW + timedelta(minutes=1)),
        repo,
        now=NOW + timedelta(minutes=2),
    )
    assert len(repo.rows) == 1
    assert repo.events[-1]["metadata"]["resource_uid"] == "uid-2"
    assert repo.events[0]["metadata"]["resource_uid"] == "uid-1"


async def test_stale_replay_against_an_active_incident_is_ignored():
    """A previous stale event must not establish current failure."""
    repo = FakeIncidentRepository([])
    await ingest_kubernetes_finding(_finding(collected_at=NOW), repo, now=NOW + timedelta(seconds=1))
    incident_id, outcome, _ = await ingest_kubernetes_finding(
        _finding(collected_at=NOW - timedelta(minutes=5)), repo, now=NOW + timedelta(seconds=2)
    )
    assert outcome == "ignored"
    assert len(repo.rows) == 1
    assert repo.rows[0]["occurrence_starts_at"] == NOW  # watermark never regresses


async def test_future_dated_evidence_is_rejected_never_accepted_as_current():
    """Category F (stale/future evidence): a wildly future collected_at
    is rejected outright, not silently clamped or accepted."""
    repo = FakeIncidentRepository([])
    with pytest.raises(KubernetesIngestionRejected):
        await ingest_kubernetes_finding(
            _finding(collected_at=NOW + timedelta(hours=1)), repo, now=NOW
        )
    assert repo.rows == []
    assert repo.commit_count == 0


async def test_old_detector_observation_cannot_create_a_new_active_incident():
    """Correction round (Issue 6): an old (stale-relative-to-now)
    detector observation must never create a BRAND NEW incident as
    though the failure is current -- distinct from the stale-REPLAY
    case above (which compares against an existing watermark), this
    has NO existing incident/watermark to compare against at all, so
    it needs its own, unconditional freshness bound."""
    from control_plane.ingestion.kubernetes_service import MAX_PAST_STALENESS_SECONDS

    repo = FakeIncidentRepository([])
    stale_collected_at = NOW - timedelta(seconds=MAX_PAST_STALENESS_SECONDS + 1)
    with pytest.raises(KubernetesIngestionRejected):
        await ingest_kubernetes_finding(_finding(collected_at=stale_collected_at), repo, now=NOW)
    assert repo.rows == []
    assert repo.commit_count == 0


async def test_insufficient_evidence_result_still_ingests_as_a_weaker_severity():
    """Missing/partial evidence is preserved, never silently dropped --
    but mapped to a correspondingly weaker severity, never 'critical'."""
    repo = FakeIncidentRepository([])
    incident_id, outcome, severity = await ingest_kubernetes_finding(
        _finding(result="insufficient_evidence", collection_completeness="partial"), repo, now=NOW + timedelta(seconds=1)
    )
    assert outcome == "created"
    assert severity == "warning"
    assert repo.events[-1]["metadata"]["collection_completeness"] == "partial"


# ---------------------------------------------------------------------
# API auth boundary (category Y: no public unauthenticated write;
# cross-token rejection)
# ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_fake_repository(client):
    fake = FakeIncidentRepository([])
    app.dependency_overrides[get_incident_repository] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_incident_repository, None)


def test_missing_token_returns_401(client):
    response = client.post("/internal/v1/kubernetes/findings", json=_finding_body())
    assert response.status_code == 401


def test_incorrect_token_returns_401(client):
    response = client.post(
        "/internal/v1/kubernetes/findings", headers={"Authorization": "Bearer wrong-token"}, json=_finding_body()
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "other_token",
    [WEBHOOK_TOKEN, LIFECYCLE_TOKEN, REMEDIATION_PROPOSAL_TOKEN, REMEDIATION_APPROVER_TOKEN, REMEDIATION_EXECUTOR_TOKEN],
)
def test_every_other_token_is_rejected(client, other_token):
    response = client.post(
        "/internal/v1/kubernetes/findings",
        headers={"Authorization": f"Bearer {other_token}"},
        json=_finding_body(),
    )
    assert response.status_code == 401


def test_correct_token_creates_an_incident(client):
    response = client.post("/internal/v1/kubernetes/findings", headers=AUTH, json=_finding_body())
    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "created"
    assert body["severity"] == "critical"


def test_malformed_body_is_rejected_with_422(client):
    response = client.post(
        "/internal/v1/kubernetes/findings", headers=AUTH, json=_finding_body(namespace="Not_Valid!")
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------
# GET /api/v1/incidents/{id}/kubernetes-evidence (correction round,
# Issue 1): the trusted, persisted source of a Kubernetes incident's
# own resource identity.
# ---------------------------------------------------------------------


def test_kubernetes_evidence_404_for_unknown_incident(client):
    response = client.get(f"/api/v1/incidents/{uuid.uuid4()}/kubernetes-evidence")
    assert response.status_code == 404


def test_kubernetes_evidence_404_for_incident_with_no_kubernetes_evidence(client):
    create = client.post("/internal/v1/kubernetes/findings", headers=AUTH, json=_finding_body())
    assert create.status_code == 201
    other_incident_id = str(uuid.uuid4())  # a real incident this fixture never created
    response = client.get(f"/api/v1/incidents/{other_incident_id}/kubernetes-evidence")
    assert response.status_code == 404


def test_kubernetes_evidence_returns_the_latest_trusted_evidence(client):
    create = client.post("/internal/v1/kubernetes/findings", headers=AUTH, json=_finding_body())
    assert create.status_code == 201
    incident_id = create.json()["incident_id"]

    response = client.get(f"/api/v1/incidents/{incident_id}/kubernetes-evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["cluster"] == "kind-reliability-lab"
    assert body["namespace"] == "reliability-sandbox"
    assert body["resource_kind"] == "Pod"
    assert body["resource_name"] == "crashloop-demo-abc123"
    assert body["resource_uid"] == "uid-1"
    assert body["detector_id"] == "crash_loop_backoff"
    assert body["result"] == "confirmed"


def test_kubernetes_evidence_reflects_the_most_recent_observation(client):
    create = client.post("/internal/v1/kubernetes/findings", headers=AUTH, json=_finding_body())
    incident_id = create.json()["incident_id"]
    later = client.post(
        "/internal/v1/kubernetes/findings",
        headers=AUTH,
        json=_finding_body(resource_uid="uid-2", collected_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat()),
    )
    assert later.status_code == 201
    assert later.json()["incident_id"] == incident_id  # same fingerprint -- same incident, updated

    response = client.get(f"/api/v1/incidents/{incident_id}/kubernetes-evidence")
    assert response.status_code == 200
    assert response.json()["resource_uid"] == "uid-2"
