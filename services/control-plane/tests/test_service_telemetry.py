"""Phase 16 Gate 5: GET /api/v1/services/{service_id}/telemetry-summary.

Proves the required connection-status state machine (NOT_CONFIGURED /
CONFIGURED_AWAITING_DATA / RECEIVING_TELEMETRY / STALE_DATA / REVOKED)
and that every number returned is a real, bounded, organization-scoped
aggregate -- never a client-suppliable value.
"""

import uuid
from datetime import UTC, datetime, timedelta

from control_plane.api.dependencies import (
    get_integration_credential_repository,
    get_service_repository,
    get_telemetry_repository,
)
from control_plane.main import app
from tests.test_integrations import FakeIntegrationCredentialRepo, FakeServiceRepo, SERVICE_A_ID
from tests.test_organization_scoping import ORG_A, ORG_B, _assertion, org_client  # noqa: F401
from tests.test_telemetry_ingest import FakeTelemetryRepository


def _use():
    services = FakeServiceRepo([{"id": SERVICE_A_ID, "organization_id": ORG_A, "name": "checkout-api"}])
    credentials = FakeIntegrationCredentialRepo()
    telemetry = FakeTelemetryRepository()
    app.dependency_overrides[get_service_repository] = lambda: services
    app.dependency_overrides[get_integration_credential_repository] = lambda: credentials
    app.dependency_overrides[get_telemetry_repository] = lambda: telemetry
    return services, credentials, telemetry


def _clear():
    app.dependency_overrides.pop(get_service_repository, None)
    app.dependency_overrides.pop(get_integration_credential_repository, None)
    app.dependency_overrides.pop(get_telemetry_repository, None)


def _headers(org=ORG_A, role="VIEWER"):
    return {"X-Service-Assertion": _assertion(org=org, role=role)}


def test_not_configured_with_no_credential_at_all(org_client):
    _use()
    try:
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "not_configured"
        assert body["request_count"] == 0
        assert body["error_rate"] is None
    finally:
        _clear()


def test_configured_awaiting_data_with_a_credential_but_no_telemetry_ever(org_client):
    _, credentials, _ = _use()
    try:
        credentials.rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": ORG_A,
                "service_id": SERVICE_A_ID,
                "status": "active",
            }
        )
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        assert response.json()["status"] == "configured_awaiting_data"
    finally:
        _clear()


def test_receiving_telemetry_with_recent_real_samples(org_client):
    _, credentials, telemetry = _use()
    try:
        credentials.rows.append({"id": uuid.uuid4(), "organization_id": ORG_A, "service_id": SERVICE_A_ID, "status": "active"})
        now = datetime.now(UTC)
        telemetry.rows.append(
            {
                "organization_id": ORG_A,
                "service_id": SERVICE_A_ID,
                "observed_at": now - timedelta(minutes=1),
                "request_count": 10,
                "is_error": False,
            }
        )
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        body = response.json()
        assert body["status"] == "receiving_telemetry"
        assert body["request_count"] == 10
        assert body["error_rate"] == 0.0
    finally:
        _clear()


def test_stale_data_when_last_telemetry_is_old(org_client):
    _, credentials, telemetry = _use()
    try:
        credentials.rows.append({"id": uuid.uuid4(), "organization_id": ORG_A, "service_id": SERVICE_A_ID, "status": "active"})
        telemetry.rows.append(
            {
                "organization_id": ORG_A,
                "service_id": SERVICE_A_ID,
                "observed_at": datetime.now(UTC) - timedelta(hours=2),
                "request_count": 10,
                "is_error": False,
            }
        )
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        assert response.json()["status"] == "stale_data"
    finally:
        _clear()


def test_revoked_when_every_credential_for_this_service_is_revoked(org_client):
    _, credentials, _ = _use()
    try:
        credentials.rows.append({"id": uuid.uuid4(), "organization_id": ORG_A, "service_id": SERVICE_A_ID, "status": "revoked"})
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        assert response.json()["status"] == "revoked"
    finally:
        _clear()


def test_missing_telemetry_is_never_reported_as_healthy_or_receiving(org_client):
    """Gate 5: 'A registered service is not automatically healthy.
    Missing telemetry is not proof of availability.'"""
    _use()
    try:
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        assert response.json()["status"] not in ("receiving_telemetry",)
    finally:
        _clear()


def test_cross_tenant_access_is_404(org_client):
    _use()
    try:
        response = org_client.get(
            f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers(org=ORG_B, role="VIEWER")
        )
    finally:
        _clear()
    assert response.status_code == 404


def test_error_rate_is_a_real_computed_fraction_not_client_suppliable(org_client):
    _, credentials, telemetry = _use()
    try:
        credentials.rows.append({"id": uuid.uuid4(), "organization_id": ORG_A, "service_id": SERVICE_A_ID, "status": "active"})
        now = datetime.now(UTC)
        telemetry.rows.append(
            {"organization_id": ORG_A, "service_id": SERVICE_A_ID, "observed_at": now, "request_count": 8, "is_error": False}
        )
        telemetry.rows.append(
            {"organization_id": ORG_A, "service_id": SERVICE_A_ID, "observed_at": now, "request_count": 2, "is_error": True}
        )
        response = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary", headers=_headers())
        body = response.json()
        assert body["request_count"] == 10
        assert body["error_count"] == 2
        assert body["error_rate"] == 0.2
    finally:
        _clear()


def test_legacy_mode_without_any_assertion_is_401(client):
    _use()
    try:
        response = client.get(f"/api/v1/services/{SERVICE_A_ID}/telemetry-summary")
    finally:
        _clear()
    assert response.status_code == 401
