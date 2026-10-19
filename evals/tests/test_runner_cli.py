import json
import pathlib

from evals.runner.cli import run
from evals.scoring.models import Result
from evals.tests.conftest import sample_evidence_package

_PASSING_CASE = {
    "case_id": "T-PASS",
    "dataset_version": "test",
    "category": "citation",
    "scenario_description": "d",
    "evaluation_mode": "citation",
    "provenance": {"kind": "synthetic", "notes": "n"},
    "ground_truth_rationale": "r",
    "input": {
        "evidence_package": sample_evidence_package(),
        "retrieval_context": None,
        "provider_response_text": '{"summary": "x", "observations": [{"statement": "a", "evidence_ids": ["E1"]}], "hypotheses": [], "missing_evidence": [], "suggested_checks": []}',
    },
    "expected_outcome": {"min_surviving_observations": 1},
    "is_hard_safety_invariant": False,
}

_FAILING_CASE = {
    **_PASSING_CASE,
    "case_id": "T-FAIL",
    "expected_outcome": {"max_surviving_observations": 0},  # wrong -- E1 is real, so this must FAIL
    "is_hard_safety_invariant": True,
}

_NOT_EVALUATED_CASE = {
    **_PASSING_CASE,
    "case_id": "T-NOTEVAL",
    "input": {"evidence_package": {"not": "a real package"}, "provider_response_text": "{}"},
    "expected_outcome": {},
    "is_hard_safety_invariant": True,
}


def _write_cases(cases_dir: pathlib.Path, cases: list[dict]) -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (cases_dir / f"{case['case_id']}.json").write_text(json.dumps(case))


def _write_manifest_matching(manifest_path: pathlib.Path, cases: list[dict], dataset_version: str = "test") -> None:
    """A manifest that exactly matches the given case set -- used for
    FULL (unfiltered) run tests."""
    from collections import Counter

    categories = dict(Counter(c["category"] for c in cases))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_version": dataset_version,
                "total_cases": len(cases),
                "categories": categories,
                "case_ids": [c["case_id"] for c in cases],
            }
        )
    )


def _bootstrap_minimal_baseline(tmp_path: pathlib.Path, baseline_path: pathlib.Path) -> None:
    """Test setup only: creates a valid, minimal baseline file for
    dataset_version='test' via a genuinely separate, trivially
    passing, one-case full run with --update-baseline -- never via
    the --case-id/--category combination the two-final-fixes pass now
    rejects (Issue 2), and never via a run that includes a case this
    test file's own `_FAILING_CASE`/`_NOT_EVALUATED_CASE` would make
    unsuccessful. A baseline bootstrapped this way validates fine for
    ANY later run against dataset_version='test' -- every comparison
    function safely skips a case_id with no corresponding baseline
    entry."""
    bootstrap_dir = tmp_path / "_bootstrap_cases"
    bootstrap_manifest = tmp_path / "_bootstrap_manifest.json"
    _write_cases(bootstrap_dir, [_PASSING_CASE])
    _write_manifest_matching(bootstrap_manifest, [_PASSING_CASE])
    run(
        [
            "--cases-dir",
            str(bootstrap_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(bootstrap_manifest),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "_bootstrap.json"),
            "--markdown-out",
            str(tmp_path / "_bootstrap.md"),
            "--quiet",
        ]
    )


def _base_args(tmp_path: pathlib.Path, cases_dir: pathlib.Path, manifest_path: pathlib.Path) -> list[str]:
    baseline_path = tmp_path / "baseline.json"
    if not baseline_path.exists():
        _bootstrap_minimal_baseline(tmp_path, baseline_path)
    return [
        "--cases-dir",
        str(cases_dir),
        "--dataset-version",
        "test",
        "--manifest",
        str(manifest_path),
        "--baseline",
        str(baseline_path),
        "--json-out",
        str(tmp_path / "out.json"),
        "--markdown-out",
        str(tmp_path / "out.md"),
        "--quiet",
    ]


def test_run_reports_pass_and_fail_correctly(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _FAILING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE, _FAILING_CASE])

    report = run(_base_args(tmp_path, cases_dir, manifest_path))
    assert report.passed == 1
    assert report.failed == 1
    assert "T-FAIL" in report.safety_violations
    assert report.exit_code() == 1
    assert (tmp_path / "out.json").exists()
    assert (tmp_path / "out.md").exists()


def test_case_id_filter_runs_only_the_selected_case(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _FAILING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE, _FAILING_CASE])

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "T-PASS"])
    assert report.evaluated_case_count == 1
    assert report.passed == 1
    assert report.exit_code() == 0


def test_category_filter_runs_only_matching_cases(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--category", "citation"])
    assert report.evaluated_case_count == 1
    assert report.exit_code() == 0


def test_broken_dataset_directory_is_not_a_silent_clean_pass(tmp_path: pathlib.Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    report = run(
        [
            "--cases-dir",
            str(empty_dir),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert report.not_evaluated >= 1


# --- Issue 2: unknown selectors / empty selection ---


def test_unknown_case_id_filter_is_an_explicit_nonzero_error(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "DOES-NOT-EXIST"])
    assert report.exit_code() == 1
    assert "DOES-NOT-EXIST" in report.case_results[0].detail


def test_unknown_category_filter_is_an_explicit_nonzero_error(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--category", "no-such-category"])
    assert report.exit_code() == 1
    assert "no-such-category" in report.case_results[0].detail


def test_a_valid_but_mutually_exclusive_selector_combination_yields_nonzero(tmp_path: pathlib.Path):
    """Both selector VALUES are real, but their intersection is empty
    (T-PASS is not in the 'remediation_safety' category) -- the
    backstop empty-selection check must still catch this."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run(
        [*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "T-PASS", "--category", "remediation_safety"]
    )
    assert report.exit_code() == 1


# --- Issue 3: manifest completeness only enforced on FULL runs ---


def test_full_run_detects_a_case_missing_from_the_manifest(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _FAILING_CASE])
    # Manifest only knows about ONE of the two real case files.
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run(_base_args(tmp_path, cases_dir, manifest_path))  # no filters -> full run
    assert report.exit_code() == 1
    assert "manifest" in report.case_results[0].detail.lower()


def test_filtered_run_does_not_require_full_dataset_manifest_coverage(tmp_path: pathlib.Path):
    """A deliberately filtered subset run must NOT be held to 'cover
    the whole dataset' -- only full runs enforce manifest completeness."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _FAILING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])  # deliberately incomplete vs. disk

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "T-PASS"])
    assert report.exit_code() == 0  # the manifest's own incompleteness is irrelevant to this filtered run


def test_incorrect_manifest_category_count_fails_even_a_filtered_run(tmp_path: pathlib.Path):
    """Internal consistency (category counts summing to total_cases)
    is checked unconditionally -- even a filtered run must not proceed
    against a manifest that is wrong on its own terms."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    manifest_path.write_text(
        json.dumps({"dataset_version": "test", "total_cases": 1, "categories": {"citation": 2}})  # 2 != 1
    )
    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "T-PASS"])
    assert report.exit_code() == 1


# --- Issue 1: NOT_EVALUATED cases fail the run end to end ---


def test_not_evaluated_case_fails_the_whole_run(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _NOT_EVALUATED_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE, _NOT_EVALUATED_CASE])

    report = run(_base_args(tmp_path, cases_dir, manifest_path))
    assert report.not_evaluated == 1
    assert report.failed == 0
    assert report.safety_violations == []  # never fabricated as a detected violation
    assert report.exit_code() == 1


# --- Issue 4 / baseline strictness ---


def test_ordinary_run_without_update_baseline_requires_an_existing_baseline(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(tmp_path / "does-not-exist.json"),  # no --update-baseline this time
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert "baseline" in report.case_results[0].detail.lower()


def test_malformed_baseline_is_rejected_even_in_update_mode(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{not valid json")

    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1


def test_update_baseline_then_regression_and_metric_drift_detection(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])
    baseline_path = tmp_path / "baseline.json"

    first = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out1.json"),
            "--markdown-out",
            str(tmp_path / "out1.md"),
            "--quiet",
        ]
    )
    assert first.passed == 1
    assert baseline_path.exists()

    # Now swap the case to one that FAILs under the same case_id --
    # the regression must be detected against the just-recorded baseline.
    _write_cases(cases_dir, [{**_PASSING_CASE, "expected_outcome": {"max_surviving_observations": 0}}])
    second = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--json-out",
            str(tmp_path / "out2.json"),
            "--markdown-out",
            str(tmp_path / "out2.md"),
            "--quiet",
        ]
    )
    assert second.failed == 1
    assert len(second.regression_findings) == 1
    assert second.regression_findings[0].baseline_result == Result.PASS
    assert second.regression_findings[0].current_result == Result.FAIL


def test_update_baseline_refuses_to_replace_baseline_on_an_incomplete_run(tmp_path: pathlib.Path):
    """'Do not allow an incomplete/failed run to replace the reviewed
    baseline' -- a failing run with --update-baseline must leave any
    existing baseline file untouched."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])
    baseline_path = tmp_path / "baseline.json"

    # First, bootstrap a real, clean baseline.
    run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out1.json"),
            "--markdown-out",
            str(tmp_path / "out1.md"),
            "--quiet",
        ]
    )
    original_baseline_text = baseline_path.read_text()

    # Now run a BROKEN dataset with --update-baseline -- must refuse to overwrite.
    _write_cases(cases_dir, [_FAILING_CASE])
    _write_manifest_matching(manifest_path, [_FAILING_CASE])
    second = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out2.json"),
            "--markdown-out",
            str(tmp_path / "out2.md"),
            "--quiet",
        ]
    )
    assert second.exit_code() == 1
    assert baseline_path.read_text() == original_baseline_text  # untouched


# --- Two-final-fixes pass, Issue 2: --update-baseline rejects any filter ---


def test_update_baseline_combined_with_case_id_is_rejected(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    baseline_path = tmp_path / "baseline.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--case-id",
            "T-PASS",
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert "--update-baseline" in report.case_results[0].detail
    assert not baseline_path.exists()  # never written at all -- rejected before any file touch


def test_update_baseline_combined_with_category_is_rejected(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    baseline_path = tmp_path / "baseline.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--category",
            "citation",
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert not baseline_path.exists()


def test_filtered_update_baseline_leaves_an_existing_baseline_byte_for_byte_unchanged(tmp_path: pathlib.Path):
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    baseline_path = tmp_path / "baseline.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    # A real, existing, fully-valid baseline is already present (the
    # FULL 15-case-equivalent reference, in spirit).
    run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out1.json"),
            "--markdown-out",
            str(tmp_path / "out1.md"),
            "--quiet",
        ]
    )
    original_baseline_text = baseline_path.read_text()

    # A single-case filtered run must never be allowed to overwrite it.
    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--case-id",
            "T-PASS",
            "--json-out",
            str(tmp_path / "out2.json"),
            "--markdown-out",
            str(tmp_path / "out2.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert baseline_path.read_text() == original_baseline_text


def test_filtered_run_without_update_baseline_still_works_normally(tmp_path: pathlib.Path):
    """Normal filtered evaluation (no --update-baseline at all) must
    remain fully supported -- only the update-and-filter COMBINATION
    is rejected."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    _write_cases(cases_dir, [_PASSING_CASE, _FAILING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE, _FAILING_CASE])

    report = run([*_base_args(tmp_path, cases_dir, manifest_path), "--case-id", "T-PASS"])
    assert report.exit_code() == 0


# --- Two-final-fixes pass, Issue 1: a disappeared metric, end to end ---


def test_disappeared_retrieval_metric_fails_the_cli_even_though_the_scorer_itself_says_pass(tmp_path: pathlib.Path):
    """The exact end-to-end scenario the review asked for: a formerly
    present retrieval metric disappears from this run's own output
    while the underlying scorer still reports PASS (require_hit still
    satisfied) -- the CLI must still exit nonzero, never silently
    treat this as a clean benchmark."""
    cases_dir = tmp_path / "cases"
    manifest_path = tmp_path / "manifest.json"
    baseline_path = tmp_path / "baseline.json"
    _write_cases(cases_dir, [_PASSING_CASE])
    _write_manifest_matching(manifest_path, [_PASSING_CASE])

    # Bootstrap a baseline that claims T-PASS once reported a
    # "reciprocal_rank" metric (simulating a formerly-retrieval-mode
    # case, or a scorer that used to compute an extra metric) --
    # citation-mode's own real scorer never produces this metric, so
    # it is guaranteed absent from the CURRENT run's own output.
    run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--json-out",
            str(tmp_path / "out0.json"),
            "--markdown-out",
            str(tmp_path / "out0.md"),
            "--quiet",
        ]
    )
    baseline_data = json.loads(baseline_path.read_text())
    baseline_data.setdefault("metrics", {})["T-PASS"] = {"reciprocal_rank": 1.0}
    baseline_path.write_text(json.dumps(baseline_data))

    report = run(
        [
            "--cases-dir",
            str(cases_dir),
            "--dataset-version",
            "test",
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_path),
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 1
    assert report.not_evaluated == 1
    assert report.safety_violations == []  # never fabricated as a detected violation
    t_pass_result = next(cr for cr in report.case_results if cr.case_id == "T-PASS")
    assert t_pass_result.result == Result.NOT_EVALUATED
    assert "reciprocal_rank" in t_pass_result.detail
