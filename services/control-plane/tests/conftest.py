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
# Phase 3C: a deterministic, known-in-tests Bearer token so
# test_webhook.py can exercise both the "correct token" and "incorrect
# token" paths without depending on whatever a real local .env happens
# to contain.
os.environ.setdefault("CONTROL_PLANE_WEBHOOK_TOKEN", "test-webhook-token")

# Exported so test_webhook.py can build a correct `Authorization:
# Bearer <token>` header without hard-coding the literal value in two
# places; always reflects whatever is actually in the environment
# (the setdefault() above, or a real value if one was already set).
WEBHOOK_TOKEN = os.environ["CONTROL_PLANE_WEBHOOK_TOKEN"]

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
    what a real SQL query would do).

    `upsert_firing_incident`/`commit` exist so the same fixture can
    back Phase 3C's webhook route in unit tests too — the in-memory
    dedup logic here is a reasonable approximation of the real
    PostgreSQL partial-unique-index upsert
    (repositories/incident_repository.py), useful for exercising
    ingestion/service.py's and api/webhook.py's own logic in isolation,
    but it is NOT proof of real atomic/concurrent database behavior;
    that proof is scripts/verify-webhook-ingestion.sh against the real
    database (see that script's and this module's own docstrings)."""

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

    async def upsert_firing_incident(
        self, *, source, source_fingerprint, title, description, severity, first_seen_at, last_seen_at
    ):
        for row in self.rows:
            if (
                row["source"] == source
                and row["source_fingerprint"] == source_fingerprint
                and row["status"] not in ("resolved", "closed")
            ):
                row["title"] = title
                row["description"] = description
                row["severity"] = severity
                row["last_seen_at"] = max(row["last_seen_at"], last_seen_at)
                row["updated_at"] = datetime.now(UTC)
                return row["id"], False

        new_id = uuid.uuid4()
        now = datetime.now(UTC)
        self.rows.append(
            {
                "id": new_id,
                "source": source,
                "source_fingerprint": source_fingerprint,
                "title": title,
                "description": description,
                "severity": severity,
                "status": "open",
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "resolved_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return new_id, True

    async def commit(self) -> None:
        # No real session/transaction behind this fake — nothing to do.
        pass


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
