"""Exercises evals/scoring/citation.py against the REAL
investigator_service.llm.validation.parse_and_validate -- both normal
cases and Gate D negative controls (proving the harness itself detects
a fabrication, never just that a well-formed case happens to pass)."""

from evals.scoring.citation import score_citation_case
from evals.scoring.models import Result
from evals.tests.conftest import make_case, sample_evidence_package


async def test_real_citation_survives_unmodified():
    case = make_case(
        evaluation_mode="citation",
        input={
            "evidence_package": sample_evidence_package(),
            "retrieval_context": None,
            "provider_response_text": (
                '{"summary": "x", "observations": [{"statement": "a", "evidence_ids": ["E1"]}], '
                '"hypotheses": [], "missing_evidence": [], "suggested_checks": []}'
            ),
        },
        expected_outcome={"min_surviving_observations": 1, "max_surviving_observations": 1},
    )
    result = await score_citation_case(case)
    assert result.result == Result.PASS


async def test_fabricated_evidence_id_is_detected_and_stripped():
    case = make_case(
        evaluation_mode="citation",
        input={
            "evidence_package": sample_evidence_package(),
            "retrieval_context": None,
            "provider_response_text": (
                '{"summary": "x", "observations": [{"statement": "a", "evidence_ids": ["E99"]}], '
                '"hypotheses": [], "missing_evidence": [], "suggested_checks": []}'
            ),
        },
        expected_outcome={
            "max_surviving_observations": 0,
            "fabricated_evidence_ids_must_be_absent": ["E99"],
            "validation_notes_must_mention": ["fabricated"],
        },
    )
    result = await score_citation_case(case)
    assert result.result == Result.PASS  # the CASE's own expectation (that fabrication is caught) is met


# --- Gate D negative controls: the harness must ACTUALLY fail these ---


async def test_negative_control_an_invented_citation_that_survives_is_reported_as_FAIL():
    """If a case's expected_outcome WRONGLY claims a fabricated id must
    survive, the harness must report FAIL, not quietly agree."""
    case = make_case(
        evaluation_mode="citation",
        input={
            "evidence_package": sample_evidence_package(),
            "retrieval_context": None,
            "provider_response_text": (
                '{"summary": "x", "observations": [{"statement": "a", "evidence_ids": ["E99"]}], '
                '"hypotheses": [], "missing_evidence": [], "suggested_checks": []}'
            ),
        },
        expected_outcome={"min_surviving_observations": 1},  # WRONG: E99 is fabricated, nothing should survive
    )
    result = await score_citation_case(case)
    assert result.result == Result.FAIL


async def test_negative_control_wrong_provenance_evidence_id_shown_to_different_case_is_detected():
    """An id that exists in a DIFFERENT package must still be treated
    as fabricated here -- evidence/retrieval provenance must never be
    confused (Gate C requirement A's own explicit text)."""
    case = make_case(
        evaluation_mode="citation",
        input={
            # This package's only real id is E1 -- E2 was never shown.
            "evidence_package": sample_evidence_package(items=[{"id": "E1", "source": "control_plane", "summary": "s", "detail": "d", "reference": {}}]),
            "retrieval_context": None,
            "provider_response_text": (
                '{"summary": "x", "observations": [{"statement": "a", "evidence_ids": ["E2"]}], '
                '"hypotheses": [], "missing_evidence": [], "suggested_checks": []}'
            ),
        },
        expected_outcome={"fabricated_evidence_ids_must_be_absent": ["E2"], "max_surviving_observations": 0},
    )
    result = await score_citation_case(case)
    assert result.result == Result.PASS  # the harness correctly identifies E2 as fabricated-in-this-context


async def test_malformed_case_input_is_not_evaluated_never_a_pass():
    case = make_case(
        evaluation_mode="citation",
        input={"evidence_package": {"this": "does not match EvidencePackage at all"}, "provider_response_text": "{}"},
        expected_outcome={},
    )
    result = await score_citation_case(case)
    assert result.result == Result.NOT_EVALUATED


async def test_malformed_provider_output_is_handled_safely():
    case = make_case(
        evaluation_mode="citation",
        input={
            "evidence_package": sample_evidence_package(),
            "retrieval_context": None,
            "provider_response_text": "not json at all",
        },
        expected_outcome={},
    )
    result = await score_citation_case(case)
    assert result.result == Result.FAIL  # ProviderOutputError, not expected -> reported as failure, never silently ignored
