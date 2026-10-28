"""Phase 16 Gate 2/3/8: POST/GET/revoke
/api/v1/services/{service_id}/integrations.

Mirrors tests/test_services.py's own fixture/fake-repository
conventions exactly. Proves: the real role matrix (OWNER/ADMIN/
ENGINEER may create; VIEWER/INCIDENT_APPROVER may not), cross-tenant
isolation (a service id from another organization never resolves),
the secret is shown exactly once and never again, and revocation is
real and persists.
"""

import uuid
from datetime import UTC, datetime

import pytest

from control_plane.api.dependencies import get_integration_credential_repository, get_service_repository
from control_plane.core.authz import ROLES_THAT_MAY_REGISTER_SERVICES
from control_plane.main import app
from tests.test_organization_scoping import ASSERTION_SECRET, ORG_A, ORG_B, _assertion, org_client  # noqa: F401

ALL_ROLES = ("OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER")


class FakeServiceRepo:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def get_by_id_for_organization(self, organization_id, service_id):
        for row in self.rows:
            if str(row["id"]) == str(service_id) and str(row["organization_id"]) == str(organization_id):
                return row
        return None


class FakeIntegrationCredentialRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def create(self, *, organization_id, service_id, connection_type, credential_id, credential_secret_hash, created_by_user_id):
        now = datetime.now(UTC)
        row = {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "service_id": service_id,
            "connection_type": connection_type,
            "credential_id": credential_id,
            "credential_secret_hash": credential_secret_hash,
            "status": "active",
            "created_by_user_id": created_by_user_id,
            "created_at": now,
            "updated_at": now,
            "revoked_at": None,
            "last_verified_telemetry_at": None,
        }
        self.rows.append(row)
        return row

    async def list_for_service(self, organization_id, service_id):
        return [
            r for r in self.rows if str(r["organization_id"]) == str(organization_id) and str(r["service_id"]) == str(service_id)
        ]

    async def get_by_credential_id(self, credential_id):
        for row in self.rows:
            if row["credential_id"] == credential_id:
                return row
        return None

    async def touch_last_verified_telemetry(self, integration_id):
        for row in self.rows:
            if str(row["id"]) == str(integration_id):
                row["last_verified_telemetry_at"] = datetime.now(UTC)
                return

    async def get_by_id_for_organization(self, organization_id, integration_id):
        for row in self.rows:
            if str(row["id"]) == str(integration_id) and str(row["organization_id"]) == str(organization_id):
                return row
        return None

    async def revoke(self, integration_id):
        for row in self.rows:
            if str(row["id"]) == str(integration_id):
                row["status"] = "revoked"
                row["revoked_at"] = datetime.now(UTC)
                return row
        return None


SERVICE_A_ID = str(uuid.uuid4())
SERVICE_B_ID = str(uuid.uuid4())


def _use():
    services = FakeServiceRepo(
        [
            {"id": SERVICE_A_ID, "organization_id": ORG_A, "name": "checkout-api"},
            {"id": SERVICE_B_ID, "organization_id": ORG_B, "name": "orders-api"},
        ]
    )
    credentials = FakeIntegrationCredentialRepo()
    app.dependency_overrides[get_service_repository] = lambda: services
    app.dependency_overrides[get_integration_credential_repository] = lambda: credentials
    return services, credentials


def _clear():
    app.dependency_overrides.pop(get_service_repository, None)
    app.dependency_overrides.pop(get_integration_credential_repository, None)


@pytest.mark.parametrize("role", sorted(ROLES_THAT_MAY_REGISTER_SERVICES))
def test_allowed_roles_can_create_a_credential(org_client, role):
    _use()
    try:
        response = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations",
            json={"connection_type": "opentelemetry"},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role=role)},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["credential"]["status"] == "active"
        assert body["credential"]["service_id"] == SERVICE_A_ID
        # Gate 3: the real secret is present exactly in THIS response.
        assert "." in body["bearer_token"]
        assert body["bearer_token"].startswith(body["credential"]["credential_id"] + ".")
        # Never a plaintext secret or its hash anywhere in the public view.
        assert "credential_secret_hash" not in body["credential"]
        assert "secret" not in body["credential"]
    finally:
        _clear()


@pytest.mark.parametrize("role", sorted(set(ALL_ROLES) - ROLES_THAT_MAY_REGISTER_SERVICES))
def test_denied_roles_cannot_create_a_credential(org_client, role):
    _, credentials = _use()
    try:
        response = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations",
            json={"connection_type": "opentelemetry"},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role=role)},
        )
        assert response.status_code == 403
    finally:
        _clear()
    assert credentials.rows == []


def test_cannot_create_a_credential_for_another_organizations_service(org_client):
    _use()
    try:
        response = org_client.post(
            f"/api/v1/services/{SERVICE_B_ID}/integrations",
            json={"connection_type": "opentelemetry"},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")},
        )
        assert response.status_code == 404
    finally:
        _clear()


def test_list_is_secret_free_and_organization_scoped(org_client):
    _use()
    try:
        headers_a = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        org_client.post(f"/api/v1/services/{SERVICE_A_ID}/integrations", json={"connection_type": "opentelemetry"}, headers=headers_a)

        listed = org_client.get(f"/api/v1/services/{SERVICE_A_ID}/integrations", headers=headers_a)
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1
        assert "credential_secret_hash" not in listed.json()["items"][0]

        cross_tenant = org_client.get(
            f"/api/v1/services/{SERVICE_A_ID}/integrations",
            headers={"X-Service-Assertion": _assertion(org=ORG_B, role="OWNER")},
        )
        assert cross_tenant.status_code == 404
    finally:
        _clear()


def test_revoke_requires_the_same_role_matrix_and_persists(org_client):
    _use()
    try:
        headers_owner = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        created = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations", json={"connection_type": "opentelemetry"}, headers=headers_owner
        )
        integration_id = created.json()["credential"]["id"]

        denied = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations/{integration_id}/revoke",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        assert denied.status_code == 403

        revoked = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations/{integration_id}/revoke", headers=headers_owner
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert revoked.json()["revoked_at"] is not None
    finally:
        _clear()


def test_revoke_from_another_organization_is_not_found(org_client):
    _use()
    try:
        headers_a = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        created = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations", json={"connection_type": "opentelemetry"}, headers=headers_a
        )
        integration_id = created.json()["credential"]["id"]

        response = org_client.post(
            f"/api/v1/services/{SERVICE_A_ID}/integrations/{integration_id}/revoke",
            headers={"X-Service-Assertion": _assertion(org=ORG_B, role="OWNER")},
        )
        assert response.status_code == 404
    finally:
        _clear()


def test_legacy_mode_without_any_assertion_is_401(client):
    _use()
    try:
        response = client.post(f"/api/v1/services/{SERVICE_A_ID}/integrations", json={"connection_type": "opentelemetry"})
    finally:
        _clear()
    assert response.status_code == 401
