import json
import pathlib

import pytest

from evals.scoring.models import Baseline, CaseResult, Result
from evals.scoring.regression import (
    BaselineError,
    BaselineMissingError,
    apply_missing_metric_checks,
    compare_metrics_to_baseline,
    compare_to_baseline,
    empty_baseline,
    load_baseline,
    write_baseline,
)


def _cr(case_id: str, result: Result, hard: bool = False, metrics: dict | None = None) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        category="c",
        evaluation_mode="citation",
        result=result,
        is_hard_safety_invariant=hard,
        detail="d",
        metrics=metrics or {},
    )


# --- load_baseline: strict, never silently empty (Issue 1/4) ---


def test_load_baseline_missing_file_raises_missing_error(tmp_path: pathlib.Path):
    with pytest.raises(BaselineMissingError):
        load_baseline(tmp_path / "nope.json", "v1")


def test_load_baseline_malformed_json_raises_baseline_error(tmp_path: pathlib.Path):
    path = tmp_path / "baseline.json"
    path.write_text("{not valid json")
    with pytest.raises(BaselineError):
        load_baseline(path, "v1")


def test_load_baseline_schema_mismatch_raises_baseline_error(tmp_path: pathlib.Path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dataset_version": "v1", "results": {"A": "NOT_A_REAL_RESULT"}}))
    with pytest.raises(BaselineError):
        load_baseline(path, "v1")


def test_load_baseline_dataset_version_mismatch_is_rejected_safely(tmp_path: pathlib.Path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dataset_version": "v2", "results": {"A": "PASS"}}))
    with pytest.raises(BaselineError):
        load_baseline(path, "v1")


def test_load_baseline_valid_file_round_trips(tmp_path: pathlib.Path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dataset_version": "v1", "results": {"A": "PASS"}, "metrics": {"A": {"m": 1.0}}}))
    baseline = load_baseline(path, "v1")
    assert baseline.results["A"] == Result.PASS
    assert baseline.metrics["A"]["m"] == 1.0


def test_empty_baseline_has_no_results_or_metrics():
    baseline = empty_baseline("v1")
    assert baseline.dataset_version == "v1"
    assert baseline.results == {}
    assert baseline.metrics == {}


# --- compare_to_baseline: outcome regressions ---


def test_no_findings_when_results_match_baseline():
    results = [_cr("A", Result.PASS)]
    findings = compare_to_baseline(results, Baseline(dataset_version="v1", results={"A": Result.PASS}))
    assert findings == []


def test_hard_safety_invariant_regression_is_flagged():
    results = [_cr("A", Result.FAIL, hard=True)]
    findings = compare_to_baseline(results, Baseline(dataset_version="v1", results={"A": Result.PASS}))
    assert len(findings) == 1
    assert findings[0].is_hard_safety_invariant is True
    assert findings[0].current_result == Result.FAIL


def test_soft_metric_regression_is_reported_but_distinctly_non_hard():
    results = [_cr("A", Result.FAIL, hard=False)]
    findings = compare_to_baseline(results, Baseline(dataset_version="v1", results={"A": Result.PASS}))
    assert len(findings) == 1
    assert findings[0].is_hard_safety_invariant is False


def test_an_improvement_is_also_reported_never_hidden():
    results = [_cr("A", Result.PASS)]
    findings = compare_to_baseline(results, Baseline(dataset_version="v1", results={"A": Result.FAIL}))
    assert len(findings) == 1
    assert findings[0].current_result == Result.PASS


def test_a_brand_new_case_with_no_baseline_entry_is_not_a_regression():
    results = [_cr("NEW", Result.FAIL, hard=True)]
    findings = compare_to_baseline(results, empty_baseline("v1"))
    assert findings == []


# --- compare_metrics_to_baseline: Issue 4's own numeric drift ---


def test_unchanged_metrics_produce_no_drift():
    results = [_cr("RET-006", Result.PASS, metrics={"reciprocal_rank": 1.0})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    assert compare_metrics_to_baseline(results, baseline) == []


def test_degraded_reciprocal_rank_is_visible_even_though_outcome_stays_pass():
    """The exact scenario Issue 4 names: require_hit still satisfied
    (PASS), but the ranking itself got worse -- this must be visible."""
    results = [_cr("RET-006", Result.PASS, metrics={"reciprocal_rank": 0.5})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    outcome_findings = compare_to_baseline(results, baseline)
    drift = compare_metrics_to_baseline(results, baseline)
    assert outcome_findings == []  # outcome itself did NOT regress
    assert len(drift) == 1
    assert drift[0].baseline_value == 1.0
    assert drift[0].current_value == 0.5
    assert drift[0].delta == pytest.approx(-0.5)


def test_improved_metric_is_also_visible():
    results = [_cr("RET-006", Result.PASS, metrics={"reciprocal_rank": 1.0})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 0.5}})
    drift = compare_metrics_to_baseline(results, baseline)
    assert len(drift) == 1
    assert drift[0].delta == pytest.approx(0.5)


def test_missing_baseline_metrics_are_handled_explicitly_never_a_crash():
    """A case with no recorded baseline metrics at all (e.g. a
    non-retrieval case, or a case added before metrics existed) must
    be skipped cleanly, never raise and never fabricate a baseline of
    0.0."""
    results = [_cr("REM-002", Result.PASS, metrics={})]
    baseline = Baseline(dataset_version="v1", results={"REM-002": Result.PASS})  # no "metrics" entry for REM-002 at all
    assert compare_metrics_to_baseline(results, baseline) == []


def test_compare_metrics_to_baseline_itself_stays_narrowly_scoped():
    """`compare_metrics_to_baseline`'s OWN job is pure drift
    computation among metrics present in BOTH the baseline and the
    current result -- it still, correctly, reports no drift when a
    metric is entirely absent from the current run (there is nothing
    to compute a delta FROM). This is deliberately NOT where
    completeness is enforced -- see `apply_missing_metric_checks`
    below, which is the corrected behavior for the actual disappeared-
    metric scenario (two-final-fixes pass, Issue 1). A prior version
    of this test incorrectly treated this narrow, correct behavior as
    if it were itself sufficient to catch a disappeared metric -- it
    is not, and this test now says so explicitly."""
    results = [_cr("RET-006", Result.PASS, metrics={})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    assert compare_metrics_to_baseline(results, baseline) == []


# --- apply_missing_metric_checks: Issue 1's own corrected behavior ---


def test_disappeared_metric_downgrades_the_case_to_not_evaluated():
    """The exact scenario Issue 1 names: the scorer still reports
    PASS, but a metric the baseline recorded is simply gone from this
    run's own output -- must never look like a clean pass."""
    results = [_cr("RET-006", Result.PASS, metrics={})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    updated = apply_missing_metric_checks(results, baseline)
    assert len(updated) == 1
    assert updated[0].result == Result.NOT_EVALUATED
    assert "RET-006" in updated[0].detail
    assert "reciprocal_rank" in updated[0].detail


def test_disappeared_metric_is_never_fabricated_as_a_safety_violation():
    results = [_cr("RET-006", Result.PASS, metrics={}, hard=False)]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    updated = apply_missing_metric_checks(results, baseline)
    assert updated[0].result == Result.NOT_EVALUATED
    assert updated[0].is_hard_safety_invariant is False  # never upgraded/fabricated


def test_a_present_metric_that_merely_changed_value_is_not_downgraded():
    """Normal numeric drift (the metric is still THERE, just a
    different value) must never be confused with a disappeared one --
    that case stays PASS/FAIL as the scorer reported; only
    `compare_metrics_to_baseline` reports the (informational) delta."""
    results = [_cr("RET-006", Result.PASS, metrics={"reciprocal_rank": 0.5})]
    baseline = Baseline(dataset_version="v1", results={"RET-006": Result.PASS}, metrics={"RET-006": {"reciprocal_rank": 1.0}})
    updated = apply_missing_metric_checks(results, baseline)
    assert updated[0].result == Result.PASS


def test_a_case_with_no_baseline_metrics_at_all_is_returned_unchanged():
    """A brand-new case (or one that simply never had a recorded
    metric) must never be penalized for a metric it was never expected
    to report."""
    results = [_cr("NEW-CASE", Result.PASS, metrics={})]
    baseline = Baseline(dataset_version="v1", results={})  # no entry for NEW-CASE at all
    updated = apply_missing_metric_checks(results, baseline)
    assert updated[0].result == Result.PASS


def test_only_the_specifically_missing_metric_is_named_not_every_metric():
    results = [_cr("RET-006", Result.PASS, metrics={"hit_at_k": 1.0})]  # reciprocal_rank specifically disappeared
    baseline = Baseline(
        dataset_version="v1",
        results={"RET-006": Result.PASS},
        metrics={"RET-006": {"hit_at_k": 1.0, "reciprocal_rank": 1.0}},
    )
    updated = apply_missing_metric_checks(results, baseline)
    assert updated[0].result == Result.NOT_EVALUATED
    assert "reciprocal_rank" in updated[0].detail
    assert "hit_at_k" not in updated[0].detail  # only the MISSING metric is named, never every baseline metric


# --- write_baseline ---


def test_write_baseline_round_trips_results_and_metrics(tmp_path: pathlib.Path):
    path = tmp_path / "baseline.json"
    write_baseline(
        path,
        "v1",
        [_cr("A", Result.PASS, metrics={"m": 0.5}), _cr("B", Result.FAIL)],
    )
    loaded = json.loads(path.read_text())
    assert loaded["dataset_version"] == "v1"
    assert loaded["results"] == {"A": "PASS", "B": "FAIL"}
    assert loaded["metrics"] == {"A": {"m": 0.5}}  # B had no metrics -- never fabricated as {}

    baseline = load_baseline(path, "v1")
    assert baseline.results == {"A": Result.PASS, "B": Result.FAIL}
    assert baseline.metrics == {"A": {"m": 0.5}}
