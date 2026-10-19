"""Regression comparison -- Gate C requirement E, extended by the
final independent-review correction pass to also track numeric metric
drift (Issue 4), and to load the baseline STRICTLY (Issue 1/4: a
missing or malformed required baseline must never silently become an
empty one).

Two independent comparisons, kept deliberately separate:
  - `compare_to_baseline`: PASS/FAIL/NOT_EVALUATED OUTCOME changes.
    A regressed HARD safety invariant here always fails the overall
    run (see RunReport.exit_code()).
  - `compare_metrics_to_baseline`: numeric METRIC drift (e.g. a
    retrieval reciprocal_rank dropping). Purely informational -- never
    gates CI, never an invented accuracy threshold, surfaced in both
    the JSON and Markdown reports so a ranking regression can never be
    invisible merely because the case's own hit/miss outcome didn't
    change.
"""

import json
import pathlib

from evals.scoring.models import Baseline, CaseResult, MetricDrift, RegressionFinding, Result


class BaselineError(Exception):
    """A baseline file exists but is malformed, or declares a
    dataset_version that does not match the run being evaluated --
    NEVER silently treated as "no baseline" (that would make a
    required regression comparison silently vanish)."""


class BaselineMissingError(BaselineError):
    """The baseline file does not exist at all. For an ORDINARY run
    (not `--update-baseline`), this is still a hard failure -- a
    required baseline must exist and be used, never silently
    skipped. `--update-baseline`'s own bootstrap path is the ONLY
    caller that may legitimately treat this one specific error as
    "start from an empty baseline" (see runner/cli.py)."""


def load_baseline(path: pathlib.Path, expected_dataset_version: str) -> Baseline:
    """Loads and validates the versioned regression baseline. Raises
    `BaselineMissingError` if the file does not exist, or `BaselineError`
    for malformed JSON, a schema mismatch, or a `dataset_version` that
    does not match `expected_dataset_version` -- every one of these is
    a hard failure for a normal run; see `runner/cli.py` for the one,
    explicit, `--update-baseline`-only exception."""
    if not path.exists():
        raise BaselineMissingError(f"required regression baseline not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline at {path} is not valid JSON: {exc}") from exc
    try:
        baseline = Baseline.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise BaselineError(f"baseline at {path} does not match the Baseline schema: {exc}") from exc
    if baseline.dataset_version != expected_dataset_version:
        raise BaselineError(
            f"baseline at {path} is for dataset_version={baseline.dataset_version!r}, but this run is "
            f"evaluating dataset_version={expected_dataset_version!r}"
        )
    return baseline


def empty_baseline(dataset_version: str) -> Baseline:
    """Used ONLY by `--update-baseline`'s own bootstrap path when no
    baseline file exists yet -- never used for an ordinary run."""
    return Baseline(dataset_version=dataset_version, results={}, metrics={})


def compare_to_baseline(case_results: list[CaseResult], baseline: Baseline) -> list[RegressionFinding]:
    """Compares PASS/FAIL/NOT_EVALUATED OUTCOMES only. A changed
    result is reported regardless of direction (a case that newly
    PASSES is reported too, not just a newly-FAILING one -- hiding an
    improvement would be just as dishonest as hiding a regression)."""
    findings: list[RegressionFinding] = []
    for case_result in case_results:
        baseline_result = baseline.results.get(case_result.case_id)
        if baseline_result is None:
            continue  # a brand-new case has no prior baseline to regress against
        if baseline_result == case_result.result:
            continue
        findings.append(
            RegressionFinding(
                case_id=case_result.case_id,
                baseline_result=baseline_result,
                current_result=case_result.result,
                is_hard_safety_invariant=case_result.is_hard_safety_invariant,
                detail=(
                    f"{case_result.case_id}: baseline was {baseline_result.value}, now "
                    f"{case_result.result.value} -- {case_result.detail}"
                ),
            )
        )
    return findings


def apply_missing_metric_checks(case_results: list[CaseResult], baseline: Baseline) -> list[CaseResult]:
    """Two-final-fixes correction pass, Issue 1: if the baseline
    recorded a metric for a given case, THIS run's own scorer must
    still report it. A metric that silently disappeared (e.g. a
    scorer regression, a code change that stopped computing it) is an
    INCOMPLETE measurement, never a passing benchmark -- it must never
    be quietly skipped by `compare_metrics_to_baseline` alone (that
    function's own narrow job is drift computation among metrics
    present in BOTH places, and stays unchanged).

    Minimal, non-redundant fix: downgrades the affected case's own
    `result` to NOT_EVALUATED here, BEFORE the caller computes
    pass/fail/not_evaluated counts -- reusing the exact same
    NOT_EVALUATED/`exit_code()` machinery every other incomplete
    measurement already goes through (final correction pass #1's own
    fix), rather than inventing a second, parallel error framework.
    Never manufactures a numeric value for the missing metric, and
    never adds the case to `safety_violations` (that set is reserved
    for a genuinely DETECTED hard-FAIL, never an unavailable
    measurement). A case with no recorded baseline metrics at all
    (brand-new, or never had one) is returned unchanged.
    """
    updated: list[CaseResult] = []
    for case_result in case_results:
        baseline_metrics = baseline.metrics.get(case_result.case_id)
        if not baseline_metrics:
            updated.append(case_result)
            continue
        missing = sorted(name for name in baseline_metrics if name not in case_result.metrics)
        if not missing:
            updated.append(case_result)
            continue
        updated.append(
            case_result.model_copy(
                update={
                    "result": Result.NOT_EVALUATED,
                    "detail": (
                        f"INCOMPLETE MEASUREMENT: the baseline recorded metric(s) {missing} for "
                        f"{case_result.case_id!r}, but this run's own scorer no longer reports them -- "
                        f"never silently ignored, never scored as a pass (original detail: {case_result.detail})"
                    ),
                }
            )
        )
    return updated


def compare_metrics_to_baseline(case_results: list[CaseResult], baseline: Baseline) -> list[MetricDrift]:
    """Compares NUMERIC metrics only (Issue 4). A case with no
    recorded baseline metrics (either it never had one, or it is
    brand-new) is explicitly, safely skipped -- never a crash, never a
    fabricated "0.0 baseline". A metric the current run no longer
    reports (e.g. a case's own scoring module changed) is likewise
    skipped rather than compared against a hole. Every metric present
    in BOTH the baseline and the current result is compared exactly
    (these are deterministic offline measurements -- no fuzzy epsilon
    is needed or used)."""
    drifts: list[MetricDrift] = []
    for case_result in case_results:
        baseline_metrics = baseline.metrics.get(case_result.case_id)
        if not baseline_metrics:
            continue
        for metric_name, baseline_value in baseline_metrics.items():
            current_value = case_result.metrics.get(metric_name)
            if current_value is None:
                continue
            if current_value == baseline_value:
                continue
            drifts.append(
                MetricDrift(
                    case_id=case_result.case_id,
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    current_value=current_value,
                    delta=current_value - baseline_value,
                )
            )
    return drifts


def write_baseline(path: pathlib.Path, dataset_version: str, case_results: list[CaseResult]) -> None:
    """Writes/updates the recorded baseline -- an explicit, reviewable
    action (`--update-baseline` on the CLI), never done implicitly as
    a side effect of a normal evaluation run. Callers (runner/cli.py)
    must gate this on `RunReport.is_fully_successful()` themselves --
    this function has no way to know whether the run that produced
    `case_results` was itself clean, and never second-guesses its
    caller."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_version": dataset_version,
        "results": {cr.case_id: cr.result.value for cr in case_results},
        "metrics": {cr.case_id: cr.metrics for cr in case_results if cr.metrics},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
