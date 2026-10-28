"""Phase 15 Gate 7: GET/POST /api/v1/services.

Unlike every other read endpoint in this service, these two routes
ALWAYS require a real, verified actor -- even in legacy/default mode
(CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT disabled). This module
proves that explicitly, in addition to the real cross-tenant isolation,
duplicate-name conflict, role-matrix (independent-review correction
round, BLOCKER 2), and pagination (BLOCKER 4) behavior.
"""

import uuid
from datetime import UTC, datetime

import pytest

from control_plane.api.dependencies import get_service_repository
from control_plane.core.authz import ROLES_THAT_MAY_REGISTER_SERVICES
from control_plane.core.config import ServiceAssertionSettings
from control_plane.main import app
from control_plane.repositories.service_repository import ServiceAlreadyExistsError
from tests.test_organization_scoping import ASSERTION_SECRET, ORG_A, ORG_B, _assertion, org_client  # noqa: F401

ALL_ROLES = ("OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER")


class FakeServiceRepository:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def list_services(self, organization_id, *, limit: int, offset: int):
        matched = [r for r in self.rows if str(r["organization_id"]) == str(organization_id)]
        matched.sort(key=lambda r: (r["created_at"], str(r["id"])), reverse=True)
        total = len(matched)
        return matched[offset : offset + limit], total

    async def create_service(self, *, organization_id, name, kind, language, description, created_by_user_id):
        for row in self.rows:
            if str(row["organization_id"]) == str(organization_id) and row["name"] == name:
                raise ServiceAlreadyExistsError(name)
        now = datetime.now(UTC)
        row = {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "name": name,
            "kind": kind,
            "language": language,
            "description": description,
            "created_by_user_id": created_by_user_id,
            "created_at": now,
            "updated_at": now,
        }
        self.rows.append(row)
        return row


def _use() -> FakeServiceRepository:
    fake = FakeServiceRepository()
    app.dependency_overrides[get_service_repository] = lambda: fake
    return fake


@pytest.fixture
def assertion_signing_configured(client):
    """Configures ONLY service-assertion signing -- organization-context
    ENFORCEMENT (app.state.organization_context_settings) is left at
    its real default (disabled), exactly matching this platform's own
    actual local-development default. Regression coverage for a real
    bug: require_actor_context used to depend on get_actor_context,
    whose own first line returns None unconditionally whenever that
    enforcement flag is disabled -- so a real, genuinely valid,
    web-console-signed assertion was being rejected with 401 on every
    default-configuration deployment, never actually reaching
    signature verification at all. Found by inspecting the live dev
    stack's own real Services page, not by a lower-level unit test."""
    previous = app.state.service_assertion_settings
    app.state.service_assertion_settings = ServiceAssertionSettings(
        secret=ASSERTION_SECRET,
        trusted_issuers=frozenset({"web-console"}),
        audience="control-plane",
        max_clock_skew_seconds=5,
    )
    yield client
    app.state.service_assertion_settings = previous


def test_a_real_valid_assertion_succeeds_even_with_organization_context_enforcement_disabled(
    assertion_signing_configured,
):
    fake = _use()
    try:
        response = assertion_signing_configured.get(
            "/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_legacy_mode_without_any_assertion_is_still_401(client):
    """The one deliberate exception to legacy mode's usual
    "organization context is simply not enforced" behavior -- this
    brand-new resource has no unscoped precedent to preserve."""
    _use()
    try:
        response = client.get("/api/v1/services")
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
    assert response.status_code == 401


def test_create_then_list_round_trips_in_secure_mode(org_client):
    fake = _use()
    try:
        created = org_client.post(
            "/api/v1/services",
            json={"name": "checkout-api", "kind": "rest_api", "language": "Java", "description": "Order intake"},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")},
        )
        assert created.status_code == 201
        assert created.json()["name"] == "checkout-api"
        assert created.json()["created_by_user_id"] == "user-1"

        listed = org_client.get(
            "/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["name"] == "checkout-api"
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_cross_tenant_isolation_org_b_never_sees_org_as_service(org_client):
    fake = _use()
    try:
        org_client.post(
            "/api/v1/services",
            json={"name": "org-a-only-service", "kind": "database", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")},
        )
        response = org_client.get(
            "/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_B, role="OWNER")}
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_duplicate_name_within_the_same_organization_is_a_conflict(org_client):
    fake = _use()
    try:
        headers = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        body = {"name": "dup", "kind": "microservice", "language": None, "description": None}
        first = org_client.post("/api/v1/services", json=body, headers=headers)
        assert first.status_code == 201
        second = org_client.post("/api/v1/services", json=body, headers=headers)
        assert second.status_code == 409
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_invalid_kind_is_rejected(org_client):
    _use()
    try:
        response = org_client.post(
            "/api/v1/services",
            json={"name": "x", "kind": "not-a-real-kind", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


# -- Independent-review correction round, BLOCKER 2: service
# registration role matrix. Registering a service is an organization
# MUTATION, not a read -- only OWNER/ADMIN/ENGINEER may do it. --


@pytest.mark.parametrize("role", sorted(ROLES_THAT_MAY_REGISTER_SERVICES))
def test_allowed_roles_can_register_a_service(org_client, role):
    _use()
    try:
        response = org_client.post(
            "/api/v1/services",
            json={"name": f"svc-{role.lower()}", "kind": "other", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role=role)},
        )
        assert response.status_code == 201, response.text
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


@pytest.mark.parametrize("role", sorted(set(ALL_ROLES) - ROLES_THAT_MAY_REGISTER_SERVICES))
def test_denied_roles_cannot_register_a_service(org_client, role):
    """VIEWER is a real, read-only role -- it must not be able to
    mutate the organization's service catalog. INCIDENT_APPROVER's
    entire purpose is deciding remediation proposals (Gate 3), not
    general catalog administration -- it is deliberately NOT granted
    this permission without an explicit, separate product decision."""
    fake = _use()
    try:
        response = org_client.post(
            "/api/v1/services",
            json={"name": f"svc-{role.lower()}", "kind": "other", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role=role)},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
    # The denial happened BEFORE any write -- not merely a response
    # code, a real absence of a mutation.
    assert fake.rows == []


def test_viewer_cannot_register_but_can_still_list(org_client):
    """Confirms the role gate applies ONLY to the mutation, not the
    existing read policy -- every member, including VIEWER, may still
    list the organization's registered services."""
    _use()
    try:
        denied = org_client.post(
            "/api/v1/services",
            json={"name": "viewer-attempt", "kind": "other", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        assert denied.status_code == 403

        listed = org_client.get(
            "/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
        assert listed.status_code == 200
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_denied_registration_still_enforces_cross_tenant_isolation(org_client):
    """A VIEWER in Org B attempting to register a service is denied by
    role -- not accidentally let through because of some interaction
    with tenant scoping."""
    _use()
    try:
        response = org_client.post(
            "/api/v1/services",
            json={"name": "cross-tenant-attempt", "kind": "other", "language": None, "description": None},
            headers={"X-Service-Assertion": _assertion(org=ORG_B, role="VIEWER")},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


# -- Independent-review correction round, BLOCKER 4: real server-side
# pagination. --


def test_pagination_returns_a_real_total_and_a_stable_bounded_page(org_client):
    fake = _use()
    try:
        headers = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        for i in range(25):
            org_client.post(
                "/api/v1/services",
                json={"name": f"service-{i:02d}", "kind": "other", "language": None, "description": None},
                headers=headers,
            )

        page1 = org_client.get(
            "/api/v1/services?limit=10&offset=0",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        assert page1.status_code == 200
        body1 = page1.json()
        assert body1["total"] == 25
        assert body1["limit"] == 10
        assert body1["offset"] == 0
        assert len(body1["items"]) == 10

        page2 = org_client.get(
            "/api/v1/services?limit=10&offset=10",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        body2 = page2.json()
        assert len(body2["items"]) == 10

        page3 = org_client.get(
            "/api/v1/services?limit=10&offset=20",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        body3 = page3.json()
        assert len(body3["items"]) == 5

        # Stable, deterministic ordering: no item appears on more than
        # one page, and every one of the 25 created items is accounted
        # for across exactly the three pages above.
        all_ids = [item["id"] for item in body1["items"] + body2["items"] + body3["items"]]
        assert len(all_ids) == len(set(all_ids)) == 25
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_pagination_defaults_when_no_query_params_given(org_client):
    _use()
    try:
        response = org_client.get(
            "/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
        body = response.json()
        assert body["limit"] == 20
        assert body["offset"] == 0
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_pagination_rejects_invalid_inputs(org_client, query):
    _use()
    try:
        response = org_client.get(
            f"/api/v1/services?{query}", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
    assert response.status_code == 422


def test_two_organizations_with_the_same_service_name_do_not_collide(org_client):
    """UNIQUE(organization_id, name) is scoped per organization -- the
    SAME name in two different organizations is not a conflict, and
    each organization's own paginated list sees only its own row."""
    _use()
    try:
        headers_a = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        headers_b = {"X-Service-Assertion": _assertion(org=ORG_B, role="OWNER")}
        body = {"name": "shared-name", "kind": "other", "language": None, "description": None}

        created_a = org_client.post("/api/v1/services", json=body, headers=headers_a)
        assert created_a.status_code == 201
        created_b = org_client.post("/api/v1/services", json=body, headers=headers_b)
        assert created_b.status_code == 201

        list_a = org_client.get("/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")})
        list_b = org_client.get("/api/v1/services", headers={"X-Service-Assertion": _assertion(org=ORG_B, role="VIEWER")})
        assert list_a.json()["total"] == 1
        assert list_b.json()["total"] == 1
        assert list_a.json()["items"][0]["id"] != list_b.json()["items"][0]["id"]
    finally:
        app.dependency_overrides.pop(get_service_repository, None)


def test_pagination_never_leaks_another_organizations_rows_into_a_page(org_client):
    fake = _use()
    try:
        headers_a = {"X-Service-Assertion": _assertion(org=ORG_A, role="OWNER")}
        headers_b = {"X-Service-Assertion": _assertion(org=ORG_B, role="OWNER")}
        for i in range(5):
            org_client.post(
                "/api/v1/services",
                json={"name": f"a-{i}", "kind": "other", "language": None, "description": None},
                headers=headers_a,
            )
        for i in range(5):
            org_client.post(
                "/api/v1/services",
                json={"name": f"b-{i}", "kind": "other", "language": None, "description": None},
                headers=headers_b,
            )

        response = org_client.get(
            "/api/v1/services?limit=100&offset=0",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
        body = response.json()
        assert body["total"] == 5
        assert all(item["name"].startswith("a-") for item in body["items"])
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
