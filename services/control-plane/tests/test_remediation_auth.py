"""Phase 8 §HUMAN APPROVAL CANNOT BE BYPASSED -- cross-token rejection
tests for the three new remediation endpoints' Bearer-token
dependencies. Pure request/response/auth-boundary testing, same
convention test_webhook.py/test_lifecycle.py already use: these never
reach the real repository (the auth dependency 401s before the route
body runs), so no real database and no dependency override is needed
at all for any of these -- a fresh, un-overridden `client` fixture is
sufficient, exactly like test_lifecycle.py's own
test_missing_lifecycle_token_returns_401_and_does_not_mutate.
"""

import uuid

import pytest

from control_plane.api.dependencies import get_remediation_repository
from control_plane.main import app
from tests.conftest import (
    LIFECYCLE_TOKEN,
    REMEDIATION_APPROVER_TOKEN,
    REMEDIATION_EXECUTOR_TOKEN,
    REMEDIATION_PROPOSAL_TOKEN,
    WEBHOOK_TOKEN,
)


class _EmptyRemediationRepository:
    """In-memory stand-in with no rows at all -- used only by this
    module's two unauthenticated-GET-404 sanity checks below, so they
    never need a real database connection (every other test in this
    module exercises a 401 short-circuit, which never reaches the
    repository at all)."""

    async def get_by_id(self, *args, **kwargs):
        return None

    async def get_events(self, *args, **kwargs):
        return [], 0


@pytest.fixture(autouse=True)
def _use_empty_remediation_repository(client):
    app.dependency_overrides[get_remediation_repository] = lambda: _EmptyRemediationRepository()
    yield
    app.dependency_overrides.pop(get_remediation_repository, None)

PROPOSAL_AUTH = {"Authorization": f"Bearer {REMEDIATION_PROPOSAL_TOKEN}"}
APPROVER_AUTH = {"Authorization": f"Bearer {REMEDIATION_APPROVER_TOKEN}"}
EXECUTOR_AUTH = {"Authorization": f"Bearer {REMEDIATION_EXECUTOR_TOKEN}"}

CREATE_BODY = {
    "incident_id": str(uuid.uuid4()),
    "agent_run_id": str(uuid.uuid4()),
    "idempotency_key": "phase8-proposal:test-run",
    "action_type": "clear_payment_authorization_fault",
    "target": "payment-service",
    "reason": "test",
}
DECISION_BODY = {"expected_status": "pending_approval", "decision": "approve"}
RESULT_BODY = {"outcome": "succeeded"}


def _random_proposal_path(suffix: str) -> str:
    return f"/{'internal' if 'execution' in suffix else 'api'}/v1/remediation-proposals/{uuid.uuid4()}{suffix}"


# ---------------------------------------------------------------------
# POST /internal/v1/remediation-proposals -- proposal token only
# ---------------------------------------------------------------------


def test_create_proposal_missing_token_returns_401(client):
    response = client.post("/internal/v1/remediation-proposals", json=CREATE_BODY)
    assert response.status_code == 401


def test_create_proposal_incorrect_token_returns_401(client):
    response = client.post(
        "/internal/v1/remediation-proposals",
        headers={"Authorization": "Bearer wrong-token"},
        json=CREATE_BODY,
    )
    assert response.status_code == 401


def test_create_proposal_rejects_approver_token(client):
    response = client.post("/internal/v1/remediation-proposals", headers=APPROVER_AUTH, json=CREATE_BODY)
    assert response.status_code == 401


def test_create_proposal_rejects_executor_token(client):
    response = client.post("/internal/v1/remediation-proposals", headers=EXECUTOR_AUTH, json=CREATE_BODY)
    assert response.status_code == 401


def test_create_proposal_rejects_webhook_token(client):
    response = client.post(
        "/internal/v1/remediation-proposals", headers={"Authorization": f"Bearer {WEBHOOK_TOKEN}"}, json=CREATE_BODY
    )
    assert response.status_code == 401


def test_create_proposal_rejects_lifecycle_token(client):
    response = client.post(
        "/internal/v1/remediation-proposals", headers={"Authorization": f"Bearer {LIFECYCLE_TOKEN}"}, json=CREATE_BODY
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------
# POST /api/v1/remediation-proposals/{id}/decision -- approver token only
# ---------------------------------------------------------------------


def test_decision_missing_token_returns_401(client):
    response = client.post(f"/api/v1/remediation-proposals/{uuid.uuid4()}/decision", json=DECISION_BODY)
    assert response.status_code == 401


def test_decision_rejects_proposal_token(client):
    response = client.post(
        f"/api/v1/remediation-proposals/{uuid.uuid4()}/decision", headers=PROPOSAL_AUTH, json=DECISION_BODY
    )
    assert response.status_code == 401


def test_decision_rejects_executor_token(client):
    response = client.post(
        f"/api/v1/remediation-proposals/{uuid.uuid4()}/decision", headers=EXECUTOR_AUTH, json=DECISION_BODY
    )
    assert response.status_code == 401


def test_decision_rejects_lifecycle_token(client):
    # The human/operator lifecycle token (incident status PATCH) must
    # NOT double as the remediation approver token either -- they
    # authorize two different kinds of human decisions and must stay
    # separate credentials.
    response = client.post(
        f"/api/v1/remediation-proposals/{uuid.uuid4()}/decision",
        headers={"Authorization": f"Bearer {LIFECYCLE_TOKEN}"},
        json=DECISION_BODY,
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------
# POST .../execution/start and .../execution/result -- executor token only
# ---------------------------------------------------------------------


def test_execution_start_missing_token_returns_401(client):
    response = client.post(f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/start", json={})
    assert response.status_code == 401


def test_execution_start_rejects_proposal_token(client):
    response = client.post(
        f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/start", headers=PROPOSAL_AUTH, json={}
    )
    assert response.status_code == 401


def test_execution_start_rejects_approver_token(client):
    response = client.post(
        f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/start", headers=APPROVER_AUTH, json={}
    )
    assert response.status_code == 401


def test_execution_result_missing_token_returns_401(client):
    response = client.post(f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/result", json=RESULT_BODY)
    assert response.status_code == 401


def test_execution_result_rejects_proposal_token(client):
    response = client.post(
        f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/result",
        headers=PROPOSAL_AUTH,
        json=RESULT_BODY,
    )
    assert response.status_code == 401


def test_execution_result_rejects_approver_token(client):
    response = client.post(
        f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/result",
        headers=APPROVER_AUTH,
        json=RESULT_BODY,
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------
# GET routes remain unauthenticated (read-only, same local-dev policy
# as every other GET in this service)
# ---------------------------------------------------------------------


def test_get_proposal_requires_no_token_and_404s_for_unknown_id(client):
    response = client.get(f"/api/v1/remediation-proposals/{uuid.uuid4()}")
    assert response.status_code == 404


def test_list_events_requires_no_token_and_404s_for_unknown_proposal(client):
    response = client.get(f"/api/v1/remediation-proposals/{uuid.uuid4()}/events")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# No secret leakage in any 401 body (same invariant
# test_webhook.py::test_no_secrets_in_auth_error_responses already
# enforces for the webhook/lifecycle tokens)
# ---------------------------------------------------------------------


def test_no_secrets_in_remediation_auth_error_responses(client):
    for path, headers, body in (
        ("/internal/v1/remediation-proposals", {"Authorization": "Bearer wrong"}, CREATE_BODY),
        (f"/api/v1/remediation-proposals/{uuid.uuid4()}/decision", {"Authorization": "Bearer wrong"}, DECISION_BODY),
        (
            f"/internal/v1/remediation-proposals/{uuid.uuid4()}/execution/start",
            {"Authorization": "Bearer wrong"},
            {},
        ),
    ):
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 401
        for secret in (
            REMEDIATION_PROPOSAL_TOKEN,
            REMEDIATION_APPROVER_TOKEN,
            REMEDIATION_EXECUTOR_TOKEN,
            WEBHOOK_TOKEN,
            LIFECYCLE_TOKEN,
        ):
            assert secret not in response.text
