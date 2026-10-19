"""Gate D tests: the finding contract must remain valid for an unknown
incident with zero scenario matches, must never require a scenario_id,
and must keep OBSERVATION/HYPOTHESIS/DIAGNOSTIC/REMEDIATION/EXECUTION/
RECOVERY as separate, independently-gated stages."""

import pytest
from pydantic import ValidationError

from catalog.schemas.finding import (
    CandidateScenarioMatch,
    EvidenceProvenance,
    FailureFinding,
    Observation,
    RemediationProposal,
)


def _evidence() -> EvidenceProvenance:
    return EvidenceProvenance(
        source_system="test-system",
        source_identifier="trace-123",
        collected_at="2026-10-19T00:00:00Z",
        collection_method="synthetic-test",
    )


def test_a_finding_without_any_scenario_match_is_valid():
    """An unknown incident -- no catalog match at all -- must remain a
    fully valid FailureFinding, not an error state."""
    finding = FailureFinding(
        finding_id="F-0001",
        observed_service_or_resource="checkout-service",
        observation_window_start="2026-10-19T00:00:00Z",
    )
    assert finding.candidate_known_scenario_matches == []
    assert finding.unresolved_classification is True


def test_finding_has_no_top_level_scenario_id_field():
    """scenario_id must never exist as a required (or even optional)
    top-level field -- only as an entry inside
    candidate_known_scenario_matches, which may be empty."""
    assert "scenario_id" not in FailureFinding.model_fields


def test_candidate_match_is_additive_not_a_substitute_for_unresolved_flag():
    """Even WITH a candidate match, unresolved_classification defaults
    to True -- a candidate match is a hypothesis, never an automatic
    resolution of the finding's classification."""
    finding = FailureFinding(
        finding_id="F-0002",
        observed_service_or_resource="billing-service",
        observation_window_start="2026-10-19T00:00:00Z",
        candidate_known_scenario_matches=[
            CandidateScenarioMatch(
                scenario_id="D01-F16",
                match_confidence=0.4,
                match_rationale="title keyword overlap only -- not confirmed",
            )
        ],
    )
    assert finding.unresolved_classification is True
    assert finding.candidate_known_scenario_matches[0].scenario_id == "D01-F16"


def test_observation_is_not_a_hypothesis_or_remediation():
    """The stages are genuinely separate models -- an Observation
    cannot be mistaken for, or substituted as, a RemediationProposal."""
    obs = Observation(
        observation_id="OBS-1",
        observed_service_or_resource="checkout-service",
        observation_window_start="2026-10-19T00:00:00Z",
        actual_behavior="p99 latency elevated 4x baseline",
        evidence=_evidence(),
    )
    assert not isinstance(obs, RemediationProposal)
    assert obs.expected_or_baseline_behavior is None


def test_remediation_proposal_always_requires_human_approval_by_default():
    proposal = RemediationProposal(
        proposal_id="RP-1",
        hypothesis_id="H-1",
        description="restart affected pods",
        risk_notes="no known side effects in staging",
    )
    assert proposal.requires_human_approval is True


def test_remediation_proposal_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RemediationProposal(
            proposal_id="RP-2",
            hypothesis_id="H-1",
            description="x",
            risk_notes="y",
            auto_execute=True,
        )


def test_remediation_proposal_rejects_explicit_false_human_approval():
    """Correction-round Issue 1: requires_human_approval=False must be
    a ValidationError, never a silently-accepted bypass value."""
    with pytest.raises(ValidationError):
        RemediationProposal(
            proposal_id="RP-3",
            hypothesis_id="H-1",
            description="x",
            risk_notes="y",
            requires_human_approval=False,
        )


def test_diagnostic_check_rejects_explicit_false_read_only():
    """Correction-round Issue 1: read_only=False must be a
    ValidationError, never a silently-accepted mutating check."""
    from catalog.schemas.finding import DiagnosticCheck

    with pytest.raises(ValidationError):
        DiagnosticCheck(
            check_id="DC-1",
            hypothesis_id="H-1",
            description="x",
            expected_evidence_if_hypothesis_true="y",
            read_only=False,
        )


def test_finding_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        FailureFinding(
            finding_id="F-0003",
            observed_service_or_resource="x",
            observation_window_start="2026-10-19T00:00:00Z",
            scenario_id="D01-F01",
        )
