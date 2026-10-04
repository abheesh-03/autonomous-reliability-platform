"""Tests for llm/validation.py — Phase 5 §9's "structured output
validation" and "rejection of fabricated evidence citations", as
strengthened across Phase 5 correction rounds: an observation
surviving with evidence_ids=[] is never acceptable; a hypothesis with
no real supporting evidence (fabricated-only or submitted with zero
citations) is dropped entirely rather than merely confidence-
downgraded; and (Phase 5 correction round #3) the provider's own
free-text summary is NEVER retained as-is -- the final summary is
always deterministically built from the already-validated
observations/hypotheses, so a claim rejected above can never survive
solely inside the summary field.

IMPORTANT: `parse_and_validate`'s second argument is the frozenset of
evidence ids actually SHOWN to the model (not a whole EvidencePackage)
— see llm/prompt.py's `build_prompts` return value, which is what a
real caller (investigator.py) passes."""

import json

import pytest

from investigator_service.llm.validation import UNVERIFIED_SUMMARY_FALLBACK, ProviderOutputError, parse_and_validate

VALID_IDS = frozenset({"E1", "E2"})


def test_valid_output_observations_and_hypotheses_pass_through_unchanged():
    """Observations/hypotheses with no fabricated citations pass
    through unchanged. The summary does not -- see
    test_valid_output_summary_is_built_from_validated_claims below."""
    raw = json.dumps(
        {
            "summary": "Checkout failures consistent with a dependency outage.",
            "observations": [{"statement": "502s observed", "evidence_ids": ["E1"]}],
            "hypotheses": [
                {
                    "statement": "payment-service outage",
                    "supporting_evidence_ids": ["E1", "E2"],
                    "conflicting_evidence_ids": [],
                    "confidence": "medium",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [{"description": "check payment-service logs", "rationale": "r"}],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.observations) == 1
    assert output.hypotheses[0].supporting_evidence_ids == ["E1", "E2"]
    assert output.hypotheses[0].confidence == "medium"
    # No fabrication anywhere -- the only note is the summary's
    # always-applied, structural replacement, never a drop/removal.
    assert len(notes) == 1
    assert "replaced the provider's free-text summary" in notes[0]


def test_valid_output_summary_is_built_from_validated_claims():
    """Phase 5 correction round #3: the provider's own free-text
    summary is never retained, even when nothing was fabricated --
    the final summary is always built structurally from the validated
    observations/hypotheses, and hypotheses are always labeled
    explicitly as unconfirmed."""
    raw = json.dumps(
        {
            "summary": "Checkout failures consistent with a dependency outage.",
            "observations": [{"statement": "502s observed", "evidence_ids": ["E1"]}],
            "hypotheses": [
                {
                    "statement": "payment-service outage",
                    "supporting_evidence_ids": ["E1", "E2"],
                    "conflicting_evidence_ids": [],
                    "confidence": "medium",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, _notes = parse_and_validate(raw, VALID_IDS)
    assert output.summary != "Checkout failures consistent with a dependency outage."
    assert "502s observed" in output.summary
    assert "payment-service outage" in output.summary
    assert "unconfirmed" in output.summary.lower()


def test_malformed_json_raises_provider_output_error():
    with pytest.raises(ProviderOutputError):
        parse_and_validate("not json at all {{{", VALID_IDS)


def test_wrong_shape_raises_provider_output_error():
    raw = json.dumps({"totally": "wrong shape"})
    with pytest.raises(ProviderOutputError):
        parse_and_validate(raw, VALID_IDS)


def test_markdown_fenced_json_is_still_parsed():
    raw = "```json\n" + json.dumps(
        {
            "summary": "irrelevant raw text -- never retained",
            "observations": [{"statement": "502s observed", "evidence_ids": ["E1"]}],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    ) + "\n```"
    output, _notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.observations) == 1
    assert output.observations[0].statement == "502s observed"
    assert "502s observed" in output.summary


def test_observation_with_a_valid_and_a_fabricated_id_keeps_the_valid_one():
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [{"statement": "claim", "evidence_ids": ["E1", "E999"]}],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.observations) == 1
    assert output.observations[0].evidence_ids == ["E1"]
    assert any("E999" in note for note in notes)


def test_hypothesis_with_a_valid_and_a_fabricated_id_keeps_the_valid_one():
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [],
            "hypotheses": [
                {
                    "statement": "h",
                    "supporting_evidence_ids": ["E1", "E_FAKE"],
                    "conflicting_evidence_ids": ["E2", "E_ALSO_FAKE"],
                    "confidence": "low",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    hyp = output.hypotheses[0]
    assert hyp.supporting_evidence_ids == ["E1"]
    assert hyp.conflicting_evidence_ids == ["E2"]
    assert any("E_FAKE" in note for note in notes)
    assert any("E_ALSO_FAKE" in note for note in notes)


def test_observation_with_only_fabricated_ids_is_dropped_entirely():
    """Phase 5 correction round #1 — THE core fix: a hallucinated
    factual observation must never survive with evidence_ids=[]."""
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [{"statement": "claim", "evidence_ids": ["E_NOPE"]}],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.observations == []
    assert any("dropped observation" in note for note in notes)
    assert any("E_NOPE" in note for note in notes)


def test_observation_with_no_citations_at_all_is_dropped_entirely():
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [{"statement": "claim with no evidence", "evidence_ids": []}],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.observations == []
    assert any("dropped observation" in note and "cited no evidence" in note for note in notes)


def test_mixed_observations_only_the_unsupported_one_is_dropped():
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [
                {"statement": "grounded claim", "evidence_ids": ["E1"]},
                {"statement": "hallucinated claim", "evidence_ids": ["E_FAKE"]},
            ],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.observations) == 1
    assert output.observations[0].statement == "grounded claim"
    assert any("hallucinated claim" in note for note in notes)


def test_hypothesis_with_all_fabricated_support_is_dropped_entirely():
    """Phase 5 correction round #2: a fabricated citation must never
    survive merely because confidence was lowered -- a hypothesis
    whose entire supporting evidence turns out fabricated is dropped,
    not kept with a downgraded confidence."""
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [],
            "hypotheses": [
                {
                    "statement": "h",
                    "supporting_evidence_ids": ["E_FAKE1", "E_FAKE2"],
                    "conflicting_evidence_ids": [],
                    "confidence": "high",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.hypotheses == []
    assert any("dropped hypothesis" in note and "E_FAKE1" in note and "E_FAKE2" in note for note in notes)


def test_hypothesis_with_no_support_at_all_is_dropped_entirely():
    """Phase 5 correction round #2: a hypothesis initially submitted
    with zero supporting citations is dropped too, even at high
    confidence -- a hypothesis with no real evidence behind it is
    never surfaced, regardless of how confidently it was stated."""
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [],
            "hypotheses": [
                {
                    "statement": "pure speculation",
                    "supporting_evidence_ids": [],
                    "conflicting_evidence_ids": [],
                    "confidence": "high",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.hypotheses == []
    assert any("dropped hypothesis" in note and "cited no supporting evidence" in note for note in notes)


def test_properly_cited_hypothesis_is_retained():
    """A hypothesis with at least one real supporting citation
    survives unchanged alongside a dropped, unsupported one."""
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [],
            "hypotheses": [
                {
                    "statement": "grounded hypothesis",
                    "supporting_evidence_ids": ["E1"],
                    "conflicting_evidence_ids": [],
                    "confidence": "medium",
                },
                {
                    "statement": "unsupported hypothesis",
                    "supporting_evidence_ids": [],
                    "conflicting_evidence_ids": [],
                    "confidence": "low",
                },
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.hypotheses) == 1
    assert output.hypotheses[0].statement == "grounded hypothesis"
    assert output.hypotheses[0].supporting_evidence_ids == ["E1"]
    assert output.hypotheses[0].confidence == "medium"
    assert any("unsupported hypothesis" in note for note in notes)


def test_unsupported_summary_is_withheld_after_all_analysis_is_rejected():
    """Phase 5 correction round #2/#3: once every observation and
    hypothesis the model submitted has been rejected for lacking real
    evidence, nothing validated remains to build a summary from, so
    the fixed, conservative fallback is used."""
    raw = json.dumps(
        {
            "summary": "payment-service is definitely the root cause",
            "observations": [{"statement": "hallucinated claim", "evidence_ids": ["E_FAKE"]}],
            "hypotheses": [
                {
                    "statement": "h",
                    "supporting_evidence_ids": ["E_FAKE2"],
                    "conflicting_evidence_ids": [],
                    "confidence": "high",
                }
            ],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.observations == []
    assert output.hypotheses == []
    assert output.summary != "payment-service is definitely the root cause"
    assert output.summary == UNVERIFIED_SUMMARY_FALLBACK
    assert "could not be verified" in output.summary
    assert any("replaced the provider's free-text summary" in note for note in notes)


def test_mixed_valid_and_fabricated_claims_summary_never_carries_the_rejected_one():
    """Phase 5 final pre-commit housekeeping, issue 1 — the core fix:
    even when SOME claims survive, the provider's own free-text
    summary is never retained verbatim. It is rebuilt from the
    validated observations/hypotheses only, so a claim rejected above
    (here, a fabricated-citation observation the model's own summary
    explicitly named) can never survive solely inside the summary
    field."""
    raw = json.dumps(
        {
            "summary": (
                "Both the grounded checkout latency spike and the hallucinated payment-service "
                "total outage contributed to this incident."
            ),
            "observations": [
                {"statement": "checkout latency spike observed", "evidence_ids": ["E1"]},
                {"statement": "payment-service total outage", "evidence_ids": ["E_FAKE"]},
            ],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert len(output.observations) == 1
    assert output.observations[0].statement == "checkout latency spike observed"
    # The rejected claim's own words never survive, even though the
    # provider's original summary explicitly mentioned them.
    assert "hallucinated" not in output.summary
    assert "total outage" not in output.summary
    assert "payment-service" not in output.summary
    # The surviving, validated claim is what the summary is built from.
    assert "checkout latency spike observed" in output.summary
    assert any("replaced the provider's free-text summary" in note for note in notes)


def test_summary_is_replaced_even_when_model_submitted_no_claims_at_all():
    """Phase 5 correction round #3: a model that honestly submits no
    observations/hypotheses (e.g. insufficient evidence) still has its
    own free-text summary replaced -- this module can never
    semantically verify arbitrary prose, so "nothing to validate" is
    treated the same conservative way as "everything was rejected"."""
    raw = json.dumps(
        {
            "summary": "insufficient evidence to form an opinion",
            "observations": [],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, VALID_IDS)
    assert output.summary != "insufficient evidence to form an opinion"
    assert output.summary == UNVERIFIED_SUMMARY_FALLBACK
    assert any("replaced the provider's free-text summary" in note for note in notes)


def test_extra_unexpected_top_level_field_is_rejected():
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
            "executed_remediation": "restarted payment-service",
        }
    )
    with pytest.raises(ProviderOutputError):
        parse_and_validate(raw, VALID_IDS)


def test_validation_uses_only_shown_ids_not_a_larger_collected_set():
    """IMPORTANT (Phase 5 correction round #1): an id that genuinely
    exists in the larger collected package but was never actually
    shown to the model is exactly as fabricated as one that never
    existed at all."""
    shown_ids = frozenset({"E1"})  # E2 was collected but never shown
    raw = json.dumps(
        {
            "summary": "s",
            "observations": [{"statement": "claim", "evidence_ids": ["E2"]}],
            "hypotheses": [],
            "missing_evidence": [],
            "suggested_checks": [],
        }
    )
    output, notes = parse_and_validate(raw, shown_ids)
    assert output.observations == []
    assert any("E2" in note for note in notes)
