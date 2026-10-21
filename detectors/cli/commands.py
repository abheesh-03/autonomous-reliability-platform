"""Gate J: the `python -m detectors` CLI.

  analyze  -- LIVE mode: connects to real (or explicitly-overridden)
              Prometheus/Tempo/control-plane endpoints and runs the
              unified pipeline. Any endpoint URL omitted means that
              stage's checks are honestly reported as NOT EXECUTED
              (never silently skipped) -- partial results are still
              produced and still exit 0.
  replay   -- SYNTHETIC mode: runs the SAME real pipeline code fully
              offline against a JSON fixture (see
              detectors/cli/fixture_loader.py) -- no network call is
              ever made.
  verify   -- a bounded, OFFLINE internal self-check (service
              allowlist, schema wiring) -- NOT the full test suite
              (see `make detectors-validate` for that).

A manually triggered `analyze`/`replay` run is a POINT-IN-TIME check,
never continuous autonomous monitoring -- this CLI has no daemon mode,
no scheduler, and no background loop in this round (see Gate J's own
"document that distinction" requirement, and the architecture doc).

Exit codes: 0 on a successfully produced report (even if every
individual check inside it reports INSUFFICIENT_DATA/
TELEMETRY_UNAVAILABLE -- that is an honest result, not a CLI failure);
1 on an actual usage/validation/operational error (no client
configured at all, a malformed fixture, an unknown --service).
"""

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import UTC, datetime

from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.clients.prometheus_client import ALLOWED_SERVICES, PrometheusClient
from detectors.clients.tempo_client import TempoClient
from detectors.cli.fixture_loader import FixtureError, load_fixture_clients
from detectors.pipeline.orchestrator import PipelineConfig
from detectors.pipeline.run import PipelineReport, run_pipeline


# A fixed, deterministic reference instant for `replay` -- NEVER
# wall-clock time. `replay` is Phase 11B's explicitly offline/
# deterministic mode (Gate F: "keep output deterministic for fixed
# inputs"); using datetime.now() here would make finding_id/window
# values differ between two runs of the exact same fixture, which
# would silently defeat that requirement. `analyze` (live mode) always
# uses real wall-clock time instead, since it queries real current
# telemetry.
_DETERMINISTIC_REPLAY_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _report_to_dict(report: PipelineReport) -> dict:
    return {
        "findings": [f.model_dump(mode="json") for f in report.findings],
        "anomaly_results": [r.model_dump(mode="json") for r in report.anomaly_results],
        "dependency_graph": report.dependency_graph.model_dump(mode="json") if report.dependency_graph else None,
        "propagation_paths": [p.model_dump(mode="json") for p in report.propagation_paths],
        "invariant_reports": [r.model_dump(mode="json") for r in report.invariant_reports],
        "correlation_groups": [g.model_dump(mode="json") for g in report.correlation_groups],
        "tentative_associations": [t.model_dump(mode="json") for t in report.tentative_associations],
        "checks_executed": report.checks_executed,
        "checks_not_executed": [{"check": name, "reason": reason} for name, reason in report.checks_not_executed],
        "summary": report.summary,
    }


def _emit(report: PipelineReport, output: pathlib.Path | None) -> None:
    payload = json.dumps(_report_to_dict(report), indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n")
        print(f"wrote machine-readable report -> {output}", file=sys.stderr)
    else:
        print(payload)
    print("", file=sys.stderr)
    print(report.summary, file=sys.stderr)


def _cmd_analyze(args: argparse.Namespace) -> int:
    services = tuple(args.service) if args.service else tuple(sorted(ALLOWED_SERVICES))
    unknown = [s for s in services if s not in ALLOWED_SERVICES]
    if unknown:
        print(f"VALIDATION ERROR: unknown service(s) {unknown} -- allowed: {sorted(ALLOWED_SERVICES)}", file=sys.stderr)
        return 1

    prometheus_client = PrometheusClient(args.prometheus_url) if args.prometheus_url else None
    tempo_client = TempoClient(args.tempo_url) if args.tempo_url else None
    control_plane_client = ControlPlaneClient(args.control_plane_url) if args.control_plane_url else None

    if prometheus_client is None and tempo_client is None and control_plane_client is None:
        print(
            "VALIDATION ERROR: at least one of --prometheus-url/--tempo-url/--control-plane-url is required "
            "for 'analyze' (live mode) -- use 'replay --fixture ...' for a fully offline run",
            file=sys.stderr,
        )
        return 1

    config = PipelineConfig(services=services)
    try:
        report = asyncio.run(
            run_pipeline(
                prometheus_client=prometheus_client,
                tempo_client=tempo_client,
                control_plane_client=control_plane_client,
                config=config,
            )
        )
    except Exception as exc:  # noqa: BLE001 -- a safe, non-leaking top-level error message, never a raw traceback with secrets
        print(f"OPERATIONAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _emit(report, args.output)
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    try:
        prometheus_client, tempo_client, control_plane_client = load_fixture_clients(
            args.fixture, reference_now=_DETERMINISTIC_REPLAY_NOW
        )
    except FixtureError as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        report = asyncio.run(
            run_pipeline(
                prometheus_client=prometheus_client,
                tempo_client=tempo_client,
                control_plane_client=control_plane_client,
                now=_DETERMINISTIC_REPLAY_NOW,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"OPERATIONAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _emit(report, args.output)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """A bounded, fully offline sanity check -- never the full test
    suite, never a network call."""
    problems: list[str] = []
    if not ALLOWED_SERVICES:
        problems.append("ALLOWED_SERVICES is empty")

    from detectors.pipeline.findings import _DETECTOR_TO_FAMILY
    from catalog.registry.detector_families import get_detector_family

    for detector_id, family_id in _DETECTOR_TO_FAMILY.items():
        if family_id is None:
            continue
        if get_detector_family(family_id) is None:
            problems.append(f"detector {detector_id!r} references unregistered family {family_id!r}")

    if problems:
        print("VERIFY FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"VERIFY OK: {len(ALLOWED_SERVICES)} allowlisted service(s), detector-family wiring consistent")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m detectors", description="Phase 11B autonomous failure discovery CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_analyze = subparsers.add_parser("analyze", help="LIVE mode: run the pipeline against real endpoints")
    p_analyze.add_argument("--service", action="append", help="repeatable; defaults to all allowlisted services")
    p_analyze.add_argument("--prometheus-url", default=None)
    p_analyze.add_argument("--tempo-url", default=None)
    p_analyze.add_argument("--control-plane-url", default=None)
    p_analyze.add_argument("--output", type=pathlib.Path, default=None)
    p_analyze.set_defaults(func=_cmd_analyze)

    p_replay = subparsers.add_parser("replay", help="SYNTHETIC mode: run the pipeline fully offline against a JSON fixture")
    p_replay.add_argument("--fixture", type=pathlib.Path, required=True)
    p_replay.add_argument("--output", type=pathlib.Path, default=None)
    p_replay.set_defaults(func=_cmd_replay)

    p_verify = subparsers.add_parser("verify", help="bounded offline internal self-check")
    p_verify.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
