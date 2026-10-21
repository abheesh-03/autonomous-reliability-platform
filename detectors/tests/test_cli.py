"""Gate J tests: the CLI's exit codes and basic behavior, via real
subprocess invocations of `python -m detectors`."""

import json
import pathlib
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FIXTURE = _REPO_ROOT / "detectors" / "tests" / "fixtures" / "cascading_failure.json"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "detectors", *args], cwd=_REPO_ROOT, capture_output=True, text=True)


def test_verify_exits_zero():
    result = _run_cli(["verify"])
    assert result.returncode == 0
    assert "VERIFY OK" in result.stdout


def test_analyze_with_no_urls_is_a_validation_error():
    result = _run_cli(["analyze"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr


def test_analyze_with_unknown_service_is_a_validation_error():
    result = _run_cli(["analyze", "--service", "bogus-service", "--prometheus-url", "http://x.invalid"])
    assert result.returncode == 1
    assert "unknown service" in result.stderr


def test_replay_with_missing_fixture_is_a_validation_error():
    result = _run_cli(["replay", "--fixture", "/tmp/does-not-exist-detectors-fixture.json"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr


def test_replay_with_real_fixture_produces_deterministic_json(tmp_path):
    output_path = tmp_path / "report.json"
    result = _run_cli(["replay", "--fixture", str(_FIXTURE), "--output", str(output_path)])
    assert result.returncode == 0
    report = json.loads(output_path.read_text())
    assert len(report["findings"]) == 2
    # The fixture's Tempo edge has error_observed=True but no trace
    # attribution to either aggregate Prometheus anomaly finding, so
    # per the final evidence-integrity correction (Issue A) this stays
    # a tentative association, never a strong, asserted group.
    assert report["correlation_groups"] == []
    assert len(report["tentative_associations"]) == 1
    assert all(f["candidate_known_scenario_matches"] == [] for f in report["findings"])
    assert all(f["remediation_proposals"] == [] for f in report["findings"])


def test_replay_is_byte_identical_across_two_runs():
    """`replay` pins a fixed reference instant (never wall-clock
    time), so two runs of the exact same fixture must be byte-for-byte
    identical, including every timestamp field."""
    result1 = _run_cli(["replay", "--fixture", str(_FIXTURE)])
    result2 = _run_cli(["replay", "--fixture", str(_FIXTURE)])
    assert result1.returncode == 0 and result2.returncode == 0
    assert result1.stdout == result2.stdout
