"""Shared test fixtures. Unit tests never make a real network call or
a real database connection -- see individual test modules for which
seam each fake double replaces. Real PostgreSQL/LangGraph checkpoint
durability and the real privilege boundary are covered by
test_checkpoint_durability.py and test_db_privilege_boundary.py
respectively (gated exactly like retrieval-service's own
test_db_transaction.py), and by scripts/verify-agent-runtime.sh
against the real Compose stack.
"""

import uuid
from datetime import UTC, datetime

SAMPLE_INCIDENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def incident_json(
    *,
    incident_id: uuid.UUID = SAMPLE_INCIDENT_ID,
    status: str = "resolved",
    severity: str = "critical",
    title: str = "checkout-service is returning HTTP 5xx errors",
    description: str | None = "checkout-service has served HTTP 5xx responses",
    source: str = "alertmanager",
    source_fingerprint: str = "deadbeef12345678",
    organization_id: str = LEGACY_ORGANIZATION_ID,
) -> dict:
    first_seen_at = datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC)
    last_seen_at = datetime(2026, 4, 1, 9, 5, 0, tzinfo=UTC)
    return {
        "id": str(incident_id),
        "organization_id": organization_id,
        "source": source,
        "source_fingerprint": source_fingerprint,
        "title": title,
        "description": description,
        "severity": severity,
        "status": status,
        "first_seen_at": first_seen_at.isoformat(),
        "last_seen_at": last_seen_at.isoformat(),
        "resolved_at": last_seen_at.isoformat() if status == "resolved" else None,
        "created_at": first_seen_at.isoformat(),
        "updated_at": last_seen_at.isoformat(),
    }


def investigation_report_json(*, incident_id: uuid.UUID = SAMPLE_INCIDENT_ID, **overrides) -> dict:
    base = {
        "incident_id": str(incident_id),
        "investigated_at": datetime(2026, 4, 1, 9, 30, 0, tzinfo=UTC).isoformat(),
        "incident_status_at_investigation": "resolved",
        "summary": "Validated observations: 502 observed. (evidence: E1).",
        "observations": [{"statement": "502 observed", "evidence_ids": ["E1"]}],
        "hypotheses": [],
        "missing_evidence": [],
        "suggested_checks": [],
        "evidence": [
            {
                "id": "E1",
                "source": "control_plane",
                "observed_at": None,
                "window_start": None,
                "window_end": None,
                "summary": "s",
                "detail": "d",
                "reference": {},
            }
        ],
        "source_outcomes": [{"source": "control_plane", "status": "ok", "detail": "d", "query_summary": None}],
        "retrieval_context": {"knowledge": [], "historical_incidents": [], "outcome": "no_data", "detail": ""},
        "provider": {"configured": True, "provider": "stub", "model": "stub-deterministic-v1"},
        "validation_notes": [],
    }
    base.update(overrides)
    return base
