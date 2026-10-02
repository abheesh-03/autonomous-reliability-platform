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
# Phase 3D: a SEPARATE deterministic, known-in-tests Bearer token for
# the lifecycle endpoint — deliberately a different literal value from
# the webhook token above, so test_lifecycle.py can assert the two are
# not interchangeable (using one where the other is expected must
# still 401).
os.environ.setdefault("CONTROL_PLANE_LIFECYCLE_TOKEN", "test-lifecycle-token")

# Exported so test_webhook.py/test_lifecycle.py can build a correct
# `Authorization: Bearer <token>` header without hard-coding the
# literal value in multiple places; always reflects whatever is
# actually in the environment (the setdefault() calls above, or a real
# value if one was already set).
WEBHOOK_TOKEN = os.environ["CONTROL_PLANE_WEBHOOK_TOKEN"]
LIFECYCLE_TOKEN = os.environ["CONTROL_PLANE_LIFECYCLE_TOKEN"]

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
        # Tracked (not just a pass-through no-op) so a unit test can
        # catch a regression of the real commit-after-successful-write
        # bug a real-PostgreSQL smoke test found during Phase 3D
        # development: a route that returns 200 without ever calling
        # commit() looks correct against this fake (which has no real
        # transaction to roll back) but silently discards the write
        # against the real database once the session closes.
        self.commit_count = 0
        # Phase 3E: in-memory audit trail, appended to by the same
        # three mutation methods the real repository writes it from
        # (upsert_firing_incident, transition_incident_status,
        # resolve_active_incident_for_fingerprint) — never by a
        # separate call a test has to remember to make. This fake
        # cannot model real transactional atomicity (there is no real
        # transaction here to roll back) — that proof is
        # scripts/verify-incident-audit.sh against the real database;
        # see this fixture's and that script's own docstrings.
        self.events: list[dict] = []
        self._next_event_id = 1

    def _record_event(self, incident_id, *, event_type, actor_type, previous_status, new_status, metadata):
        self.events.append(
            {
                "id": self._next_event_id,
                "incident_id": incident_id,
                "event_type": event_type,
                "actor_type": actor_type,
                "previous_status": previous_status,
                "new_status": new_status,
                "occurred_at": datetime.now(UTC),
                "metadata": dict(metadata),
            }
        )
        self._next_event_id += 1

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
        self,
        *,
        source,
        source_fingerprint,
        title,
        description,
        severity,
        first_seen_at,
        last_seen_at,
        occurrence_starts_at,
    ):
        metadata = {
            "source_fingerprint": source_fingerprint,
            "observed_starts_at": occurrence_starts_at.isoformat(),
        }
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
                # Mirrors the real repository's GREATEST(...) — only
                # ever advances, never regresses. See
                # ingestion/service.py and
                # database/migrations/V2__add_occurrence_watermark.sql.
                row["occurrence_starts_at"] = max(row["occurrence_starts_at"], occurrence_starts_at)
                row["updated_at"] = datetime.now(UTC)
                self._record_event(
                    row["id"],
                    event_type="observed",
                    actor_type="alertmanager",
                    previous_status=row["status"],
                    new_status=row["status"],
                    metadata=metadata,
                )
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
                "occurrence_starts_at": occurrence_starts_at,
            }
        )
        self._record_event(
            new_id,
            event_type="created",
            actor_type="alertmanager",
            previous_status=None,
            new_status="open",
            metadata=metadata,
        )
        return new_id, True

    async def commit(self) -> None:
        # No real session/transaction behind this fake to actually
        # commit — but see commit_count's own docstring above for why
        # this call still needs to be counted, not simply a silent
        # no-op.
        self.commit_count += 1

    # Phase 3D: in-memory approximations of the repository's lifecycle
    # methods, for exercising api/incidents.py's and
    # ingestion/service.py's own route/decision logic in isolation.
    # They are NOT proof of real PostgreSQL atomicity/concurrency —
    # that proof is scripts/verify-incident-lifecycle.sh and
    # scripts/verify-webhook-ingestion.sh against the real database.

    async def get_active_incident(self, *, source, source_fingerprint):
        for row in self.rows:
            if (
                row["source"] == source
                and row["source_fingerprint"] == source_fingerprint
                and row["status"] not in ("resolved", "closed")
            ):
                return row
        return None

    async def get_most_recent_incident(self, *, source, source_fingerprint):
        candidates = [
            row
            for row in self.rows
            if row["source"] == source and row["source_fingerprint"] == source_fingerprint
        ]
        if not candidates:
            return None
        # Ordered by the occurrence watermark, not the immutable
        # first_seen_at — mirrors the real repository's
        # get_most_recent_incident (see its own docstring for why).
        return max(candidates, key=lambda r: (r["occurrence_starts_at"], r["created_at"]))

    async def acquire_fingerprint_lock(self, **kwargs) -> None:
        # No real concurrency to serialize against in an in-memory
        # single-threaded fake.
        pass

    async def transition_incident_status(self, incident_id, *, expected_status, target_status, resolved_at):
        for row in self.rows:
            if row["id"] == incident_id:
                if row["status"] != expected_status:
                    return None
                row["status"] = target_status
                if resolved_at is not None:
                    row["resolved_at"] = resolved_at
                row["updated_at"] = datetime.now(UTC)
                self._record_event(
                    incident_id,
                    event_type="status_transition",
                    actor_type="operator",
                    previous_status=expected_status,
                    new_status=target_status,
                    metadata={},
                )
                return row
        return None

    async def resolve_active_incident_for_fingerprint(self, incident_id, *, resolved_at):
        for row in self.rows:
            if row["id"] == incident_id:
                if row["status"] in ("resolved", "closed"):
                    return None
                previous_status = row["status"]
                row["status"] = "resolved"
                row["resolved_at"] = resolved_at
                row["updated_at"] = datetime.now(UTC)
                self._record_event(
                    incident_id,
                    event_type="status_transition",
                    actor_type="alertmanager",
                    previous_status=previous_status,
                    new_status="resolved",
                    metadata={"resolution_source": "alertmanager_webhook"},
                )
                return row
        return None

    async def get_incident_events(self, incident_id, *, limit, offset):
        matched = [e for e in self.events if e["incident_id"] == incident_id]
        matched.sort(key=lambda e: (e["occurred_at"], e["id"]))
        total = len(matched)
        page = matched[offset : offset + limit]
        return page, total


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
    # Defaults to first_seen_at (after any override above has already
    # been applied) — the correct value for a row that has never
    # accepted a newer firing observation since creation. A caller
    # testing watermark-advancement behavior passes
    # occurrence_starts_at explicitly as one of **overrides.
    row.setdefault("occurrence_starts_at", row["first_seen_at"])
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
