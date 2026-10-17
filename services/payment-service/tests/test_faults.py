"""Phase 8 §PAYMENT FAULT TESTING -- the controlled authorization-fault
endpoints and their two separate, never-interchangeable Bearer tokens.
"""

from tests.conftest import INJECTION_TOKEN, REMEDIATION_TOKEN

INJECTION_AUTH = {"Authorization": f"Bearer {INJECTION_TOKEN}"}
REMEDIATION_AUTH = {"Authorization": f"Bearer {REMEDIATION_TOKEN}"}


def test_status_starts_inactive(client):
    response = client.get("/internal/v1/faults/authorization", headers=REMEDIATION_AUTH)
    assert response.status_code == 200
    assert response.json() == {"active": False}


def test_enable_requires_injection_token(client):
    assert client.post("/internal/v1/faults/authorization/enable").status_code == 401
    assert (
        client.post(
            "/internal/v1/faults/authorization/enable", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_enable_rejects_remediation_token(client):
    # The two tokens are never interchangeable -- the credential that
    # can RECOVER this service must never also be able to CREATE the
    # fault it is supposedly fixing.
    response = client.post("/internal/v1/faults/authorization/enable", headers=REMEDIATION_AUTH)
    assert response.status_code == 401


def test_clear_requires_remediation_token(client):
    assert client.post("/internal/v1/faults/authorization/clear").status_code == 401
    assert (
        client.post(
            "/internal/v1/faults/authorization/clear", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_clear_rejects_injection_token(client):
    response = client.post("/internal/v1/faults/authorization/clear", headers=INJECTION_AUTH)
    assert response.status_code == 401


def test_read_status_requires_remediation_token_not_injection_token(client):
    assert client.get("/internal/v1/faults/authorization").status_code == 401
    assert client.get("/internal/v1/faults/authorization", headers=INJECTION_AUTH).status_code == 401
    assert client.get("/internal/v1/faults/authorization", headers=REMEDIATION_AUTH).status_code == 200


def test_enable_then_status_reports_active(client):
    enable = client.post("/internal/v1/faults/authorization/enable", headers=INJECTION_AUTH)
    assert enable.status_code == 200
    assert enable.json() == {"active": True}

    status = client.get("/internal/v1/faults/authorization", headers=REMEDIATION_AUTH)
    assert status.json() == {"active": True}


def test_clear_is_idempotent(client):
    client.post("/internal/v1/faults/authorization/enable", headers=INJECTION_AUTH)

    first_clear = client.post("/internal/v1/faults/authorization/clear", headers=REMEDIATION_AUTH)
    assert first_clear.json() == {"active": False, "changed": True}

    second_clear = client.post("/internal/v1/faults/authorization/clear", headers=REMEDIATION_AUTH)
    assert second_clear.json() == {"active": False, "changed": False}


def test_clear_when_never_enabled_is_a_safe_no_op(client):
    response = client.post("/internal/v1/faults/authorization/clear", headers=REMEDIATION_AUTH)
    assert response.status_code == 200
    assert response.json() == {"active": False, "changed": False}


def test_enable_refuses_when_injection_disabled(client, monkeypatch):
    # PAYMENT_FAULT_INJECTION_ENABLED=false (the real documented
    # default) must make ENABLE refuse even with the correct token --
    # a correctly-held token alone is not enough; this mechanism must
    # be explicitly opted into.
    from fastapi.testclient import TestClient

    from payment_service.main import app

    monkeypatch.setenv("PAYMENT_FAULT_INJECTION_ENABLED", "false")
    with TestClient(app) as disabled_client:
        response = disabled_client.post("/internal/v1/faults/authorization/enable", headers=INJECTION_AUTH)
        assert response.status_code == 403

        # The fault must never have actually been set.
        status = disabled_client.get("/internal/v1/faults/authorization", headers=REMEDIATION_AUTH)
        assert status.json() == {"active": False}


def test_malformed_authorization_header_never_leaks_expected_token(client):
    response = client.post(
        "/internal/v1/faults/authorization/enable", headers={"Authorization": "NotBearer something"}
    )
    assert response.status_code == 401
    assert INJECTION_TOKEN not in response.text
    assert REMEDIATION_TOKEN not in response.text


def test_no_token_values_leak_in_any_fault_response(client):
    for path, headers in (
        ("/internal/v1/faults/authorization/enable", {"Authorization": "Bearer wrong"}),
        ("/internal/v1/faults/authorization/clear", {"Authorization": "Bearer wrong"}),
        ("/internal/v1/faults/authorization", {"Authorization": "Bearer wrong"}),
    ):
        response = client.get(path, headers=headers) if path.endswith("authorization") else client.post(
            path, headers=headers
        )
        assert response.status_code == 401
        assert INJECTION_TOKEN not in response.text
        assert REMEDIATION_TOKEN not in response.text


def test_colliding_injection_and_remediation_tokens_fail_closed_but_payments_still_work(monkeypatch):
    """Phase 8 correction round (finding #3): a runtime, fail-closed
    guard over scripts/init-remediation-secrets.sh's own distinctness
    guarantee -- if an operator hand-configures BOTH tokens to the SAME
    value, the credential meant only to RECOVER the fault must never
    also be able to CREATE it. Both endpoints must fail closed, but
    POST /payments/authorize (unrelated to either token) must remain
    completely unaffected."""
    from fastapi.testclient import TestClient

    from payment_service.main import app

    same_token = "this-value-is-shared-by-mistake"
    monkeypatch.setenv("PAYMENT_FAULT_INJECTION_TOKEN", same_token)
    monkeypatch.setenv("PAYMENT_REMEDIATION_TOKEN", same_token)
    monkeypatch.setenv("PAYMENT_FAULT_INJECTION_ENABLED", "true")
    colliding_auth = {"Authorization": f"Bearer {same_token}"}

    with TestClient(app) as colliding_client:
        enable_resp = colliding_client.post("/internal/v1/faults/authorization/enable", headers=colliding_auth)
        assert enable_resp.status_code == 401

        clear_resp = colliding_client.post("/internal/v1/faults/authorization/clear", headers=colliding_auth)
        assert clear_resp.status_code == 401

        status_resp = colliding_client.get("/internal/v1/faults/authorization", headers=colliding_auth)
        assert status_resp.status_code == 401

        # Never logs/returns the actual (shared) token value.
        assert same_token not in enable_resp.text
        assert same_token not in clear_resp.text
        assert same_token not in status_resp.text

        # Normal payment behavior is completely unaffected -- the
        # fault was never (and could never be) enabled.
        authorize_resp = colliding_client.post(
            "/payments/authorize",
            json={"checkout_id": "checkout-1", "amount_cents": 500, "currency": "USD"},
        )
        assert authorize_resp.status_code == 200


def test_fault_control_endpoints_accept_no_extra_fields():
    # Phase 8 §PAYMENT INTERNAL CONTROL ENDPOINTS: "one boolean fault
    # mode only -- never arbitrary delays, status codes, or exception
    # injection". There is no request body schema for enable/clear at
    # all (both take only the Authorization header) -- confirmed by
    # inspecting the route definitions directly rather than merely
    # asserting behavior, so a future accidental body-field addition
    # would be caught here.
    from payment_service.api.faults import clear_authorization_fault, enable_authorization_fault

    for fn in (enable_authorization_fault, clear_authorization_fault):
        params = set(fn.__annotations__) - {"return"}
        assert params == {"request"}
