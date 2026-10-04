"""Shared test fixtures.

Unit tests never make a real network call to control-plane,
Prometheus, Loki, Tempo, or a real LLM provider. HTTP-level client
tests inject httpx.MockTransport; EvidenceCollector/Investigator-level
tests inject fake client/provider doubles implementing the same
method signatures as the real ones — the same seam-based philosophy
control-plane's own FakeIncidentRepository already uses, never a
mocked SQLAlchemy/httpx internal.
"""

import uuid
from datetime import UTC, datetime, timedelta

from investigator_service.config import EvidenceBounds

SAMPLE_INCIDENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Shared, explicit bounds for tests that need an EvidenceBounds but
# are not themselves testing bounds/clamping behavior (that is
# test_config.py's job).
TEST_BOUNDS = EvidenceBounds(
    max_audit_events=200,
    max_prometheus_series=10,
    max_loki_lines=20,
    max_loki_line_length=500,
    max_tempo_traces=5,
    max_incident_text_length=2000,
    evidence_window_before_seconds=900,
    evidence_window_after_seconds=900,
    max_prompt_evidence_items=80,
    max_prompt_chars=40_000,
)


def incident_json(
    *,
    incident_id: uuid.UUID = SAMPLE_INCIDENT_ID,
    status: str = "resolved",
    severity: str = "critical",
    title: str = "checkout-service is returning HTTP 5xx errors",
    description: str | None = "checkout-service has served HTTP 5xx responses",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> dict:
    first_seen_at = first_seen_at or datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC)
    last_seen_at = last_seen_at or (first_seen_at + timedelta(minutes=5))
    return {
        "id": str(incident_id),
        "source": "alertmanager",
        "source_fingerprint": "deadbeef12345678",
        "title": title,
        "description": description,
        "severity": severity,
        "status": status,
        "first_seen_at": first_seen_at.isoformat(),
        "last_seen_at": last_seen_at.isoformat(),
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
        "created_at": first_seen_at.isoformat(),
        "updated_at": last_seen_at.isoformat(),
    }


def event_json(
    *,
    event_id: int,
    incident_id: uuid.UUID = SAMPLE_INCIDENT_ID,
    event_type: str = "created",
    actor_type: str = "alertmanager",
    previous_status: str | None = None,
    new_status: str = "open",
    occurred_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict:
    occurred_at = occurred_at or datetime(2026, 4, 1, 9, 0, 1, tzinfo=UTC)
    return {
        "id": event_id,
        "incident_id": str(incident_id),
        "event_type": event_type,
        "actor_type": actor_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "occurred_at": occurred_at.isoformat(),
        "metadata": metadata or {},
    }
