"""Tests for historical.py -- Phase 6 §7: bounded/redacted incident
text, honest empty-history handling, never-invented history."""

from datetime import UTC, datetime

from retrieval_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot
from retrieval_service.historical import build_historical_incident_text
from tests.conftest import SAMPLE_INCIDENT_ID


def _incident(title="t", description="d", status="resolved") -> IncidentSnapshot:
    return IncidentSnapshot.model_validate(
        {
            "id": str(SAMPLE_INCIDENT_ID),
            "source": "alertmanager",
            "source_fingerprint": "fp",
            "title": title,
            "description": description,
            "severity": "critical",
            "status": status,
            "first_seen_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "last_seen_at": datetime(2026, 4, 1, 9, 5, 0, tzinfo=UTC).isoformat(),
            "resolved_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat() if status == "resolved" else None,
            "created_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "updated_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat(),
        }
    )


def _event(event_id=1) -> IncidentEventSnapshot:
    return IncidentEventSnapshot.model_validate(
        {
            "id": event_id,
            "incident_id": str(SAMPLE_INCIDENT_ID),
            "event_type": "created",
            "actor_type": "alertmanager",
            "previous_status": None,
            "new_status": "open",
            "occurred_at": datetime(2026, 4, 1, 9, 0, 1, tzinfo=UTC).isoformat(),
            "metadata": {},
        }
    )


def test_includes_core_fields():
    text = build_historical_incident_text(_incident(), [], 0, max_text_length=2000)
    assert str(SAMPLE_INCIDENT_ID) in text
    assert "title: t" in text
    assert "severity: critical" in text
    assert "status: resolved" in text


def test_empty_event_history_is_honest_not_invented():
    """Phase 6 §7: an incident with no audit events remains a valid
    historical record with an EXPLICIT empty history, never a
    fabricated timeline."""
    text = build_historical_incident_text(_incident(), [], 0, max_text_length=2000)
    assert "no audit events recorded" in text.lower()


def test_events_are_rendered_in_the_timeline():
    text = build_historical_incident_text(_incident(), [_event(1), _event(2)], 2, max_text_length=2000)
    assert text.count("created by alertmanager") == 2


def test_partial_event_retrieval_is_disclosed():
    text = build_historical_incident_text(_incident(), [_event(1)], events_total=5, max_text_length=2000)
    assert "only 1 of 5" in text


def test_title_and_description_are_bounded():
    text = build_historical_incident_text(
        _incident(title="t" * 5000, description="d" * 5000), [], 0, max_text_length=50
    )
    title_line = [line for line in text.splitlines() if line.startswith("title:")][0]
    assert len(title_line) <= 50 + len("title: ")


def test_credential_shaped_text_is_redacted():
    text = build_historical_incident_text(
        _incident(description="Authorization: Bearer sk-realsecretvalue1234567890"), [], 0, max_text_length=2000
    )
    assert "sk-realsecretvalue1234567890" not in text
    assert "REDACTED" in text


def test_no_description_renders_as_none():
    text = build_historical_incident_text(_incident(description=None), [], 0, max_text_length=2000)
    assert "description: (none)" in text
