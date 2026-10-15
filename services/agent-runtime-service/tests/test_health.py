"""Tests for api/health.py -- liveness never depends on the
checkpoint store; readiness honestly reflects whether it is usable."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime_service.api.health import router as health_router


class FakeCheckpointStore:
    def __init__(self, reachable: bool) -> None:
        self._reachable = reachable

    async def ping(self) -> bool:
        return self._reachable

    async def identity(self) -> dict | None:
        if not self._reachable:
            return None
        return {"current_user": "agent_runtime", "current_schema": "agent_runtime", "search_path": "agent_runtime"}


def _build_app(reachable: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    app.state.checkpoint_store = FakeCheckpointStore(reachable)
    return app


def test_liveness_never_touches_checkpoint_store():
    """/health/live doesn't even read app.state.checkpoint_store --
    confirmed by never setting it at all here."""
    app = FastAPI()
    app.include_router(health_router)
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "UP"}


def test_readiness_reports_ok_when_checkpoint_store_reachable():
    client = TestClient(_build_app(reachable=True))
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checkpoint_store"]["reachable"] is True
    assert body["checkpoint_store"]["identity"] == {
        "current_user": "agent_runtime",
        "current_schema": "agent_runtime",
        "search_path": "agent_runtime",
    }


def test_readiness_reports_503_when_checkpoint_store_unreachable():
    client = TestClient(_build_app(reachable=False))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not ready"
    assert body["checkpoint_store"]["reachable"] is False
    assert body["checkpoint_store"]["identity"] is None
