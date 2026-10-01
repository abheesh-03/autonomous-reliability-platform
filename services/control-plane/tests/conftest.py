"""Shared test fixtures.

Unit tests never touch a real database: `FakeIncidentRepository`
implements the same two methods as the real
`control_plane.repositories.incident_repository.IncidentRepository`
(`list_incidents`/`get_by_id`) purely in memory, and is injected via
FastAPI's `dependency_overrides` on the `get_incident_repository` seam
(control_plane/api/dependencies.py) — never by faking SQLAlchemy
internals. Real-database behavior (actual PostgreSQL connectivity,
actual column types/constraints, actual pagination/ordering against
real rows) is proven separately by scripts/verify-control-plane.sh
against the real running service; that is intentional, not a gap this
test suite tries to fill.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

# Engine construction (control_plane.db.engine.create_engine, invoked
# from the app's lifespan) never connects — it only needs these
# present to build a URL. Unit tests never touch a real database (see
# module docstring), so these dummy values are intentionally never
# expected to resolve to a reachable PostgreSQL; only
# scripts/verify-control-plane.sh exercises real connectivity. Using
# setdefault() so a real environment (e.g. these tests run inside the
# Compose network for some reason) is never silently overridden.
os.environ.setdefault("POSTGRES_HOST", "postgres.invalid")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_DB", "test_db")

import pytest
from fastapi.testclient import TestClient

from control_plane.api.dependencies import get_incident_repository
from control_plane.main import app


class FakeIncidentRepository:
    """In-memory stand-in with the same method signatures as the real
    repository. `rows` must already be in the exact order a caller
    expects `list_incidents` to apply filters/pagination over (tests
    construct them pre-sorted by last_seen_at DESC, id DESC, matching
    production ordering, so filtering/pagination logic here mirrors
    what a real SQL query would do)."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def list_incidents(self, *, status, severity, source, limit, offset):
        matched = [
            r
            for r in self.rows
            if (status is None or r["status"] == status)
            and (severity is None or r["severity"] == severity)
            and (source is None or r["source"] == source)
        ]
        total = len(matched)
        page = matched[offset : offset + limit]
        return page, total

    async def get_by_id(self, incident_id: uuid.UUID):
        for row in self.rows:
            if row["id"] == incident_id:
                return row
        return None


def make_incident_row(**overrides) -> dict:
    now = datetime.now(UTC)
    row = {
        "id": uuid.uuid4(),
        "source": "alertmanager",
        "source_fingerprint": f"fp-{uuid.uuid4()}",
        "title": "Sample incident",
        "description": None,
        "severity": "warning",
        "status": "open",
        "first_seen_at": now - timedelta(minutes=5),
        "last_seen_at": now,
        "resolved_at": None,
        "created_at": now - timedelta(minutes=5),
        "updated_at": now,
    }
    row.update(overrides)
    return row


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def use_repository(client):
    """Returns a function that installs a FakeIncidentRepository (built
    from the given rows) as the active dependency override."""

    def _use(rows: list[dict]) -> FakeIncidentRepository:
        fake = FakeIncidentRepository(rows)
        app.dependency_overrides[get_incident_repository] = lambda: fake
        return fake

    return _use
