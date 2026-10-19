"""Gate G security/no-mutation checks: the deterministic offline run
must never make a real network call, never require/expose a
credential, and never touch any backend service. Also proves
real-model mode's own double-gate fails closed when no real provider
is configured (the common/default case, including in CI)."""

import json
import pathlib

import httpx

from evals.runner.cli import run
from evals.scoring.real_model import real_model_is_available, score_citation_case_with_real_model
from evals.scoring.models import Result
from evals.tests.conftest import make_case, sample_evidence_package


def test_offline_mode_never_opens_a_real_network_connection(tmp_path: pathlib.Path, monkeypatch):
    # `run()` is itself synchronous (it calls asyncio.run() internally)
    # -- this must be a plain `def` test, never `async def`, or
    # pytest-asyncio's own event loop would make that inner
    # asyncio.run() raise "cannot be called from a running event loop".
    def _forbidden(*args, **kwargs):
        raise AssertionError("offline evaluation must never open a real network connection")

    # httpx is the transport openai/langgraph's own HTTP clients are
    # built on; patching its send path means ANY attempted real call
    # (accidental or otherwise) fails loudly instead of silently
    # succeeding or silently being skipped.
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", _forbidden)

    # Deliberately uses the DEFAULT (real, committed) --manifest/--baseline
    # paths, never a nonexistent temp one -- a missing baseline is now a
    # hard failure BEFORE scoring even runs (Issue 1/4's own fix), which
    # would make this test's own network-call assertion vacuously true
    # for the wrong reason (scoring never executed) rather than proving
    # what it claims.
    report = run(
        [
            "--cases-dir",
            str(pathlib.Path(__file__).resolve().parents[1] / "cases" / "v1"),
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.evaluated_case_count > 0  # confirms scoring actually ran, not short-circuited
    # If a network call had been attempted, the monkeypatched `_forbidden`
    # would have raised, and that case would be NOT_EVALUATED/FAIL with
    # an AssertionError in its own detail -- assert none did.
    assert not any("must never open a real network connection" in cr.detail for cr in report.case_results)


def test_json_and_markdown_reports_contain_no_credential_shaped_strings(tmp_path: pathlib.Path):
    report = run(
        [
            "--cases-dir",
            str(pathlib.Path(__file__).resolve().parents[1] / "cases" / "v1"),
            "--json-out",
            str(tmp_path / "out.json"),
            "--markdown-out",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )
    assert report.exit_code() == 0

    json_text = (tmp_path / "out.json").read_text()
    md_text = (tmp_path / "out.md").read_text()
    for forbidden in ("sk-", "Bearer ", "Authorization:", "PASSWORD", "_TOKEN="):
        assert forbidden not in json_text
        assert forbidden not in md_text


def test_real_model_mode_fails_closed_without_a_configured_provider(monkeypatch):
    monkeypatch.delenv("INVESTIGATOR_LLM_API_KEY", raising=False)
    monkeypatch.setenv("INVESTIGATOR_LLM_PROVIDER", "openai")
    available, reason = real_model_is_available()
    assert available is False
    assert "api_key" in reason.lower() or "API_KEY" in reason


async def test_real_model_mode_is_not_evaluated_not_a_pass_when_unavailable(monkeypatch):
    monkeypatch.delenv("INVESTIGATOR_LLM_API_KEY", raising=False)
    monkeypatch.setenv("INVESTIGATOR_LLM_PROVIDER", "openai")
    case = make_case(
        evaluation_mode="citation",
        input={"evidence_package": sample_evidence_package(), "retrieval_context": None, "provider_response_text": "{}"},
        expected_outcome={},
    )
    result = await score_citation_case_with_real_model(case)
    assert result.result == Result.NOT_EVALUATED


def test_stub_provider_mode_is_not_treated_as_a_real_model_invocation(monkeypatch):
    """INVESTIGATOR_LLM_PROVIDER=stub satisfies LLMSettings.configured,
    but makes no real call -- real_model_is_available() must still
    report False for this case, never letting 'stub happens to be
    configured' masquerade as 'a real provider was actually invoked'."""
    monkeypatch.setenv("INVESTIGATOR_LLM_PROVIDER", "stub")
    available, _reason = real_model_is_available()
    assert available is False


def test_remediation_safety_cases_never_touch_a_real_database_or_docker_socket():
    """Structural guarantee, not merely a runtime observation:
    evals/scoring/remediation_safety.py must never import psycopg's
    own connection machinery or anything docker-related."""
    source = pathlib.Path(__file__).resolve().parents[1].joinpath("scoring", "remediation_safety.py").read_text()
    assert "import psycopg" not in source
    assert "import docker" not in source
    assert "docker.from_env" not in source
    assert "AsyncPostgresSaver" not in source
