"""Phase 14 Gate 8/10: tenant-isolation and RBAC negative controls for
the agent-run lifecycle API, with CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
explicitly enabled. Mirrors control-plane's own
tests/test_organization_scoping.py -- two distinct organizations,
crafted-but-correctly-signed service assertions, and a real compiled
graph (InMemorySaver) so a run really is created/seeded/resumed, never
mocked at the graph level.

"Agent run IDs and checkpoint thread IDs are not authorization
credentials" (Gate 8) is the exact property every cross-tenant test
here exercises: knowing a real, valid run_id from organization B must
never let organization A read or resume it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent_runtime_service.api.agent_runs import router as agent_runs_router
from agent_runtime_service.config import OrganizationContextSettings, RuntimeBounds, ServiceAssertionSettings
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import incident_json, investigation_report_json

ASSERTION_SECRET = "test-agent-runtime-org-scoping-secret"
ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)

INCIDENT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
INCIDENT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _assertion(*, org: str, role: str = "VIEWER", aud: str = "agent-runtime-service") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "user-1",
            "org": org,
            "role": role,
            "iss": "web-console",
            "aud": aud,
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        ASSERTION_SECRET,
        algorithm="HS256",
    )


class TwoTenantControlPlaneClient:
    """Resolves each incident to its own organization -- the SAME real
    pattern authz.py's `_require_tenant_access` relies on: this
    service never stores org ownership itself, it always asks
    control-plane."""

    async def get_incident(self, incident_id):
        org = ORG_A if str(incident_id) == str(INCIDENT_A) else ORG_B
        return IncidentSnapshot.model_validate(incident_json(incident_id=uuid.UUID(str(incident_id)), organization_id=org))


class FakeInvestigatorClient:
    async def investigate(self, incident_id):
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(str(incident_id))))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agent_runs_router)
    control_plane = TwoTenantControlPlaneClient()
    graph = compile_graph(control_plane, FakeInvestigatorClient(), BOUNDS, InMemorySaver())
    app.state.graph = graph
    app.state.runtime_bounds = BOUNDS
    app.state.control_plane_client = control_plane
    app.state.organization_context_settings = OrganizationContextSettings(enabled=True)
    app.state.service_assertion_settings = ServiceAssertionSettings(
        secret=ASSERTION_SECRET, issuer="web-console", audience="agent-runtime-service", max_clock_skew_seconds=5, control_plane_audience="control-plane", investigator_audience="investigator-service")
    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


def test_viewer_cannot_create_a_run_for_any_incident(client):
    token = _assertion(org=ORG_A, role="VIEWER")
    response = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token},
        json={"incident_id": str(INCIDENT_A)},
    )
    assert response.status_code == 403


def test_engineer_cannot_create_a_run_for_another_organizations_incident(client):
    token = _assertion(org=ORG_A, role="ENGINEER")
    response = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token},
        json={"incident_id": str(INCIDENT_B)},
    )
    assert response.status_code == 404  # tenant-isolation 404, never 403


def test_engineer_can_create_a_run_for_their_own_organizations_incident(client):
    token = _assertion(org=ORG_A, role="ENGINEER")
    response = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token},
        json={"incident_id": str(INCIDENT_A)},
    )
    assert response.status_code == 201


def test_org_b_cannot_read_a_run_id_known_from_org_a(client):
    token_a = _assertion(org=ORG_A, role="ENGINEER")
    created = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token_a},
        json={"incident_id": str(INCIDENT_A)},
    )
    run_id = created.json()["run_id"]

    token_b = _assertion(org=ORG_B, role="VIEWER")
    response = client.get(f"/api/v1/agent-runs/{run_id}", headers={"X-Service-Assertion": token_b})
    assert response.status_code == 404


def test_org_a_can_read_its_own_run(client):
    token_a = _assertion(org=ORG_A, role="ENGINEER")
    created = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token_a},
        json={"incident_id": str(INCIDENT_A)},
    )
    run_id = created.json()["run_id"]

    response = client.get(f"/api/v1/agent-runs/{run_id}", headers={"X-Service-Assertion": token_a})
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id


def test_org_b_cannot_read_run_history_for_a_run_known_from_org_a(client):
    token_a = _assertion(org=ORG_A, role="ENGINEER")
    created = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token_a},
        json={"incident_id": str(INCIDENT_A)},
    )
    run_id = created.json()["run_id"]

    token_b = _assertion(org=ORG_B, role="VIEWER")
    response = client.get(f"/api/v1/agent-runs/{run_id}/history", headers={"X-Service-Assertion": token_b})
    assert response.status_code == 404


def test_org_b_cannot_resume_a_run_known_from_org_a(client):
    token_a = _assertion(org=ORG_A, role="ENGINEER")
    created = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token_a},
        json={"incident_id": str(INCIDENT_A)},
    )
    run_id = created.json()["run_id"]

    token_b = _assertion(org=ORG_B, role="ENGINEER")
    response = client.post(f"/api/v1/agent-runs/{run_id}/resume", headers={"X-Service-Assertion": token_b})
    assert response.status_code == 404


def test_viewer_cannot_resume_even_their_own_organizations_run(client):
    token_a_engineer = _assertion(org=ORG_A, role="ENGINEER")
    created = client.post(
        "/api/v1/agent-runs",
        headers={"X-Service-Assertion": token_a_engineer},
        json={"incident_id": str(INCIDENT_A)},
    )
    run_id = created.json()["run_id"]

    token_a_viewer = _assertion(org=ORG_A, role="VIEWER")
    response = client.post(f"/api/v1/agent-runs/{run_id}/resume", headers={"X-Service-Assertion": token_a_viewer})
    assert response.status_code == 403


def test_missing_assertion_is_rejected_when_enforcement_is_on(client):
    response = client.post("/api/v1/agent-runs", json={"incident_id": str(INCIDENT_A)})
    assert response.status_code == 401
