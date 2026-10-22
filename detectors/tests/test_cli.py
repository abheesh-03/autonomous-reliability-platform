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


def test_analyze_with_partial_kube_args_is_a_validation_error():
    result = _run_cli(["analyze", "--kubeconfig", "/tmp/does-not-matter.yaml", "--kube-context", "some-context"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "--kubeconfig" in result.stderr


def test_analyze_publish_without_kube_args_is_a_validation_error():
    """Correction round (Issue 6B): --publish-k8s-findings-to-control-plane
    requires Kubernetes observation to be configured at all."""
    result = _run_cli(["analyze", "--control-plane-url", "http://x.invalid", "--publish-k8s-findings-to-control-plane"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "Kubernetes observation" in result.stderr


def test_analyze_publish_without_control_plane_url_is_a_validation_error():
    result = _run_cli([
        "analyze", "--kubeconfig", "/tmp/does-not-matter.yaml", "--kube-context", "some-context",
        "--kube-namespace", "reliability-sandbox", "--publish-k8s-findings-to-control-plane",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "--control-plane-url" in result.stderr


def test_analyze_publish_without_ingestion_token_env_var_is_a_validation_error(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN", raising=False)
    result = _run_cli([
        "analyze", "--kubeconfig", "/tmp/does-not-matter.yaml", "--kube-context", "some-context",
        "--kube-namespace", "reliability-sandbox", "--control-plane-url", "http://x.invalid",
        "--publish-k8s-findings-to-control-plane",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN" in result.stderr


def test_analyze_with_aws_observe_but_no_account_or_region_is_a_validation_error():
    result = _run_cli(["analyze", "--aws-observe"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "--aws-account-id" in result.stderr


def test_analyze_with_aws_account_and_region_but_no_observe_flag_is_a_validation_error():
    result = _run_cli(["analyze", "--aws-account-id", "123456789012", "--aws-region", "us-east-1"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr


def test_analyze_with_aws_observe_but_no_resource_enrollment_is_a_validation_error():
    result = _run_cli([
        "analyze", "--aws-observe", "--aws-account-id", "123456789012", "--aws-region", "us-east-1",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "resource enrollment" in result.stderr


def test_analyze_with_malformed_aws_account_id_is_a_validation_error():
    result = _run_cli([
        "analyze", "--aws-observe", "--aws-account-id", "not-a-valid-id", "--aws-region", "us-east-1",
        "--aws-enroll-cloudwatch-alarm", "my-alarm",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr


def test_analyze_publish_aws_without_aws_observation_is_a_validation_error():
    result = _run_cli(["analyze", "--control-plane-url", "http://x.invalid", "--publish-aws-findings-to-control-plane"])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "AWS observation" in result.stderr


def test_analyze_publish_aws_without_ingestion_token_env_var_is_a_validation_error(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_AWS_INGESTION_TOKEN", raising=False)
    result = _run_cli([
        "analyze", "--aws-observe", "--aws-account-id", "123456789012", "--aws-region", "us-east-1",
        "--aws-enroll-cloudwatch-alarm", "my-alarm", "--control-plane-url", "http://x.invalid",
        "--publish-aws-findings-to-control-plane",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "CONTROL_PLANE_AWS_INGESTION_TOKEN" in result.stderr


def test_analyze_with_malformed_ecs_service_enrollment_pair_is_a_validation_error():
    result = _run_cli([
        "analyze", "--aws-observe", "--aws-account-id", "123456789012", "--aws-region", "us-east-1",
        "--aws-enroll-ecs-service", "no-colon-here",
    ])
    assert result.returncode == 1
    assert "VALIDATION ERROR" in result.stderr
    assert "cluster:service" in result.stderr


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
    # `replay` never supplies a Kubernetes client -- these fields are
    # always present but empty (Phase 12A's observation stage is
    # live-analyze-only in this round, never part of the offline
    # fixture-replay path).
    assert report["k8s_collection_results"] == []
    assert report["k8s_findings"] == []


def test_replay_is_byte_identical_across_two_runs():
    """`replay` pins a fixed reference instant (never wall-clock
    time), so two runs of the exact same fixture must be byte-for-byte
    identical, including every timestamp field."""
    result1 = _run_cli(["replay", "--fixture", str(_FIXTURE)])
    result2 = _run_cli(["replay", "--fixture", str(_FIXTURE)])
    assert result1.returncode == 0 and result2.returncode == 0
    assert result1.stdout == result2.stdout
