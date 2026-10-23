"""Shared fixtures for the Phase 10 harness's own test suite -- these
tests exercise evals/scoring/* and evals/runner/* directly, never the
versioned dataset under evals/cases/ (that dataset is exercised by
`python -m evals.runner` itself and by scripts/verify-evals-offline.sh)."""

from typing import Any

from evals.scoring.models import Case

SAMPLE_INCIDENT = {
    "id": "11111111-1111-1111-1111-111111111111",
    # Phase 14 correction round FINAL VALIDATION: organization_id
    # became a required IncidentSnapshot field (database/migrations/V10)
    # -- the same fixed "legacy local-development organization"
    # constant V10's own backfill used, never a fresh/random UUID this
    # harness's own tests were never designed around.
    "organization_id": "00000000-0000-0000-0000-000000000001",
    "source": "alertmanager",
    "source_fingerprint": "fp-1",
    "title": "checkout-service is returning HTTP 5xx errors",
    "description": None,
    "severity": "critical",
    "status": "investigating",
    "first_seen_at": "2026-01-01T00:00:00+00:00",
    "last_seen_at": "2026-01-01T00:00:00+00:00",
    "resolved_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


def sample_evidence_package(items: list[dict] | None = None, source_outcomes: list[dict] | None = None) -> dict:
    return {
        "incident": SAMPLE_INCIDENT,
        "events": [],
        "events_total": 0,
        "items": items
        if items is not None
        else [{"id": "E1", "source": "control_plane", "summary": "s", "detail": "d", "reference": {}}],
        "source_outcomes": source_outcomes if source_outcomes is not None else [{"source": "control_plane", "status": "ok", "detail": "d"}],
        "collected_at": "2026-01-01T00:05:00+00:00",
    }


def sample_investigation_report(**overrides: Any) -> dict:
    base = {
        "incident_id": "22222222-2222-2222-2222-222222222222",
        "investigated_at": "2026-01-01T00:05:00+00:00",
        "incident_status_at_investigation": "investigating",
        "summary": "s",
        "observations": [],
        "hypotheses": [],
        "missing_evidence": [],
        "suggested_checks": [],
        "evidence": [],
        "source_outcomes": [],
        "retrieval_context": {"knowledge": [], "historical_incidents": [], "outcome": "no_data", "detail": ""},
        "provider": {"configured": False, "provider": "stub", "model": None},
        "validation_notes": [],
    }
    base.update(overrides)
    return base


def make_case(
    *,
    case_id: str = "TEST-001",
    category: str = "test",
    evaluation_mode: str,
    input: dict,
    expected_outcome: dict,
    is_hard_safety_invariant: bool = False,
) -> Case:
    return Case(
        case_id=case_id,
        dataset_version="test",
        category=category,
        scenario_description="a test-only case, never part of the real versioned dataset",
        evaluation_mode=evaluation_mode,
        provenance={"kind": "synthetic", "notes": "test fixture"},
        ground_truth_rationale="test fixture -- exercises the harness itself",
        input=input,
        expected_outcome=expected_outcome,
        is_hard_safety_invariant=is_hard_safety_invariant,
    )
