import pytest
from pydantic import ValidationError

from evals.scoring.models import Case, CaseResult, Result, RunReport


def test_case_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case_id": "X",
                "dataset_version": "v1",
                "category": "c",
                "scenario_description": "d",
                "evaluation_mode": "citation",
                "provenance": {"kind": "synthetic", "notes": "n"},
                "ground_truth_rationale": "r",
                "input": {},
                "expected_outcome": {},
                "unexpected_extra_field": "should be rejected",
            }
        )


def test_case_rejects_unknown_evaluation_mode():
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case_id": "X",
                "dataset_version": "v1",
                "category": "c",
                "scenario_description": "d",
                "evaluation_mode": "not_a_real_mode",
                "provenance": {"kind": "synthetic", "notes": "n"},
                "ground_truth_rationale": "r",
                "input": {},
                "expected_outcome": {},
            }
        )


def test_run_report_exit_code_is_zero_when_clean():
    report = RunReport(
        dataset_version="v1",
        generated_at="2026-01-01T00:00:00+00:00",
        runtime_seconds=0.1,
        evaluated_case_count=1,
        passed=1,
        failed=0,
        not_evaluated=0,
        safety_violations=[],
        case_results=[
            CaseResult(case_id="A", category="c", evaluation_mode="citation", result=Result.PASS, is_hard_safety_invariant=False, detail="d")
        ],
    )
    assert report.exit_code() == 0


def test_run_report_exit_code_is_nonzero_on_any_failure():
    report = RunReport(
        dataset_version="v1",
        generated_at="2026-01-01T00:00:00+00:00",
        runtime_seconds=0.1,
        evaluated_case_count=1,
        passed=0,
        failed=1,
        not_evaluated=0,
        safety_violations=[],
        case_results=[
            CaseResult(case_id="A", category="c", evaluation_mode="citation", result=Result.FAIL, is_hard_safety_invariant=False, detail="d")
        ],
    )
    assert report.exit_code() == 1


def test_run_report_exit_code_is_nonzero_on_safety_violation_even_with_zero_failed():
    report = RunReport(
        dataset_version="v1",
        generated_at="2026-01-01T00:00:00+00:00",
        runtime_seconds=0.1,
        evaluated_case_count=1,
        passed=0,
        failed=0,
        not_evaluated=0,
        safety_violations=["A"],
        case_results=[],
    )
    assert report.exit_code() == 1


def test_not_evaluated_never_counts_as_passed():
    """A pure schema-level sanity check: NOT_EVALUATED and PASS are
    distinct enum members, so a caller cannot accidentally treat one
    as the other via truthiness or string equality with 'PASS'."""
    assert Result.NOT_EVALUATED != Result.PASS
    assert Result.NOT_EVALUATED.value != Result.PASS.value


# --- Issue 1: a required NOT_EVALUATED case must never yield success ---


def _report(*, passed=0, failed=0, not_evaluated=0, safety_violations=None, hard_result_missing=False, case_results=None):
    return RunReport(
        dataset_version="v1",
        generated_at="2026-01-01T00:00:00+00:00",
        runtime_seconds=0.1,
        evaluated_case_count=passed + failed + not_evaluated,
        passed=passed,
        failed=failed,
        not_evaluated=not_evaluated,
        safety_violations=safety_violations or [],
        case_results=case_results or [],
    )


def test_all_pass_exits_zero():
    assert _report(passed=15).exit_code() == 0


def test_required_hard_case_not_evaluated_is_nonzero():
    """Independently reproduces the exact scenario the review
    constructed: a hard safety case that could not run must still
    fail the run, even with zero `failed` and zero `safety_violations`
    -- a missing measurement is never silently fabricated into a
    detected violation, but it must still block success."""
    report = _report(
        passed=14,
        not_evaluated=1,
        case_results=[
            CaseResult(
                case_id="REM-002",
                category="remediation_safety",
                evaluation_mode="remediation_safety",
                result=Result.NOT_EVALUATED,
                is_hard_safety_invariant=True,
                detail="could not construct the real graph for this case",
            )
        ],
    )
    assert report.not_evaluated == 1
    assert report.safety_violations == []  # never fabricated
    assert report.exit_code() == 1


def test_required_soft_case_not_evaluated_is_also_nonzero():
    """A SOFT (non-safety) case that could not run is still an
    incomplete benchmark, never a passing one."""
    report = _report(
        passed=14,
        not_evaluated=1,
        case_results=[
            CaseResult(
                case_id="RET-006",
                category="retrieval",
                evaluation_mode="retrieval",
                result=Result.NOT_EVALUATED,
                is_hard_safety_invariant=False,
                detail="the real knowledge corpus was not found",
            )
        ],
    )
    assert report.exit_code() == 1


def test_hard_fail_is_nonzero():
    report = _report(
        passed=14,
        failed=1,
        safety_violations=["REM-012"],
        case_results=[
            CaseResult(case_id="REM-012", category="remediation_safety", evaluation_mode="remediation_safety", result=Result.FAIL, is_hard_safety_invariant=True, detail="d")
        ],
    )
    assert report.exit_code() == 1


def test_dataset_load_failure_shape_is_nonzero():
    report = _report(
        not_evaluated=1,
        safety_violations=["__harness_error__"],
        case_results=[
            CaseResult(case_id="__harness_error__", category="harness", evaluation_mode="citation", result=Result.NOT_EVALUATED, is_hard_safety_invariant=True, detail="dataset failed to load")
        ],
    )
    assert report.exit_code() == 1


# --- is_fully_successful(): gates --update-baseline writes ---


def test_is_fully_successful_true_when_clean():
    assert _report(passed=15).is_fully_successful() is True


def test_is_fully_successful_false_on_not_evaluated():
    assert _report(passed=14, not_evaluated=1).is_fully_successful() is False


def test_is_fully_successful_false_on_failed():
    assert _report(passed=14, failed=1).is_fully_successful() is False


def test_is_fully_successful_false_on_safety_violation():
    assert _report(passed=14, failed=0, safety_violations=["X"]).is_fully_successful() is False
