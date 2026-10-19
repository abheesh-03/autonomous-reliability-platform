"""`python -m evals.runner` -- the deterministic offline evaluation CLI.
See evals/README.md for full usage; `--help` lists every flag."""

import argparse
import asyncio
import pathlib
import sys
import time
from datetime import UTC, datetime

from evals.runner.loader import CaseLoadError, load_cases
from evals.runner.manifest import ManifestError, load_manifest, validate_manifest_against_cases, validate_manifest_internal_consistency
from evals.runner.report import render_terminal_summary, write_json_report, write_markdown_report
from evals.scoring import score_case
from evals.scoring.models import Case, CaseResult, Result, RunReport
from evals.scoring.real_model import (
    MAX_REAL_MODEL_CASES,
    real_model_is_available,
    real_model_run_metadata,
    score_citation_case_with_real_model,
)
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

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULT_CASES_DIR = _REPO_ROOT / "evals" / "cases" / "v1"
_DEFAULT_MANIFEST = _REPO_ROOT / "evals" / "datasets" / "v1" / "manifest.json"
_DEFAULT_BASELINE = _REPO_ROOT / "evals" / "datasets" / "v1" / "regression_baseline.json"
_DEFAULT_JSON_OUT = _REPO_ROOT / "evals" / "reports" / "latest.json"
_DEFAULT_MARKDOWN_OUT = _REPO_ROOT / "evals" / "reports" / "latest.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.runner",
        description="Deterministic offline evaluation for the AI reliability platform (Phase 10).",
    )
    parser.add_argument("--cases-dir", type=pathlib.Path, default=_DEFAULT_CASES_DIR)
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument("--manifest", type=pathlib.Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--case-id", action="append", default=None, help="run only this case id (repeatable)")
    parser.add_argument("--category", action="append", default=None, help="run only this category (repeatable)")
    parser.add_argument("--baseline", type=pathlib.Path, default=_DEFAULT_BASELINE)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "explicit, separate mode: record this run's own results (and metrics) as the new reviewed "
            "baseline. Only takes effect for a COMPLETE, unfiltered, manifest-validated, fully successful "
            "run (no FAIL, no NOT_EVALUATED, no safety violations) -- an incomplete/failed run never "
            "replaces the baseline, and this flag is REJECTED outright when combined with "
            "--case-id/--category (a filtered run must never overwrite the complete dataset baseline)"
        ),
    )
    parser.add_argument("--json-out", type=pathlib.Path, default=_DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", type=pathlib.Path, default=_DEFAULT_MARKDOWN_OUT)
    parser.add_argument("--quiet", action="store_true", help="suppress the terminal summary (reports are still written)")
    parser.add_argument(
        "--real-model",
        action="store_true",
        help=(
            "OPTIONAL, explicitly opt-in: in addition to the deterministic offline run, re-run a bounded "
            f"subset (up to {MAX_REAL_MODEL_CASES}) of citation-mode cases against a REAL configured LLM "
            "provider (never used by default, never required for CI, reported separately from the "
            "deterministic safety/offline results -- see evals/README.md)"
        ),
    )
    return parser


def _select_cases(cases: list[Case], case_ids: list[str] | None, categories: list[str] | None) -> list[Case]:
    selected = cases
    if case_ids is not None:
        wanted = set(case_ids)
        selected = [c for c in selected if c.case_id in wanted]
    if categories is not None:
        wanted_categories = set(categories)
        selected = [c for c in selected if c.category in wanted_categories]
    return selected


def _validate_selectors(cases: list[Case], case_ids: list[str] | None, categories: list[str] | None) -> list[str]:
    """Issue 2: an explicitly requested --case-id/--category that does
    not exist anywhere in the loaded dataset is an EXPLICIT ERROR,
    never a silent "selected nothing, exit 0". Returns a list of
    error strings (empty if every requested selector is real)."""
    errors: list[str] = []
    if case_ids is not None:
        known_ids = {c.case_id for c in cases}
        for requested in case_ids:
            if requested not in known_ids:
                errors.append(f"--case-id {requested!r} does not exist in the loaded dataset")
    if categories is not None:
        known_categories = {c.category for c in cases}
        for requested in categories:
            if requested not in known_categories:
                errors.append(f"--category {requested!r} does not exist in the loaded dataset")
    return errors


async def _run_all(cases: list[Case]) -> list[CaseResult]:
    results = []
    for case in cases:
        results.append(await score_case(case))
    return results


async def _run_real_model(cases: list[Case]) -> list[CaseResult]:
    results = []
    for case in cases:
        result = await score_citation_case_with_real_model(case)
        results.append(result.model_copy(update={"case_id": f"{result.case_id}::real-model"}))
    return results


def _failure_report(dataset_version: str, started: float, detail: str) -> RunReport:
    """Builds a single, synthetic, always-nonzero-exit RunReport for
    every harness-level failure mode that happens BEFORE case scoring
    can even begin (dataset load failure, manifest inconsistency/drift,
    an unknown explicitly-requested selector, an empty selection, a
    missing/malformed required baseline) -- one shared shape so none
    of these paths can accidentally diverge from "must fail closed"."""
    return RunReport(
        dataset_version=dataset_version,
        generated_at=datetime.now(UTC).isoformat(),
        runtime_seconds=time.monotonic() - started,
        evaluated_case_count=0,
        passed=0,
        failed=0,
        not_evaluated=1,
        safety_violations=["__harness_error__"],
        case_results=[
            CaseResult(
                case_id="__harness_error__",
                category="harness",
                evaluation_mode="citation",
                result=Result.NOT_EVALUATED,
                is_hard_safety_invariant=True,
                detail=detail,
            )
        ],
        limitations=[f"this run could not be completed: {detail}"],
    )


def run(argv: list[str] | None = None) -> RunReport:
    """Runs the full deterministic offline evaluation and returns the
    RunReport -- the function `tests/test_runner_cli.py` and other
    callers import directly, so the CLI's own argument parsing stays
    the only place that touches `sys.argv`/writes files/calls
    `sys.exit`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    started = time.monotonic()
    is_full_run = args.case_id is None and args.category is None

    # Issue 2 (two-final-fixes pass): --update-baseline may NEVER be
    # combined with a filter -- a single-case/category run must never
    # overwrite the complete dataset's own reviewed baseline. Checked
    # FIRST, before any file is even opened, so the existing baseline
    # is provably left byte-for-byte unchanged on rejection.
    if args.update_baseline and not is_full_run:
        report = _failure_report(
            args.dataset_version,
            started,
            "--update-baseline cannot be combined with --case-id/--category -- a filtered run must never "
            "overwrite the complete dataset's own reviewed baseline; run --update-baseline with no filters",
        )
        _write_and_print(report, args)
        return report

    try:
        cases = load_cases(args.cases_dir, dataset_version=args.dataset_version)
    except CaseLoadError as exc:
        # A dataset that cannot even be loaded is reported as a single
        # NOT_EVALUATED/safety-violation result, never silently treated
        # as "0 cases, exit 0" -- an empty/broken dataset must never
        # look like a clean pass.
        report = _failure_report(args.dataset_version, started, f"dataset failed to load: {exc}")
        _write_and_print(report, args)
        return report

    # Manifest internal consistency (Issue 3) is checked for EVERY run,
    # filtered or not -- it costs nothing and depends on no case file,
    # and an authoring bug there (categories not summing to total_cases)
    # is wrong regardless of what subset is being run.
    try:
        manifest = load_manifest(args.manifest)
        validate_manifest_internal_consistency(manifest)
        if is_full_run:
            # Full-dataset completeness (Issue 2/3): only required when
            # NOT deliberately filtering -- a subset run is never held
            # to "must cover the whole dataset".
            validate_manifest_against_cases(manifest, cases, args.dataset_version)
    except ManifestError as exc:
        report = _failure_report(args.dataset_version, started, f"manifest validation failed: {exc}")
        _write_and_print(report, args)
        return report

    selector_errors = _validate_selectors(cases, args.case_id, args.category)
    if selector_errors:
        report = _failure_report(args.dataset_version, started, "; ".join(selector_errors))
        _write_and_print(report, args)
        return report

    selected = _select_cases(cases, args.case_id, args.category)
    if not selected:
        report = _failure_report(
            args.dataset_version, started, "the requested --case-id/--category selection matched zero cases"
        )
        _write_and_print(report, args)
        return report

    # Strict baseline loading (Issue 1/4): a missing or malformed
    # required baseline must NEVER silently become an empty one for an
    # ORDINARY run. `--update-baseline`'s own bootstrap path is the
    # ONLY caller allowed to treat a MISSING (never malformed, never
    # wrong-version) baseline as "start from empty".
    try:
        baseline = load_baseline(args.baseline, args.dataset_version)
    except BaselineMissingError as exc:
        if args.update_baseline:
            baseline = empty_baseline(args.dataset_version)
        else:
            report = _failure_report(args.dataset_version, started, f"required baseline unavailable: {exc}")
            _write_and_print(report, args)
            return report
    except BaselineError as exc:
        report = _failure_report(args.dataset_version, started, f"required baseline is invalid: {exc}")
        _write_and_print(report, args)
        return report

    offline_results = asyncio.run(_run_all(selected))

    # Issue 1 (two-final-fixes pass): a metric the baseline recorded
    # for a case, but which this run's own scorer no longer reports at
    # all, is an INCOMPLETE measurement -- downgraded to NOT_EVALUATED
    # here, BEFORE any count below is computed, so it fails the run
    # through the exact same exit_code() path every other incomplete
    # measurement already does. Never manufactures a 0.0 value, never
    # added to safety_violations (that stays reserved for a genuinely
    # DETECTED hard-FAIL).
    offline_results = apply_missing_metric_checks(offline_results, baseline)

    # These summary counts are deliberately computed from the
    # DETERMINISTIC OFFLINE results ONLY -- real-model results (if
    # --real-model is requested below) are appended to the report's
    # own `case_results` list afterward for visibility, but must never
    # shift `evaluated_case_count`/passed/failed/safety_violations,
    # since a stochastic real-model observation is not a safety gate.
    passed = sum(1 for r in offline_results if r.result == Result.PASS)
    failed = sum(1 for r in offline_results if r.result == Result.FAIL)
    not_evaluated = sum(1 for r in offline_results if r.result == Result.NOT_EVALUATED)
    safety_violations = [r.case_id for r in offline_results if r.is_hard_safety_invariant and r.result == Result.FAIL]

    regression_findings = compare_to_baseline(offline_results, baseline)
    metric_drift = compare_metrics_to_baseline(offline_results, baseline)
    case_results = list(offline_results)

    limitations = [
        "retrieval metrics use the deterministic LOCAL lexical embedding provider, never the real "
        "semantic OpenAI embedding model actually configured in production -- see evals/README.md.",
        "remediation-safety cases exercise agent-runtime-service's real graph logic with fake "
        "control-plane/tool-gateway doubles (InMemorySaver, no database) -- control-plane's own "
        "atomic approve/reject transaction safety is proven separately by its own real-database test, "
        "never re-proven here.",
        "adversarial_deterministic cases prove only that hostile text is rendered as escaped, inert "
        "data -- they prove nothing about a real LLM's actual susceptibility to an injected "
        "instruction; see the optional real-model mode for that distinct, separate question.",
        "metric_drift is a purely informational, soft signal -- it never gates CI and carries no "
        "invented accuracy threshold; only PASS/FAIL/NOT_EVALUATED outcomes and hard safety "
        "invariants ever affect this run's own exit code.",
    ]
    if not_evaluated:
        limitations.append(
            f"{not_evaluated} case(s) were NOT_EVALUATED (a required measurement could not be taken) -- "
            "this alone makes the run incomplete and fails it, never counted as a pass."
        )
    if not is_full_run:
        limitations.append(
            "this was a FILTERED (--case-id/--category) run -- full-dataset manifest completeness was "
            "intentionally not checked; run with no filters for the complete-dataset guarantee."
        )

    real_provider_metadata: dict[str, str] | None = None
    if args.real_model:
        available, reason = real_model_is_available()
        if not available:
            limitations.append(f"--real-model was requested but is not available: {reason}")
        else:
            citation_cases = [c for c in selected if c.evaluation_mode == "citation"][:MAX_REAL_MODEL_CASES]
            real_model_results = asyncio.run(_run_real_model(citation_cases))
            # Appended as SEPARATE, clearly-marked case results -- never
            # merged into the deterministic passed/failed/safety_violations
            # counts above, since a stochastic real-model citation check
            # is not a safety invariant and must never gate CI or this
            # run's own exit code.
            case_results = case_results + real_model_results
            real_provider_metadata = real_model_run_metadata()
            limitations.append(
                f"real-model results ({len(real_model_results)} case(s), suffixed '::real-model') are reported "
                "separately and never counted toward passed/failed/safety_violations above -- a real model's "
                "output is stochastic and this is a quality observation, never a safety gate."
            )

    report = RunReport(
        dataset_version=args.dataset_version,
        generated_at=datetime.now(UTC).isoformat(),
        runtime_seconds=time.monotonic() - started,
        evaluated_case_count=len(offline_results),
        passed=passed,
        failed=failed,
        not_evaluated=not_evaluated,
        safety_violations=safety_violations,
        case_results=case_results,
        regression_findings=regression_findings,
        metric_drift=metric_drift,
        limitations=limitations,
        real_provider=real_provider_metadata,
    )

    if args.update_baseline:
        if report.is_fully_successful():
            write_baseline(args.baseline, args.dataset_version, offline_results)
        else:
            # Explicit, validated operation (final correction pass's own
            # requirement): an incomplete/failed run must NEVER replace
            # the reviewed baseline as though it were a clean reference
            # run. Recorded in the report, never done silently.
            report.limitations.append(
                "--update-baseline was requested but this run was NOT fully successful "
                "(failed/not_evaluated/safety_violations present) -- the existing baseline file was left "
                "unchanged."
            )

    _write_and_print(report, args)
    return report


def _write_and_print(report: RunReport, args: argparse.Namespace) -> None:
    write_json_report(report, args.json_out)
    write_markdown_report(report, args.markdown_out)
    if not args.quiet:
        print(render_terminal_summary(report))  # noqa: T201 -- this IS the terminal-output feature


def main(argv: list[str] | None = None) -> int:
    report = run(argv)
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
