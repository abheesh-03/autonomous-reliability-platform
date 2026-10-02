"""Unit tests for the Phase 3D incident lifecycle:

- The centralized state machine (domain/lifecycle.py) — pure Python,
  no HTTP, no repository at all.
- PATCH /api/v1/incidents/{id}/status (api/incidents.py), using the
  same in-memory FakeIncidentRepository (conftest.py) Phase 3C's
  webhook tests use. Real PostgreSQL atomic compare-and-swap behavior
  and real concurrent-request races are proven separately by
  scripts/verify-incident-lifecycle.sh — mocked repository tests alone
  are NOT proof of real database concurrency, only of this route's own
  request/response/validation logic.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from control_plane.api.dependencies import get_incident_repository
from control_plane.domain.lifecycle import ALLOWED_TRANSITIONS, entering_resolved, is_transition_allowed
from control_plane.main import app
from tests.conftest import LIFECYCLE_TOKEN, WEBHOOK_TOKEN, make_incident_row

LIFECYCLE_AUTH = {"Authorization": f"Bearer {LIFECYCLE_TOKEN}"}

ALL_STATUSES = ["open", "acknowledged", "investigating", "remediating", "resolved", "closed"]

PERMITTED_TRANSITIONS = [
    ("open", "acknowledged"),
    ("open", "investigating"),
    ("open", "resolved"),
    ("acknowledged", "investigating"),
    ("acknowledged", "resolved"),
    ("investigating", "remediating"),
    ("investigating", "resolved"),
    ("remediating", "investigating"),
    ("remediating", "resolved"),
    ("resolved", "closed"),
]

# Every (current, target) pair NOT in PERMITTED_TRANSITIONS, including
# same-status pairs — a status is never "allowed to transition to
# itself" in this table; that is a deliberately separate no-op case
# (see domain/lifecycle.py's module docstring and the no-op tests
# below), not part of this matrix.
FORBIDDEN_TRANSITIONS = [
    (current, target)
    for current in ALL_STATUSES
    for target in ALL_STATUSES
    if (current, target) not in PERMITTED_TRANSITIONS
]


def _patch(client, incident_id, expected_status, target_status, headers=LIFECYCLE_AUTH):
    return client.patch(
        f"/api/v1/incidents/{incident_id}/status",
        headers=headers,
        json={"expected_status": expected_status, "target_status": target_status},
    )


def _row_for_status(status: str, **overrides) -> dict:
    """A plausible incident row for the given status — resolved_at
    populated for resolved/closed (matching the real schema's own
    CHECK constraint), None otherwise."""
    defaults = {"status": status}
    if status in ("resolved", "closed"):
        defaults["resolved_at"] = datetime.now(UTC) - timedelta(hours=1)
    else:
        defaults["resolved_at"] = None
    defaults.update(overrides)
    return make_incident_row(**defaults)


# ---------------------------------------------------------------------
# Pure state machine — domain/lifecycle.py
# ---------------------------------------------------------------------


@pytest.mark.parametrize("current,target", PERMITTED_TRANSITIONS)
def test_every_permitted_transition_is_allowed(current, target):
    assert is_transition_allowed(current, target) is True


@pytest.mark.parametrize("current,target", FORBIDDEN_TRANSITIONS)
def test_every_forbidden_transition_is_rejected(current, target):
    assert is_transition_allowed(current, target) is False


def test_closed_permits_no_further_transitions():
    assert ALLOWED_TRANSITIONS["closed"] == frozenset()


def test_resolved_at_should_only_be_set_entering_resolved():
    assert entering_resolved("resolved") is True
    for status in ["open", "acknowledged", "investigating", "remediating", "closed"]:
        assert entering_resolved(status) is False


# ---------------------------------------------------------------------
# PATCH /api/v1/incidents/{id}/status — every permitted transition
# ---------------------------------------------------------------------


@pytest.mark.parametrize("current,target", PERMITTED_TRANSITIONS)
def test_patch_every_permitted_transition_succeeds(use_repository, client, current, target):
    row = _row_for_status(current)
    use_repository([row])

    response = _patch(client, row["id"], current, target)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == target
    assert body["id"] == str(row["id"])


@pytest.mark.parametrize("current,target", FORBIDDEN_TRANSITIONS)
def test_patch_every_forbidden_transition_returns_409_and_leaves_row_unchanged(use_repository, client, current, target):
    if current == target:
        return  # same-status is a separate, documented no-op case — see below
    row = _row_for_status(current)
    repo = use_repository([row])
    original = dict(row)

    response = _patch(client, row["id"], current, target)

    assert response.status_code == 409, response.text
    assert repo.rows[0] == original


# ---------------------------------------------------------------------
# Same-status no-op
# ---------------------------------------------------------------------


def test_same_status_noop_returns_200_without_mutating_anything(use_repository, client):
    original_updated_at = datetime.now(UTC) - timedelta(minutes=5)
    row = _row_for_status("investigating", updated_at=original_updated_at)
    repo = use_repository([row])

    response = _patch(client, row["id"], "investigating", "investigating")

    assert response.status_code == 200
    assert response.json()["status"] == "investigating"
    # Not even updated_at changes — this is a documented no-op, not a
    # real (if trivial) write.
    assert repo.rows[0]["updated_at"] == original_updated_at


def test_same_status_noop_with_stale_actual_status_returns_409(use_repository, client):
    # Caller declares expected_status=target_status="open", but the
    # incident has actually moved on to "acknowledged" — still a
    # concurrency conflict, reported the same way a real transition
    # attempt would be.
    row = _row_for_status("acknowledged")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "open")

    assert response.status_code == 409
    assert repo.rows[0]["status"] == "acknowledged"


def test_same_status_noop_missing_incident_returns_404(use_repository, client):
    use_repository([])

    response = _patch(client, uuid.uuid4(), "open", "open")

    assert response.status_code == 404


# ---------------------------------------------------------------------
# Stale expected_status (real transition attempt)
# ---------------------------------------------------------------------


def test_stale_expected_status_returns_409_and_leaves_row_unchanged(use_repository, client):
    row = _row_for_status("acknowledged")
    repo = use_repository([row])
    original = dict(row)

    # A legal transition in the abstract (open -> investigating), but
    # the incident's actual status is "acknowledged", not "open".
    response = _patch(client, row["id"], "open", "investigating")

    assert response.status_code == 409
    assert repo.rows[0] == original


# ---------------------------------------------------------------------
# Missing incident / invalid UUID / invalid status values
# ---------------------------------------------------------------------


def test_missing_incident_returns_404(use_repository, client):
    use_repository([])

    response = _patch(client, uuid.uuid4(), "open", "acknowledged")

    assert response.status_code == 404
    assert response.json() == {"detail": "incident not found"}


def test_invalid_uuid_returns_422(use_repository, client):
    use_repository([])

    response = client.patch(
        "/api/v1/incidents/not-a-uuid/status",
        headers=LIFECYCLE_AUTH,
        json={"expected_status": "open", "target_status": "acknowledged"},
    )

    assert response.status_code == 422


def test_invalid_target_status_returns_422(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])

    response = _patch(client, row["id"], "open", "bogus-status")

    assert response.status_code == 422


def test_invalid_expected_status_returns_422(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])

    response = _patch(client, row["id"], "bogus-status", "acknowledged")

    assert response.status_code == 422


def test_extra_field_in_request_body_returns_422(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])

    response = client.patch(
        f"/api/v1/incidents/{row['id']}/status",
        headers=LIFECYCLE_AUTH,
        json={"expected_status": "open", "target_status": "acknowledged", "force": True},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------
# Authentication — missing/incorrect credentials, and token separation
# ---------------------------------------------------------------------


def test_missing_lifecycle_token_returns_401_and_does_not_mutate(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = client.patch(
        f"/api/v1/incidents/{row['id']}/status",
        json={"expected_status": "open", "target_status": "acknowledged"},
    )

    assert response.status_code == 401
    assert repo.rows[0]["status"] == "open"


def test_incorrect_lifecycle_token_returns_401_and_does_not_mutate(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "acknowledged", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert repo.rows[0]["status"] == "open"


def test_webhook_token_cannot_authenticate_the_lifecycle_endpoint(use_repository, client):
    # The two tokens are deliberately separate secrets — Alertmanager
    # (which only ever holds the webhook token) must not be able to
    # invoke this human/operator endpoint.
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "acknowledged", headers={"Authorization": f"Bearer {WEBHOOK_TOKEN}"})

    assert response.status_code == 401
    assert repo.rows[0]["status"] == "open"


def test_lifecycle_token_cannot_authenticate_the_webhook_endpoint(use_repository, client):
    use_repository([])

    response = client.post(
        "/internal/v1/alertmanager/webhook",
        headers={"Authorization": f"Bearer {LIFECYCLE_TOKEN}"},
        json={
            "version": "4",
            "groupKey": "x",
            "status": "firing",
            "receiver": "y",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "X", "severity": "critical"},
                    "annotations": {},
                    "startsAt": datetime.now(UTC).isoformat(),
                    "fingerprint": "fp-cross-token-test",
                }
            ],
        },
    )

    assert response.status_code == 401


def test_unconfigured_lifecycle_token_fails_closed(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])
    original = app.state.lifecycle_token
    app.state.lifecycle_token = None
    try:
        response = _patch(client, row["id"], "open", "acknowledged")
        assert response.status_code == 401
    finally:
        app.state.lifecycle_token = original


def test_no_lifecycle_credentials_leaked_in_responses(use_repository, client):
    row = _row_for_status("open")
    use_repository([row])

    missing = client.patch(
        f"/api/v1/incidents/{row['id']}/status",
        json={"expected_status": "open", "target_status": "acknowledged"},
    )
    wrong = _patch(client, row["id"], "open", "acknowledged", headers={"Authorization": "Bearer wrong-token"})

    for response in (missing, wrong):
        assert response.status_code == 401
        assert LIFECYCLE_TOKEN not in response.text


# ---------------------------------------------------------------------
# resolved_at semantics
# ---------------------------------------------------------------------


def test_resolved_at_set_on_entering_resolved(use_repository, client):
    row = _row_for_status("investigating")
    repo = use_repository([row])

    response = _patch(client, row["id"], "investigating", "resolved")

    assert response.status_code == 200
    body = response.json()
    assert body["resolved_at"] is not None
    assert repo.rows[0]["resolved_at"] is not None


def test_resolved_at_preserved_on_closure_not_overwritten(use_repository, client):
    original_resolved_at = datetime.now(UTC) - timedelta(hours=3)
    row = _row_for_status("resolved", resolved_at=original_resolved_at)
    repo = use_repository([row])

    response = _patch(client, row["id"], "resolved", "closed")

    assert response.status_code == 200
    body = response.json()
    assert repo.rows[0]["resolved_at"] == original_resolved_at
    assert datetime.fromisoformat(body["resolved_at"]) == original_resolved_at


@pytest.mark.parametrize("current", ["open", "acknowledged", "investigating", "remediating"])
def test_resolved_at_stays_null_for_non_resolving_transitions(use_repository, client, current):
    row = _row_for_status(current)
    repo = use_repository([row])
    target = next(t for t in ALLOWED_TRANSITIONS[current] if t != "resolved")

    response = _patch(client, row["id"], current, target)

    assert response.status_code == 200
    assert repo.rows[0]["resolved_at"] is None


# ---------------------------------------------------------------------
# No timestamp mutation for rejected transitions
# ---------------------------------------------------------------------


def test_illegal_transition_leaves_every_timestamp_unchanged(use_repository, client):
    original_updated_at = datetime.now(UTC) - timedelta(minutes=10)
    original_resolved_at = None
    row = _row_for_status("open", updated_at=original_updated_at, resolved_at=original_resolved_at)
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "remediating")  # not a legal transition

    assert response.status_code == 409
    assert repo.rows[0]["updated_at"] == original_updated_at
    assert repo.rows[0]["resolved_at"] == original_resolved_at
    assert repo.rows[0]["status"] == "open"


# ---------------------------------------------------------------------
# Resolved and closed cannot regress
# ---------------------------------------------------------------------


@pytest.mark.parametrize("current", ["resolved", "closed"])
@pytest.mark.parametrize("target", ["open", "acknowledged", "investigating", "remediating"])
def test_resolved_and_closed_incidents_cannot_regress(use_repository, client, current, target):
    row = _row_for_status(current)
    repo = use_repository([row])

    response = _patch(client, row["id"], current, target)

    assert response.status_code == 409
    assert repo.rows[0]["status"] == current


# ---------------------------------------------------------------------
# Database error handling
# ---------------------------------------------------------------------


def test_successful_transition_actually_commits(use_repository, client):
    # Regression test for a real bug a PostgreSQL smoke test caught
    # during development: a route returning 200 without calling
    # commit() looks fine against the mocked repository (which has no
    # real transaction) but silently rolls back against the real
    # database once the session closes. See api/incidents.py's own
    # comment at the call site.
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "acknowledged")

    assert response.status_code == 200
    assert repo.commit_count == 1


def test_noop_transition_does_not_commit(use_repository, client):
    # The documented no-op path performs no write at all, so it must
    # not call commit() either.
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "open")

    assert response.status_code == 200
    assert repo.commit_count == 0


def test_rejected_transition_does_not_commit(use_repository, client):
    row = _row_for_status("open")
    repo = use_repository([row])

    response = _patch(client, row["id"], "open", "remediating")

    assert response.status_code == 409
    assert repo.commit_count == 0


def test_lifecycle_database_error_returns_503_not_leaking_secrets(use_repository, client):
    class _BrokenRepository:
        async def get_by_id(self, incident_id):
            raise OperationalError("SELECT ...", {}, Exception("connection refused, password=supersecret"))

        async def transition_incident_status(self, *args, **kwargs):
            raise OperationalError("UPDATE ...", {}, Exception("connection refused, password=supersecret"))

    app.dependency_overrides[get_incident_repository] = lambda: _BrokenRepository()

    response = _patch(client, uuid.uuid4(), "open", "acknowledged")

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "supersecret" not in response.text
