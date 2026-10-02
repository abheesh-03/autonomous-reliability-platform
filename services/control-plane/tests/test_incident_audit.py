"""Unit tests for the Phase 3E incident audit trail:

- GET /api/v1/incidents/{id}/events (api/incidents.py).
- The audit-event side effects of the three existing mutation paths —
  webhook firing/resolution ingestion (ingestion/service.py via
  api/webhook.py) and the operator PATCH endpoint (api/incidents.py) —
  which all live inside repositories/incident_repository.py's own
  mutation methods, not in any new code those callers had to add.

Like test_webhook.py/test_lifecycle.py, these use the in-memory
FakeIncidentRepository (conftest.py) via FastAPI's dependency_overrides
— no real database, and therefore NOT proof that an audit record and
its incident mutation really commit/roll back together in one real
PostgreSQL transaction. That real proof is
scripts/verify-incident-audit.sh; see this module's and that script's
own docstrings. These tests exist to prove the route/repository-call
wiring produces the right event, with the right attribution, for the
right (and only the right) operations.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from control_plane.api.dependencies import get_incident_repository
from control_plane.main import app
from tests.conftest import LIFECYCLE_TOKEN, WEBHOOK_TOKEN, make_incident_row
from tests.test_lifecycle import _patch, _row_for_status
from tests.test_webhook import _alert, _payload, _resolved_alert

WEBHOOK_URL = "/internal/v1/alertmanager/webhook"
AUTH_HEADERS = {"Authorization": f"Bearer {WEBHOOK_TOKEN}"}
LIFECYCLE_AUTH = {"Authorization": f"Bearer {LIFECYCLE_TOKEN}"}


def _events_url(incident_id) -> str:
    return f"/api/v1/incidents/{incident_id}/events"


# ---------------------------------------------------------------------
# Creation / observation events (webhook firing path)
# ---------------------------------------------------------------------


def test_firing_alert_records_a_created_event(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert(fingerprint="fp-audit-create")))
    assert response.status_code == 200
    incident_id = repo.rows[0]["id"]

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event["incident_id"] == incident_id
    assert event["event_type"] == "created"
    assert event["actor_type"] == "alertmanager"
    assert event["previous_status"] is None
    assert event["new_status"] == "open"

    events_response = client.get(_events_url(incident_id))
    assert events_response.status_code == 200
    body = events_response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["event_type"] == "created"
    assert item["actor_type"] == "alertmanager"
    assert item["previous_status"] is None
    assert item["new_status"] == "open"
    assert item["incident_id"] == str(incident_id)


def test_repeat_firing_into_active_incident_records_an_observed_event(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(hours=1)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-audit-observe",
        status="investigating",
        first_seen_at=occurrence_starts_at,
    )
    repo = use_repository([existing])

    alert = _alert(fingerprint="fp-audit-observe", startsAt=occurrence_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))
    assert response.status_code == 200

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event["incident_id"] == existing["id"]
    assert event["event_type"] == "observed"
    assert event["actor_type"] == "alertmanager"
    # The whole point of "observed": status is reported as both the
    # previous AND new value — it never actually changes.
    assert event["previous_status"] == "investigating"
    assert event["new_status"] == "investigating"


def test_creation_and_observation_are_distinct_event_types_across_two_deliveries(use_repository, client):
    repo = use_repository([])
    starts_at = datetime.now(UTC)

    first = client.post(
        WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert(fingerprint="fp-audit-distinct", startsAt=starts_at.isoformat()))
    )
    assert first.status_code == 200
    second = client.post(
        WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert(fingerprint="fp-audit-distinct", startsAt=starts_at.isoformat()))
    )
    assert second.status_code == 200

    assert len(repo.events) == 2
    assert repo.events[0]["event_type"] == "created"
    assert repo.events[1]["event_type"] == "observed"


# ---------------------------------------------------------------------
# Operator PATCH transitions
# ---------------------------------------------------------------------


def test_operator_patch_records_a_status_transition_event_attributed_to_operator(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "acknowledged")
    assert response.status_code == 200

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event["incident_id"] == row["id"]
    assert event["event_type"] == "status_transition"
    assert event["actor_type"] == "operator"
    assert event["previous_status"] == "open"
    assert event["new_status"] == "acknowledged"


def test_operator_actor_type_never_fabricates_an_individual_identity(use_repository, client):
    # The lifecycle token is a SHARED secret, not a per-user credential
    # — actor_type='operator' must never claim to identify a specific
    # human. The event carries no user-id-shaped field at all.
    row = _row_for_status("open")
    repo = use_repository([row])

    _patch(client, row["id"], "open", "acknowledged")

    event = repo.events[0]
    assert set(event) == {"id", "incident_id", "event_type", "actor_type", "previous_status", "new_status", "occurred_at", "metadata"}
    assert event["actor_type"] == "operator"
    assert "user" not in event["metadata"]
    assert "user_id" not in event["metadata"]


# ---------------------------------------------------------------------
# Source-driven automatic resolution
# ---------------------------------------------------------------------


def test_automatic_resolution_records_a_status_transition_event_attributed_to_alertmanager(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(minutes=30)
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-audit-resolve",
        status="investigating",
        first_seen_at=occurrence_starts_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    resolved = _resolved_alert(fingerprint="fp-audit-resolve", starts_at=occurrence_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert response.status_code == 200

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event["incident_id"] == active["id"]
    assert event["event_type"] == "status_transition"
    assert event["actor_type"] == "alertmanager"
    assert event["previous_status"] == "investigating"
    assert event["new_status"] == "resolved"


# ---------------------------------------------------------------------
# Ordered timeline and pagination
# ---------------------------------------------------------------------


def test_timeline_is_ordered_and_paginated(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    _patch(client, row["id"], "open", "acknowledged")
    _patch(client, row["id"], "acknowledged", "investigating")
    _patch(client, row["id"], "investigating", "remediating")

    full = client.get(_events_url(row["id"]))
    assert full.status_code == 200
    full_body = full.json()
    assert full_body["total"] == 3
    transitions = [(e["previous_status"], e["new_status"]) for e in full_body["items"]]
    assert transitions == [("open", "acknowledged"), ("acknowledged", "investigating"), ("investigating", "remediating")]

    page1 = client.get(_events_url(row["id"]), params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    page1_body = page1.json()
    assert page1_body["total"] == 3
    assert len(page1_body["items"]) == 2
    assert [(e["previous_status"], e["new_status"]) for e in page1_body["items"]] == [
        ("open", "acknowledged"),
        ("acknowledged", "investigating"),
    ]

    page2 = client.get(_events_url(row["id"]), params={"limit": 2, "offset": 2})
    assert page2.status_code == 200
    page2_body = page2.json()
    assert len(page2_body["items"]) == 1
    assert (page2_body["items"][0]["previous_status"], page2_body["items"][0]["new_status"]) == ("investigating", "remediating")


def test_default_pagination_limit_is_twenty():
    import inspect

    from control_plane.api.incidents import list_incident_events

    sig = inspect.signature(list_incident_events)
    assert sig.parameters["limit"].default == 20


def test_events_limit_and_offset_are_validated(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])

    assert client.get(_events_url(row["id"]), params={"limit": 0}).status_code == 422
    assert client.get(_events_url(row["id"]), params={"limit": 101}).status_code == 422
    assert client.get(_events_url(row["id"]), params={"offset": -1}).status_code == 422


def test_events_for_incident_with_no_history_returns_empty_timeline(use_repository, client):
    # A pre-Phase-3E incident (or one that has only ever been read) has
    # no recorded history — this is a genuine 200 with an empty list,
    # never fabricated and never a 404.
    row = _row_for_status("open")
    use_repository([row])

    response = client.get(_events_url(row["id"]))
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


# ---------------------------------------------------------------------
# Missing incident / invalid UUID
# ---------------------------------------------------------------------


def test_events_for_missing_incident_returns_404(use_repository, client):
    use_repository([])

    response = client.get(_events_url(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json() == {"detail": "incident not found"}


def test_events_invalid_uuid_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents/not-a-uuid/events")
    assert response.status_code == 422


# ---------------------------------------------------------------------
# No events for rejected / ignored / no-op scenarios
# ---------------------------------------------------------------------


def test_illegal_transition_records_no_event(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "remediating")
    assert response.status_code == 409
    assert repo.events == []


def test_stale_expected_status_records_no_event(use_repository, client):
    row = _row_for_status("acknowledged")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "investigating")
    assert response.status_code == 409
    assert repo.events == []


def test_same_status_noop_records_no_event(use_repository, client):
    row = _row_for_status("investigating")
    repo = use_repository([row])

    response = _patch(client, row["id"], "investigating", "investigating")
    assert response.status_code == 200
    assert repo.events == []


def test_missing_incident_patch_records_no_event(use_repository, client):
    repo = use_repository([])

    response = _patch(client, uuid.uuid4(), "open", "acknowledged")
    assert response.status_code == 404
    assert repo.events == []


def test_missing_lifecycle_credentials_record_no_event(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = client.patch(
        f"/api/v1/incidents/{row['id']}/status",
        json={"expected_status": "open", "target_status": "acknowledged"},
    )
    assert response.status_code == 401
    assert repo.events == []


def test_missing_webhook_credentials_record_no_event(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, json=_payload(_alert(fingerprint="fp-audit-noauth")))
    assert response.status_code == 401
    assert repo.events == []


def test_stale_firing_replay_records_no_event(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(hours=2)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-audit-stale-firing",
        status="open",
        first_seen_at=occurrence_starts_at,
    )
    repo = use_repository([existing])

    older_starts_at = occurrence_starts_at - timedelta(hours=1)
    response = client.post(
        WEBHOOK_URL,
        headers=AUTH_HEADERS,
        json=_payload(_alert(fingerprint="fp-audit-stale-firing", startsAt=older_starts_at.isoformat())),
    )
    assert response.status_code == 200
    assert response.json()["incidents_ignored"] == 1
    assert repo.events == []


def test_ignored_resolved_notification_records_no_event(use_repository, client):
    repo = use_repository([])

    resolved = _resolved_alert(fingerprint="fp-audit-no-active", starts_at=datetime.now(UTC).isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert response.status_code == 200
    assert response.json()["incidents_ignored"] == 1
    assert repo.events == []


def test_duplicate_resolution_after_success_records_no_second_event(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(minutes=30)
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-audit-dup-resolve",
        status="open",
        first_seen_at=occurrence_starts_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    resolved = _resolved_alert(fingerprint="fp-audit-dup-resolve", starts_at=occurrence_starts_at.isoformat())
    first = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert first.status_code == 200
    assert first.json()["incidents_resolved"] == 1
    assert len(repo.events) == 1

    second = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert second.status_code == 200
    assert second.json()["incidents_ignored"] == 1
    # Still exactly one event — the duplicate delivery recorded nothing.
    assert len(repo.events) == 1


# ---------------------------------------------------------------------
# Concurrent operator transitions: one winner, one event
# ---------------------------------------------------------------------


def test_only_the_winning_concurrent_transition_records_an_event(use_repository, client):
    # A true concurrent-request race needs a real database — this is
    # the route-logic-level proxy: two sequential attempts from the
    # same expected_status, modeling "loser arrives after the winner
    # already committed" (the only way a loser's attempt can conclude
    # once a real atomic compare-and-swap has already succeeded for
    # the other request). Real concurrency is proven by
    # scripts/verify-incident-audit.sh.
    row = _row_for_status("open")
    repo = use_repository([row])

    winner = _patch(client, row["id"], "open", "acknowledged")
    assert winner.status_code == 200

    loser = _patch(client, row["id"], "open", "acknowledged")
    assert loser.status_code == 409

    assert len(repo.events) == 1
    assert repo.events[0]["new_status"] == "acknowledged"


# ---------------------------------------------------------------------
# Transaction rollback when audit insertion fails
# ---------------------------------------------------------------------


def test_audit_insertion_failure_does_not_commit(use_repository, client):
    # A real rollback (the incident mutation AND the failed audit
    # insert both discarded together) can only be proven against a
    # real PostgreSQL transaction — scripts/verify-incident-audit.sh
    # does that. At the unit level, the correct, honest proxy is: the
    # route must never call commit() when the repository raises,
    # regardless of which statement inside it failed — exactly the
    # same proxy Phase 3D's own commit-bug regression tests use (see
    # test_lifecycle.py's test_rejected_transition_does_not_commit).
    class _AuditInsertFailureRepository:
        def __init__(self):
            self.commit_count = 0

        async def get_by_id(self, incident_id):
            return None

        async def transition_incident_status(self, *args, **kwargs):
            # Simulates the audit INSERT (the last statement inside
            # the real method) raising before anything returns —
            # indistinguishable, from the caller's perspective, from
            # any other mid-method database failure.
            raise OperationalError("INSERT ...", {}, Exception("connection refused, password=supersecret"))

        async def commit(self):
            self.commit_count += 1

    broken = _AuditInsertFailureRepository()
    app.dependency_overrides[get_incident_repository] = lambda: broken

    response = _patch(client, uuid.uuid4(), "open", "acknowledged")

    assert response.status_code == 503
    assert broken.commit_count == 0
    assert "supersecret" not in response.text


# ---------------------------------------------------------------------
# No credentials or raw webhook payloads in metadata
# ---------------------------------------------------------------------


def test_metadata_never_contains_credentials_or_raw_payload(use_repository, client):
    repo = use_repository([])

    client.post(
        WEBHOOK_URL,
        headers=AUTH_HEADERS,
        json=_payload(_alert(fingerprint="fp-audit-no-secrets", annotations={"summary": "s", "description": "d"})),
    )

    assert len(repo.events) == 1
    metadata = repo.events[0]["metadata"]
    # Allowlisted keys only.
    assert set(metadata) <= {"source_fingerprint", "observed_starts_at", "resolution_source"}
    serialized = str(metadata)
    assert WEBHOOK_TOKEN not in serialized
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.parametrize(
    "event",
    [
        {"event_type": "created", "actor_type": "alertmanager", "previous_status": None, "new_status": "open", "metadata": {}},
    ],
)
def test_incident_event_model_serializes_cleanly(event):
    from control_plane.domain.incident_event import IncidentEvent

    row = {
        "id": 1,
        "incident_id": uuid.uuid4(),
        "occurred_at": datetime.now(UTC),
        **event,
    }
    model = IncidentEvent.model_validate(row)
    assert model.event_type == "created"
    assert model.previous_status is None
