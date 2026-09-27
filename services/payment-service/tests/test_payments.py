import uuid

import pytest
from fastapi.testclient import TestClient

from payment_service.main import app

client = TestClient(app)


def test_authorize_payment_succeeds_with_valid_request():
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


def test_authorize_payment_rejects_zero_amount():
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": 0, "currency": "USD"},
    )

    assert response.status_code == 422


def test_authorize_payment_rejects_negative_amount():
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": -100, "currency": "USD"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "123"])
def test_authorize_payment_rejects_invalid_currency(currency):
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "chk_12345", "amount_cents": 2599, "currency": currency},
    )

    assert response.status_code == 422


def test_authorize_payment_rejects_empty_checkout_id():
    response = client.post(
        "/payments/authorize",
        json={"checkout_id": "", "amount_cents": 2599, "currency": "USD"},
    )

    assert response.status_code == 422
