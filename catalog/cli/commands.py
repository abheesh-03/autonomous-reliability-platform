"""Gate I: the `python -m catalog` CLI. Four subcommands, each with an
explicit, documented exit code:

  build     -- parse + normalize + MANDATORY structural-validate the source,
               write catalog.v1.json only if both succeed. Exit 0 on success,
               1 if the source fails to parse OR fails structural validation
               (BuildError either way -- see correction-round Issue 4).
  validate  -- parse, then run Gate B's structural validation and report
               every violation individually. Exit 0 if clean, 1 if any
               violation is found.
  audit     -- parse + MANDATORY structural-validate, then run Gate C's
               taxonomy review heuristics. Exit 0 unless the build/validation
               step fails (exit 1).
  coverage  -- parse + MANDATORY structural-validate, then compute Gate F's
               coverage report from an optional evidence file (JSON list of
               CapabilityEvidence). Exit 0 unless the build/validation step,
               evidence loading, or evidence verification setup fails
               (exit 1).

`build`/`audit`/`coverage` all go through `build_and_validate_catalog`
(never plain `build_catalog`) specifically so that none of them can
ever write an artifact for a catalog that parsed but failed structural
validation (e.g. a missing scenario block) -- only `validate` itself
calls `build_catalog` directly, so it can report every violation
individually rather than a single collapsed `BuildError` message.

Output classification (version-controlled vs. ignored local report): `build`
and `audit` write to their DEFAULT paths under `catalog/build/` by default,
which are version-controlled artifacts reviewed like any other generated,
deterministic file. Any `--output` override to a different path is always
treated as an ignored local report (see `.gitignore`'s `catalog/build/local/`
and `*.local.json` entries) -- this module never decides that for the caller,
it only ever writes where it's told.
"""

import argparse
import json
import pathlib
import sys

from catalog.coverage.tracker import CoverageError, compute_coverage
from catalog.importer.build import (
    BuildError,
    DEFAULT_BUILD_OUTPUT,
    DEFAULT_SOURCE_PATH,
    build_and_validate_catalog,
    build_catalog,
    write_catalog,
)
from catalog.reviews.audit import audit_catalog
from catalog.schemas.coverage import CapabilityEvidence
from catalog.validation.validate import validate_catalog

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_OUTPUT = _REPO_ROOT / "catalog" / "build" / "taxonomy_review.v1.json"
DEFAULT_COVERAGE_OUTPUT = _REPO_ROOT / "catalog" / "build" / "coverage_report.v1.json"


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        manifest = build_and_validate_catalog(source_path=args.source)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    write_catalog(manifest, args.output)
    print(f"built catalog: {manifest.scenario_count} scenarios across {manifest.domain_count} domains -> {args.output}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = build_catalog(source_path=args.source)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    report = validate_catalog(manifest)
    if report.ok:
        print(f"VALID: {manifest.scenario_count} scenarios, {manifest.domain_count} domains, zero violations")
        return 0
    print(f"INVALID: {len(report.violations)} violation(s):", file=sys.stderr)
    for v in report.violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        manifest = build_and_validate_catalog(source_path=args.source)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    findings = audit_catalog(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([f.model_dump(mode="json") for f in findings], indent=2) + "\n")
    by_heuristic: dict[str, int] = {}
    for f in findings:
        by_heuristic[f.heuristic_id] = by_heuristic.get(f.heuristic_id, 0) + 1
    print(f"audit complete: {len(findings)} REVIEW_REQUIRED finding(s) -> {args.output}")
    for heuristic_id, count in sorted(by_heuristic.items()):
        print(f"  - {heuristic_id}: {count}")
    print("note: every finding is advisory only -- none of this audit rewrites the catalog or authorizes a correction")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    try:
        manifest = build_and_validate_catalog(source_path=args.source)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1

    evidence: list[CapabilityEvidence] = []
    if args.evidence is not None:
        if not args.evidence.is_file():
            print(f"COVERAGE FAILED: evidence file not found: {args.evidence}", file=sys.stderr)
            return 1
        raw = json.loads(args.evidence.read_text())
        evidence = [CapabilityEvidence.model_validate(item) for item in raw]

    try:
        report = compute_coverage(manifest, evidence)
    except CoverageError as exc:
        print(f"COVERAGE FAILED: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n")
    print(f"coverage report ({report.total_scenarios} scenarios) -> {args.output}")
    print(
        f"evidence: {report.submitted_evidence_count} submitted, {report.verified_evidence_count} verified, "
        f"{report.unverifiable_evidence_count} unverifiable (no trustworthy checker yet), "
        f"{len(report.rejected_evidence)} rejected (fabricated/invalid)"
    )
    for dimension, count in report.dimension_counts.items():
        print(f"  - {dimension}: {count}/{report.total_scenarios}")
    if report.rejected_evidence:
        print("rejected evidence (never counted toward coverage):")
        for reason in report.rejected_evidence:
            print(f"  - {reason}")
    if report.unresolved_gaps:
        print("unresolved gaps:")
        for gap in report.unresolved_gaps:
            print(f"  - {gap}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m catalog", description="Phase 11A incident intelligence catalog CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_build = subparsers.add_parser("build", help="parse + normalize the source catalog")
    p_build.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE_PATH)
    p_build.add_argument("--output", type=pathlib.Path, default=DEFAULT_BUILD_OUTPUT)
    p_build.set_defaults(func=_cmd_build)

    p_validate = subparsers.add_parser("validate", help="build, then run Gate B structural validation")
    p_validate.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE_PATH)
    p_validate.set_defaults(func=_cmd_validate)

    p_audit = subparsers.add_parser("audit", help="build, then run Gate C taxonomy review heuristics")
    p_audit.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE_PATH)
    p_audit.add_argument("--output", type=pathlib.Path, default=DEFAULT_AUDIT_OUTPUT)
    p_audit.set_defaults(func=_cmd_audit)

    p_coverage = subparsers.add_parser("coverage", help="build, then compute Gate F coverage from optional evidence")
    p_coverage.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE_PATH)
    p_coverage.add_argument("--evidence", type=pathlib.Path, default=None, help="JSON file: a list of CapabilityEvidence")
    p_coverage.add_argument("--output", type=pathlib.Path, default=DEFAULT_COVERAGE_OUTPUT)
    p_coverage.set_defaults(func=_cmd_coverage)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
