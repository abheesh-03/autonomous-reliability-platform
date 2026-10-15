"""Tests for graph/nodes.py's classify_investigation -- Phase 7 node 3
(evaluate_investigation): deterministic, orchestration-level
assessment, never a second LLM call, never invented certainty."""

from agent_runtime_service.graph.nodes import classify_investigation


def _report(**overrides) -> dict:
    base = {
        "observations": [],
        "hypotheses": [],
        "missing_evidence": [],
        "source_outcomes": [],
        "retrieval_context": {"outcome": "no_data"},
    }
    base.update(overrides)
    return base


def test_no_observations_and_no_hypotheses_is_inconclusive():
    assert classify_investigation(_report()) == "inconclusive"


def test_high_confidence_evidence_backed_hypothesis_with_no_gaps_is_well_supported():
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "high"}],
        source_outcomes=[{"source": "control_plane", "status": "ok"}],
        retrieval_context={"outcome": "ok"},
    )
    assert classify_investigation(report) == "well_supported"


def test_low_confidence_evidence_backed_hypothesis_with_no_gaps_is_only_partial():
    """Phase 7 correction round (finding #12): a hypothesis the model
    itself declared "low" confidence must NEVER be elevated into
    "well_supported" merely because telemetry sources were reachable
    and no gap was flagged -- this is the exact regression the
    correction fixes. "low" is also InvestigationReport's own Pydantic
    default (domain/investigation.py), so this is the realistic,
    common shape of a report whose hypotheses were never explicitly
    scored by the model/stub."""
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "low"}],
        source_outcomes=[{"source": "control_plane", "status": "ok"}],
        retrieval_context={"outcome": "ok"},
    )
    assert classify_investigation(report) == "partial"


def test_medium_confidence_evidence_backed_hypothesis_with_no_gaps_is_only_partial():
    """Same correction, the "at minimum" boundary case explicitly
    called out: "medium" confidence must also not be elevated."""
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "medium"}],
        source_outcomes=[{"source": "control_plane", "status": "ok"}],
        retrieval_context={"outcome": "ok"},
    )
    assert classify_investigation(report) == "partial"


def test_high_confidence_hypothesis_with_missing_evidence_is_partial():
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "high"}],
        missing_evidence=[{"description": "prometheus unavailable"}],
    )
    assert classify_investigation(report) == "partial"


def test_high_confidence_hypothesis_with_unavailable_source_is_partial():
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "high"}],
        source_outcomes=[{"source": "prometheus", "status": "unavailable"}],
    )
    assert classify_investigation(report) == "partial"


def test_high_confidence_hypothesis_with_unavailable_retrieval_is_partial():
    report = _report(
        hypotheses=[{"statement": "h", "supporting_evidence_ids": ["E1"], "confidence": "high"}],
        retrieval_context={"outcome": "unavailable"},
    )
    assert classify_investigation(report) == "partial"


def test_observation_only_with_no_hypothesis_is_partial_not_well_supported():
    """An observation alone (no evidence-backed hypothesis) is real
    signal, but never invented certainty -- "partial", not
    "well_supported"."""
    report = _report(observations=[{"statement": "502 observed", "evidence_ids": ["E1"]}])
    assert classify_investigation(report) == "partial"


def test_hypothesis_with_no_supporting_evidence_ids_never_counts_as_well_supported():
    """Phase 6 already guarantees a SURVIVING hypothesis has real E
    support -- but this function must never silently trust that
    invariant from a field it doesn't control; an (impossible in
    practice, but defensively handled) hypothesis with empty
    supporting_evidence_ids must never be treated as evidence-backed,
    even at "high" confidence."""
    report = _report(hypotheses=[{"statement": "h", "supporting_evidence_ids": [], "confidence": "high"}])
    assert classify_investigation(report) == "partial"
