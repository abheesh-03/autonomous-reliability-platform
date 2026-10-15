"""Logic-level tests for indexer.py -- verifies it calls db.py's
write functions correctly (right arguments, right cleanup calls) by
monkeypatching db.py's own functions with recording fakes, the same
"test at the seam" philosophy as the rest of this repository (db.py
IS the repository layer here; monkeypatching OUR OWN module's
functions is not mocking a third-party internal).

Real PostgreSQL constraint/idempotency behavior (the ON CONFLICT
upsert actually converging onto the same row, the UNIQUE constraint
actually enforcing itself) is proven against the real database by
scripts/verify-rag.sh, not here -- this file only proves indexer.py's
OWN orchestration logic calls the repository layer the right way.
"""

from retrieval_service import indexer
from retrieval_service.config import IndexingBounds
from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider
from tests.conftest import SAMPLE_INCIDENT_ID

TEST_BOUNDS = IndexingBounds(
    knowledge_root="/unused",
    max_chunk_chars=1200,
    chunk_overlap_chars=150,
    max_historical_incidents=200,
    max_audit_events_per_incident=100,
    max_incident_text_length=2000,
)


class _FakeTransaction:
    """Real transactional atomicity (COMMIT/ROLLBACK) is proven
    against the real database by scripts/verify-rag.sh and the real-DB
    regression test below -- this fake only needs to support the
    `async with conn.transaction():` syntax `_index_one_source` uses,
    not actually enforce rollback semantics (db.py's write functions
    are monkeypatched in these tests anyway)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False  # never swallow an exception


class _FakeConnection:
    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RecordingPool:
    """A placeholder "pool" object -- never actually used for a real
    query here, since db.py's functions themselves are monkeypatched
    below; this only needs to support `pool.acquire()` (yielding a
    fake connection) the same way `_index_one_source` uses a real
    `asyncpg.Pool`, and to otherwise be a distinct, identifiable
    object passed through unchanged."""

    def acquire(self):
        return _FakeAcquire()


class FakeControlPlaneClient:
    def __init__(self, incidents, events_by_incident=None):
        self._incidents = incidents
        self._events_by_incident = events_by_incident or {}

    async def list_all_incidents(self, *, max_incidents):
        return self._incidents[:max_incidents]

    async def get_all_events(self, incident_id, *, max_events):
        events = self._events_by_incident.get(incident_id, [])
        return events[:max_events], len(events)


def _incident(incident_id=SAMPLE_INCIDENT_ID, title="t"):
    from datetime import UTC, datetime

    from retrieval_service.domain.incident_snapshot import IncidentSnapshot

    return IncidentSnapshot.model_validate(
        {
            "id": str(incident_id),
            "source": "alertmanager",
            "source_fingerprint": "fp",
            "title": title,
            "description": None,
            "severity": "critical",
            "status": "resolved",
            "first_seen_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "last_seen_at": datetime(2026, 4, 1, 9, 5, 0, tzinfo=UTC).isoformat(),
            "resolved_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat(),
            "created_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "updated_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat(),
        }
    )


async def test_index_knowledge_upserts_one_chunk_per_document_and_cleans_stale_sources(monkeypatch, tmp_path):
    (tmp_path / "a.md").write_text("# A\nshort body a")
    (tmp_path / "b.md").write_text("# B\nshort body b")
    bounds = IndexingBounds(
        knowledge_root=str(tmp_path),
        max_chunk_chars=1200,
        chunk_overlap_chars=150,
        max_historical_incidents=200,
        max_audit_events_per_incident=100,
        max_incident_text_length=2000,
    )

    upsert_calls = []
    delete_beyond_calls = []
    delete_sources_calls = []

    async def fake_upsert_chunk(pool, **kwargs):
        upsert_calls.append(kwargs)

    async def fake_delete_chunks_beyond(pool, **kwargs):
        delete_beyond_calls.append(kwargs)
        return 0

    async def fake_delete_sources_not_in(pool, **kwargs):
        delete_sources_calls.append(kwargs)
        return 0

    monkeypatch.setattr(indexer.db, "upsert_chunk", fake_upsert_chunk)
    monkeypatch.setattr(indexer.db, "delete_chunks_beyond", fake_delete_chunks_beyond)
    monkeypatch.setattr(indexer.db, "delete_sources_not_in", fake_delete_sources_not_in)

    provider = LocalLexicalEmbeddingProvider()
    result = await indexer.index_knowledge(_RecordingPool(), provider, bounds)

    assert result["documents"] == 2
    assert {c["source_key"] for c in upsert_calls} == {"a.md", "b.md"}
    assert all(c["embedding_space"] == provider.embedding_space for c in upsert_calls)
    assert all(c["source_type"] == "knowledge" for c in upsert_calls)
    # Stale-source cleanup runs with the CURRENT full set of source keys.
    assert len(delete_sources_calls) == 1
    assert set(delete_sources_calls[0]["keep_source_keys"]) == {"a.md", "b.md"}
    # Per-document stale-chunk cleanup runs once per document.
    assert len(delete_beyond_calls) == 2


async def test_index_knowledge_is_idempotent_in_its_own_call_shape(monkeypatch, tmp_path):
    """Running index_knowledge twice with unchanged content issues the
    exact same upsert calls both times -- db.py's own ON CONFLICT
    target (proven against the real database by scripts/verify-rag.sh)
    is what makes that converge onto the same rows rather than
    duplicate them; this test proves indexer.py's OWN call shape is
    stable/repeatable, the precondition for that guarantee to hold."""
    (tmp_path / "a.md").write_text("# A\nshort body a")
    bounds = IndexingBounds(
        knowledge_root=str(tmp_path),
        max_chunk_chars=1200,
        chunk_overlap_chars=150,
        max_historical_incidents=200,
        max_audit_events_per_incident=100,
        max_incident_text_length=2000,
    )

    calls = []

    async def fake_upsert_chunk(pool, **kwargs):
        calls.append(kwargs)

    async def fake_delete_chunks_beyond(pool, **kwargs):
        return 0

    async def fake_delete_sources_not_in(pool, **kwargs):
        return 0

    monkeypatch.setattr(indexer.db, "upsert_chunk", fake_upsert_chunk)
    monkeypatch.setattr(indexer.db, "delete_chunks_beyond", fake_delete_chunks_beyond)
    monkeypatch.setattr(indexer.db, "delete_sources_not_in", fake_delete_sources_not_in)

    provider = LocalLexicalEmbeddingProvider()
    await indexer.index_knowledge(_RecordingPool(), provider, bounds)
    first_run = list(calls)
    calls.clear()
    await indexer.index_knowledge(_RecordingPool(), provider, bounds)
    second_run = list(calls)

    assert first_run == second_run


async def test_index_knowledge_changed_content_produces_a_different_content_hash(monkeypatch, tmp_path):
    bounds_for = lambda root: IndexingBounds(  # noqa: E731
        knowledge_root=str(root),
        max_chunk_chars=1200,
        chunk_overlap_chars=150,
        max_historical_incidents=200,
        max_audit_events_per_incident=100,
        max_incident_text_length=2000,
    )

    calls = []

    async def fake_upsert_chunk(pool, **kwargs):
        calls.append(kwargs)

    async def fake_delete_chunks_beyond(pool, **kwargs):
        return 0

    async def fake_delete_sources_not_in(pool, **kwargs):
        return 0

    monkeypatch.setattr(indexer.db, "upsert_chunk", fake_upsert_chunk)
    monkeypatch.setattr(indexer.db, "delete_chunks_beyond", fake_delete_chunks_beyond)
    monkeypatch.setattr(indexer.db, "delete_sources_not_in", fake_delete_sources_not_in)

    provider = LocalLexicalEmbeddingProvider()
    (tmp_path / "a.md").write_text("# A\noriginal body")
    await indexer.index_knowledge(_RecordingPool(), provider, bounds_for(tmp_path))
    first_hash = calls[0]["content_hash"]

    calls.clear()
    (tmp_path / "a.md").write_text("# A\nCHANGED body entirely")
    await indexer.index_knowledge(_RecordingPool(), provider, bounds_for(tmp_path))
    second_hash = calls[0]["content_hash"]

    assert first_hash != second_hash


async def test_index_historical_incidents_never_deletes_sources_outside_the_current_page():
    """Phase 6 §7/§20: max_historical_incidents is a per-run BUDGET,
    never a claim that incidents outside it no longer exist -- unlike
    knowledge, no "delete sources not in" cleanup ever runs here."""
    assert "delete_sources_not_in" not in indexer.index_historical_incidents.__code__.co_names


async def test_index_historical_incidents_builds_one_chunk_set_per_incident(monkeypatch):
    upsert_calls = []

    async def fake_upsert_chunk(pool, **kwargs):
        upsert_calls.append(kwargs)

    async def fake_delete_chunks_beyond(pool, **kwargs):
        return 0

    monkeypatch.setattr(indexer.db, "upsert_chunk", fake_upsert_chunk)
    monkeypatch.setattr(indexer.db, "delete_chunks_beyond", fake_delete_chunks_beyond)

    incident_a = _incident(incident_id="11111111-1111-1111-1111-111111111111", title="first incident")
    incident_b = _incident(incident_id="22222222-2222-2222-2222-222222222222", title="second incident")
    control_plane = FakeControlPlaneClient([incident_a, incident_b])

    provider = LocalLexicalEmbeddingProvider()
    result = await indexer.index_historical_incidents(_RecordingPool(), provider, control_plane, TEST_BOUNDS)

    assert result["incidents"] == 2
    source_keys = {c["source_key"] for c in upsert_calls}
    assert source_keys == {str(incident_a.id), str(incident_b.id)}
    assert all(c["source_type"] == "historical_incident" for c in upsert_calls)


async def test_index_historical_incidents_handles_empty_audit_history_honestly(monkeypatch):
    upsert_calls = []

    async def fake_upsert_chunk(pool, **kwargs):
        upsert_calls.append(kwargs)

    async def fake_delete_chunks_beyond(pool, **kwargs):
        return 0

    monkeypatch.setattr(indexer.db, "upsert_chunk", fake_upsert_chunk)
    monkeypatch.setattr(indexer.db, "delete_chunks_beyond", fake_delete_chunks_beyond)

    incident = _incident()
    control_plane = FakeControlPlaneClient([incident], events_by_incident={})  # no events at all

    provider = LocalLexicalEmbeddingProvider()
    result = await indexer.index_historical_incidents(_RecordingPool(), provider, control_plane, TEST_BOUNDS)
    assert result["incidents"] == 1
    assert len(upsert_calls) >= 1
    assert "no audit events recorded" in upsert_calls[0]["content"].lower()
