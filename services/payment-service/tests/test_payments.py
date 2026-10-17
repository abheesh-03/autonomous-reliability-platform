import uuid

import pytest


def test_authorize_payment_succeeds_with_valid_request(client):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": 2599, "currency": "USD"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_id"] == "chk_12345"
    assert body["amount_cents"] == 2599
    assert body["currency"] == "USD"
    assert body["status"] == "AUTHORIZED"
    assert "payment_id" in body
    uuid.UUID(body["payment_id"])  # raises ValueError if not a valid UUID


def test_authorize_payment_rejects_zero_amount(client):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": 0, "currency": "USD"},
    )

    assert response.status_code == 422


def test_authorize_payment_rejects_negative_amount(client):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": -100, "currency": "USD"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "123"])
def test_authorize_payment_rejects_invalid_currency(client, currency):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": 2599, "currency": currency},
    )

    assert response.status_code == 422


def test_authorize_payment_rejects_empty_checkout_id(client):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "", "amount_cents": 2599, "currency": "USD"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------
# Phase 8: the controlled authorization fault, as observed through the
# real public endpoint checkout-service actually calls. test_faults.py
# covers the internal fault-control endpoints themselves in full; this
# module only proves authorize()'s own two behaviors are wired to that
# shared state correctly.
# ---------------------------------------------------------------------


def test_authorize_payment_unaffected_when_fault_never_enabled(client):
    # Default state for every test in this module (each gets a FRESH
    # AuthorizationFaultState via the `client` fixture's own lifespan)
    # is inactive -- normal behavior is completely unchanged.
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_fault_off", "amount_cents": 500, "currency": "USD"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "AUTHORIZED"


def test_authorize_payment_fails_deterministically_while_fault_active(client):
    from tests.conftest import INJECTION_TOKEN

    enable = client.post(
        "/internal/v1/faults/authorization/enable", headers={"Authorization": f"Bearer {INJECTION_TOKEN}"}
    )
    assert enable.status_code == 200

    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_fault_on", "amount_cents": 500, "currency": "USD"},
    )
    # Any non-2xx reproduces checkout-service's real downstream_failure
    # path (confirmed directly against PaymentClient's source -- see
    # api/payments.py's own comment); 502 is this service's own chosen,
    # fixed, documented fault status.
    assert response.status_code == 502
    assert response.json()["detail"] == "authorization_fault_active"


def test_authorize_payment_recovers_after_fault_cleared(client):
    from tests.conftest import INJECTION_TOKEN, REMEDIATION_TOKEN

    client.post(
        "/internal/v1/faults/authorization/enable", headers={"Authorization": f"Bearer {INJECTION_TOKEN}"}
    )
    client.post(
        "/internal/v1/faults/authorization/clear", headers={"Authorization": f"Bearer {REMEDIATION_TOKEN}"}
    )

    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_recovered", "amount_cents": 500, "currency": "USD"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "AUTHORIZED"
