"""Exercises evals/scoring/investigation_quality.py against the REAL
agent_runtime_service.graph.nodes.classify_investigation, plus Gate D
negative controls."""

from evals.scoring.investigation_quality import score_investigation_quality_case
from evals.scoring.models import Result
from evals.tests.conftest import make_case, sample_investigation_report


async def test_well_supported_classification_matches():
    report = sample_investigation_report(
        hypotheses=[
            {
                "statement": "h",
                "supporting_evidence_ids": ["E1"],
                "conflicting_evidence_ids": [],
                "supporting_context_ids": [],
                "conflicting_context_ids": [],
                "confidence": "high",
            }
        ],
        source_outcomes=[{"source": "prometheus", "status": "ok", "detail": "d"}],
    )
    case = make_case(
        evaluation_mode="investigation_quality",
        input={"investigation_report": report},
        expected_outcome={"expected_classification": "well_supported"},
    )
    result = await score_investigation_quality_case(case)
    assert result.result == Result.PASS


async def test_negative_control_wrong_expected_classification_is_reported_as_FAIL():
    report = sample_investigation_report()  # no observations, no hypotheses -> real classification is "inconclusive"
    case = make_case(
        evaluation_mode="investigation_quality",
        input={"investigation_report": report},
        expected_outcome={"expected_classification": "well_supported"},  # WRONG
    )
    result = await score_investigation_quality_case(case)
    assert result.result == Result.FAIL


async def test_high_confidence_without_evidence_is_flagged_even_if_otherwise_passing():
    """A report whose own hypothesis is confidence='high' with NO
    supporting evidence must never pass the rubric check, even if the
    bare classification label happens to match -- this would mean the
    report bypassed real citation validation somehow."""
    report = sample_investigation_report(
        hypotheses=[
            {
                "statement": "h",
                "supporting_evidence_ids": [],
                "conflicting_evidence_ids": [],
                "supporting_context_ids": [],
                "conflicting_context_ids": [],
                "confidence": "high",
            }
        ]
    )
    case = make_case(
        evaluation_mode="investigation_quality",
        input={"investigation_report": report},
        expected_outcome={"expected_classification": "partial"},
    )
    result = await score_investigation_quality_case(case)
    assert result.result == Result.FAIL
    assert "high" in result.detail


async def test_malformed_report_is_not_evaluated():
    case = make_case(
        evaluation_mode="investigation_quality",
        input={"investigation_report": {"not": "a real report"}},
        expected_outcome={},
    )
    result = await score_investigation_quality_case(case)
    assert result.result == Result.NOT_EVALUATED
