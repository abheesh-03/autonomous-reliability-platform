from fastapi.testclient import TestClient

from payment_service.main import app

client = TestClient(app)


def test_health_returns_200_with_expected_body():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UP"
    assert body["service"] == "payment-service"
