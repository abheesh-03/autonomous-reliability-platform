"""Phase 15: GET /api/v1/dashboard/summary.

Unit-level, in-memory fake repository -- same convention as
tests/conftest.py's own FakeIncidentRepository docstring explains: not
proof of real PostgreSQL aggregate-query behavior (that is
scripts/verify-control-plane.sh's own dashboard-summary section,
against the real database), but proof of this route's own response
shaping, tenant-id propagation, and zero-filled activity window logic.

Independent-review correction round, BLOCKER 1: this endpoint ALWAYS
requires a real, verified actor now (see api/dashboard.py's own
docstring) -- there is no longer a legacy, unauthenticated/unscoped
call shape at all. Every test below configures real assertion signing
(`assertion_signing_configured`, mirroring tests/test_services.py's own
fixture of the same name) and presents a real signed assertion, even
the ones that never enable organization-context ENFORCEMENT.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from control_plane.api.dependencies import get_dashboard_repository
from control_plane.core.config import ServiceAssertionSettings
from control_plane.main import app
from tests.test_organization_scoping import ASSERTION_SECRET, ORG_A, ORG_B, _assertion, org_client  # noqa: F401


class FakeDashboardRepository:
    """Records every organization_id each method was called with (so a
    test can assert the real actor's org was actually threaded
    through, never silently dropped), and returns small, deterministic
    canned rows otherwise."""

    def __init__(self, rows_by_org: dict[str | None, dict]) -> None:
        self.rows_by_org = rows_by_org
        self.calls: list[tuple[str, object]] = []

    def _rows(self, organization_id):
        key = str(organization_id) if organization_id is not None else None
        return self.rows_by_org.get(key, self.rows_by_org.get(None, {}))

    async def get_status_counts(self, organization_id):
        self.calls.append(("get_status_counts", organization_id))
        return self._rows(organization_id).get("status_counts", {})

    async def get_active_critical_count(self, organization_id):
        self.calls.append(("get_active_critical_count", organization_id))
        return self._rows(organization_id).get("active_critical", 0)

    async def get_pending_approvals_count(self, organization_id):
        self.calls.append(("get_pending_approvals_count", organization_id))
        return self._rows(organization_id).get("pending_approvals_count", 0)

    async def list_attention_incidents(self, organization_id, limit=8):
        self.calls.append(("list_attention_incidents", organization_id))
        return self._rows(organization_id).get("attention", [])[:limit]

    async def list_pending_approvals(self, organization_id, limit=8):
        self.calls.append(("list_pending_approvals", organization_id))
        return self._rows(organization_id).get("approvals", [])[:limit]

    async def get_daily_severity_activity(self, organization_id, since, until):
        self.calls.append(("get_daily_severity_activity", organization_id))
        return self._rows(organization_id).get("activity", [])

    async def list_recent_events(self, organization_id, limit=20):
        self.calls.append(("list_recent_events", organization_id))
        return self._rows(organization_id).get("events", [])[:limit]


def _use(rows_by_org: dict[str | None, dict]) -> FakeDashboardRepository:
    fake = FakeDashboardRepository(rows_by_org)
    app.dependency_overrides[get_dashboard_repository] = lambda: fake
    return fake


@pytest.fixture
def assertion_signing_configured(client):
    """Configures ONLY service-assertion signing -- organization-context
    ENFORCEMENT (app.state.organization_context_settings) is left at its
    real default (disabled), exactly matching this platform's own real
    local-development default. Mirrors tests/test_services.py's own
    fixture of the same name -- /api/v1/dashboard/summary now shares
    exactly the same "always require a real actor" contract as
    /api/v1/services."""
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
    """BLOCKER 1's own regression test, matching test_services.py's
    sibling exactly: a genuinely valid, web-console-signed assertion
    must not be rejected merely because the global enforcement flag
    happens to be disabled (this platform's own real local-development
    default)."""
    fake = _use({ORG_A: {"status_counts": {"open": 2}}})
    try:
        response = assertion_signing_configured.get(
            "/api/v1/dashboard/summary", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    assert response.status_code == 200
    assert response.json()["counts"]["open"] == 2
    assert all(str(org) == ORG_A for _, org in fake.calls)


def test_missing_assertion_is_401_even_with_enforcement_disabled(assertion_signing_configured):
    """No "legacy mode bypass" of any kind exists for this endpoint --
    the one deliberate exception to legacy mode's usual "organization
    context is simply not enforced" behavior, exactly like
    /api/v1/services."""
    _use({})
    try:
        response = assertion_signing_configured.get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)
    assert response.status_code == 401


def test_invalid_assertion_is_401(assertion_signing_configured):
    _use({})
    try:
        response = assertion_signing_configured.get(
            "/api/v1/dashboard/summary", headers={"X-Service-Assertion": "not-a-real-jwt"}
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)
    assert response.status_code == 401


def test_organization_a_sees_only_its_own_counts(org_client):
    fake = _use(
        {
            ORG_A: {"status_counts": {"open": 1}},
            ORG_B: {"status_counts": {"open": 99}},
        }
    )
    try:
        response = org_client.get(
            "/api/v1/dashboard/summary", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    assert response.status_code == 200
    assert response.json()["counts"]["open"] == 1
    assert fake.calls
    assert all(str(org) == ORG_A for _, org in fake.calls)


def test_organization_b_sees_only_its_own_counts(org_client):
    fake = _use(
        {
            ORG_A: {"status_counts": {"open": 1}},
            ORG_B: {"status_counts": {"open": 99}},
        }
    )
    try:
        response = org_client.get(
            "/api/v1/dashboard/summary", headers={"X-Service-Assertion": _assertion(org=ORG_B, role="VIEWER")}
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    assert response.status_code == 200
    assert response.json()["counts"]["open"] == 99
    assert fake.calls
    assert all(str(org) == ORG_B for _, org in fake.calls)


def test_legacy_configuration_does_not_bypass_authorization(org_client):
    """Disabling CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT changes
    nothing about this endpoint's own requirement for a real, verified
    actor -- `org_client` enables it, this test explicitly disables it
    again and proves the 401 still holds."""
    from control_plane.core.config import OrganizationContextSettings

    app.state.organization_context_settings = OrganizationContextSettings(enabled=False)
    _use({})
    try:
        response = org_client.get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)
    assert response.status_code == 401


def test_pending_approvals_count_is_a_real_count_not_the_bounded_lists_length(org_client):
    """BLOCKER 3 bug B's own regression test: the backend's
    `pending_approvals_count` must reflect EVERY pending proposal, even
    when there are more than the bounded display list's own `limit=8`
    -- never silently truncated to len(pending_approvals)."""
    approvals = [
        {
            "proposal_id": uuid.uuid4(),
            "incident_id": uuid.uuid4(),
            "agent_run_id": uuid.uuid4(),
            "incident_title": f"incident {i}",
            "incident_severity": "warning",
            "action_type": "restart_pod",
            "target": f"service-{i}",
            "proposed_at": datetime.now(UTC),
        }
        for i in range(8)
    ]
    fake = _use(
        {
            ORG_A: {
                "status_counts": {},
                # 12 REAL pending approvals exist, but the bounded
                # display list only ever returns 8 of them.
                "pending_approvals_count": 12,
                "approvals": approvals,
            }
        }
    )
    try:
        response = org_client.get(
            "/api/v1/dashboard/summary", headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    body = response.json()
    assert body["pending_approvals_count"] == 12
    assert len(body["pending_approvals"]) == 8
    assert fake.calls


def test_shape_and_zero_filled_activity_window(assertion_signing_configured):
    fake = _use({ORG_A: {"status_counts": {"open": 3, "resolved": 5}, "active_critical": 1}})
    try:
        response = assertion_signing_configured.get(
            "/api/v1/dashboard/summary?activity_days=3",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["open"] == 3
    assert body["counts"]["resolved"] == 5
    assert body["counts"]["acknowledged"] == 0
    assert body["counts"]["active_critical"] == 1
    assert body["pending_approvals_count"] == 0
    # No real activity rows were returned by the fake, but the window
    # is still fully, explicitly zero-filled -- never fabricated
    # nonzero data, but never simply absent either.
    assert len(body["activity"]) == 3
    assert all(point["critical"] == 0 and point["warning"] == 0 and point["info"] == 0 for point in body["activity"])
    assert body["attention_incidents"] == []
    assert body["pending_approvals"] == []
    assert body["recent_events"] == []
    assert fake.calls
    assert all(str(org) == ORG_A for _, org in fake.calls)


def test_real_activity_counts_are_bucketed_by_day_and_severity(assertion_signing_configured):
    today = datetime.now(UTC).date()
    fake = _use(
        {
            ORG_A: {
                "status_counts": {},
                "activity": [
                    {"day": datetime.combine(today, datetime.min.time(), tzinfo=UTC), "severity": "critical", "count": 2},
                    {"day": datetime.combine(today, datetime.min.time(), tzinfo=UTC), "severity": "warning", "count": 1},
                ],
            }
        }
    )
    try:
        response = assertion_signing_configured.get(
            "/api/v1/dashboard/summary?activity_days=1",
            headers={"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")},
        )
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)

    body = response.json()
    assert len(body["activity"]) == 1
    assert body["activity"][0]["critical"] == 2
    assert body["activity"][0]["warning"] == 1
    assert body["activity"][0]["info"] == 0


def test_activity_days_out_of_bounds_is_rejected(assertion_signing_configured):
    _use({ORG_A: {}})
    headers = {"X-Service-Assertion": _assertion(org=ORG_A, role="VIEWER")}
    try:
        response = assertion_signing_configured.get("/api/v1/dashboard/summary?activity_days=0", headers=headers)
        assert response.status_code == 422
        response = assertion_signing_configured.get("/api/v1/dashboard/summary?activity_days=9999", headers=headers)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_dashboard_repository, None)
