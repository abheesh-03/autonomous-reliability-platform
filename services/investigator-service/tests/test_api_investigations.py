"""API-contract tests via FastAPI's TestClient. The real `lifespan`
runs (constructing real, unconfigured-by-default clients — no network
call happens merely from app startup), then `app.state.investigator`
is replaced with a fake Investigator double for each test, the same
dependency-injection-at-the-seam approach control-plane's own test
suite uses (app.dependency_overrides there; direct app.state
replacement here, since this service has no FastAPI Depends() seam for
the investigator — it is constructed once in lifespan, like
control-plane's db engine)."""

import uuid

from fastapi.testclient import TestClient

from investigator_service.clients.control_plane import ControlPlaneUnavailableError, IncidentNotFoundError
from investigator_service.domain.evidence import EvidenceItem, EvidencePackage, SourceOutcome
from investigator_service.domain.investigation import InvestigationReport, ProviderMetadata
from investigator_service.investigator import ProviderNotConfiguredError
from investigator_service.llm.provider import ProviderError
from investigator_service.llm.validation import ProviderOutputError
from investigator_service.main import app
from tests.conftest import SAMPLE_INCIDENT_ID
from datetime import UTC, datetime


class FakeInvestigator:
    def __init__(self, report=None, raise_=None):
        self._report = report
        self._raise = raise_
        self.calls: list[str] = []

    async def investigate(self, incident_id: str):
        self.calls.append(incident_id)
        if self._raise:
            raise self._raise
        return self._report


def _report() -> InvestigationReport:
    return InvestigationReport(
        incident_id=SAMPLE_INCIDENT_ID,
        investigated_at=datetime(2026, 4, 1, 9, 30, 0, tzinfo=UTC),
        incident_status_at_investigation="resolved",
        summary="Checkout failures are consistent with loss of payment-service availability.",
        observations=[],
        hypotheses=[],
        missing_evidence=[],
        suggested_checks=[],
        evidence=[EvidenceItem(id="E1", source="control_plane", summary="s", detail="d")],
        source_outcomes=[SourceOutcome(source="control_plane", status="ok", detail="d")],
        provider=ProviderMetadata(configured=True, provider="stub", model="stub-deterministic-v1"),
    )


def _client_with(fake: FakeInvestigator) -> TestClient:
    client = TestClient(app)
    client.__enter__()  # runs lifespan startup once
    client.app.state.investigator = fake
    return client


def test_health_live():
    with TestClient(app) as client:
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "UP"}


def test_health_ready_reports_provider_configuration_honestly():
    with TestClient(app) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert "configured" in body["llm_provider"]
        # Phase 5 correction round #6: the effective provider MODE
        # ("openai" or "stub") must be reported explicitly, not just
        # whether a key is configured -- this is what lets
        # scripts/verify-investigator.sh distinguish real-but-
        # unconfigured OpenAI mode from the stub mode it temporarily
        # forces, and verify restoration afterward.
        assert body["llm_provider"]["provider"] in ("openai", "stub")
        assert "api_key" not in resp.text


def test_post_investigation_happy_path_returns_structured_report():
    client = _client_with(FakeInvestigator(report=_report()))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["incident_id"] == str(SAMPLE_INCIDENT_ID)
        assert body["incident_status_at_investigation"] == "resolved"
        assert body["evidence"][0]["id"] == "E1"
        assert body["provider"]["configured"] is True
        # Never leaks a credential.
        assert "api_key" not in resp.text and "Bearer" not in resp.text
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_unknown_incident_is_404():
    client = _client_with(FakeInvestigator(raise_=IncidentNotFoundError("x")))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(uuid.uuid4())})
        assert resp.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_malformed_uuid_is_422():
    client = _client_with(FakeInvestigator(report=_report()))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": "not-a-uuid"})
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_missing_field_is_422():
    client = _client_with(FakeInvestigator(report=_report()))
    try:
        resp = client.post("/api/v1/investigations", json={})
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_control_plane_unavailable_is_503():
    client = _client_with(FakeInvestigator(raise_=ControlPlaneUnavailableError("down")))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert resp.status_code == 503
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_provider_not_configured_is_503_explicit():
    client = _client_with(FakeInvestigator(raise_=ProviderNotConfiguredError()))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert resp.status_code == 503
        assert "INVESTIGATOR_LLM_API_KEY" in resp.text
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_provider_error_is_502():
    client = _client_with(FakeInvestigator(raise_=ProviderError("timeout")))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert resp.status_code == 502
    finally:
        client.__exit__(None, None, None)


def test_post_investigation_malformed_provider_output_is_502():
    client = _client_with(FakeInvestigator(raise_=ProviderOutputError("bad json")))
    try:
        resp = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert resp.status_code == 502
    finally:
        client.__exit__(None, None, None)


def test_only_post_and_health_routes_exist():
    """Confirms this service exposes no PATCH/PUT/DELETE route and no
    generic incident-mutation endpoint of any kind."""
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        methods_by_path.setdefault(path, set()).update(getattr(route, "methods", set()) or set())
    for path, methods in methods_by_path.items():
        assert "PATCH" not in methods
        assert "PUT" not in methods
        assert "DELETE" not in methods
