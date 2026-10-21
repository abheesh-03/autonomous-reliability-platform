"""Gate H (SAFETY): consolidated negative controls proving the
detectors/ package stays read-only, never executes untrusted input,
never leaks secrets, and never invents catalog scenario matches or
coverage claims. Combines direct behavioral tests (real HTTP requests
captured via httpx.MockTransport) with source-level structural checks
where a behavioral test cannot exist (e.g. "this package never imports
a database driver")."""

import ast
import pathlib

import httpx
import pytest

from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.clients.prometheus_client import PrometheusClientError, error_count_query, p95_latency_query, total_count_query
from detectors.clients.tempo_client import TempoClient

_DETECTORS_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PY_FILES = [p for p in _DETECTORS_ROOT.rglob("*.py") if "tests" not in p.parts]


def _all_source_text() -> str:
    return "\n".join(p.read_text() for p in _PY_FILES)


# ---------------------------------------------------------------------
# no arbitrary PromQL / TraceQL / LogQL
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fn", [error_count_query, total_count_query, p95_latency_query])
def test_prometheus_query_templates_reject_any_service_outside_the_allowlist(fn):
    with pytest.raises(PrometheusClientError):
        fn("arbitrary-caller-supplied-service-name")


def test_tempo_search_has_no_caller_supplied_query_parameter():
    """TempoClient.search_window's only configurable inputs are the
    time window and a result-count bound -- no tag/query string
    parameter exists for a caller (or an LLM) to inject."""
    import inspect

    sig = inspect.signature(TempoClient.search_window)
    assert "tags" not in sig.parameters
    assert "query" not in sig.parameters


def test_no_loki_or_logql_client_exists_in_this_package():
    """This phase never built a Loki/LogQL client at all -- nothing to
    misuse."""
    assert not any(p.name == "loki_client.py" for p in _PY_FILES)
    assert "LogQL" not in _all_source_text()


# ---------------------------------------------------------------------
# no secret disclosure
# ---------------------------------------------------------------------


async def test_no_client_ever_sends_an_authorization_header():
    captured_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        if "/api/v1/incidents" in request.url.path:
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        if "/api/search" in request.url.path:
            return httpx.Response(200, json={"traces": []})
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    cp = ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))
    await cp.list_incidents()
    tempo = TempoClient("http://tempo.invalid", transport=httpx.MockTransport(handler))
    await tempo.search_window(0, 100)

    assert captured_headers
    for headers in captured_headers:
        assert "authorization" not in {k.lower() for k in headers}


def test_no_source_file_references_a_bearer_token_or_credential_constant():
    text = _all_source_text()
    for forbidden in ("Authorization", "Bearer ", "api_key", "API_KEY", "password", "PASSWORD"):
        assert forbidden not in text, f"unexpected credential-shaped string {forbidden!r} found in detectors/ source"


# ---------------------------------------------------------------------
# no database writes / no control-plane mutation / no remediation execution
# ---------------------------------------------------------------------


def test_no_database_driver_is_imported_anywhere_in_this_package():
    for name in ("psycopg", "asyncpg", "sqlalchemy", "sqlite3"):
        assert f"import {name}" not in _all_source_text() and f"from {name}" not in _all_source_text()


async def test_control_plane_client_only_ever_issues_get_requests():
    methods_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods_seen.append(request.method)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    cp = ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))
    await cp.list_incidents()
    await cp.list_all_incident_events("some-id")

    assert methods_seen
    assert all(m == "GET" for m in methods_seen)


def test_control_plane_client_has_no_patch_post_put_delete_method():
    for forbidden in ("def patch", "def post", "def put", "def delete", ".patch(", ".post(", ".put(", ".delete("):
        assert forbidden not in (_DETECTORS_ROOT / "clients" / "control_plane_client.py").read_text()


def test_no_tool_gateway_client_or_remediation_execution_path_exists():
    """No client module targets tool-gateway at all (a bare mention of
    the name in prose, e.g. explaining it emits no HTTP metrics, is
    fine -- an actual client/URL/import referencing it is not)."""
    assert not any(p.name == "tool_gateway_client.py" for p in _PY_FILES)
    for path in _PY_FILES:
        text = path.read_text()
        assert "TOOL_GATEWAY_URL" not in text
        assert "http://tool-gateway" not in text
    text = _all_source_text()
    for forbidden in ("subprocess", "os.system", "shell=True"):
        assert forbidden not in text, f"unexpected execution-shaped string {forbidden!r} found in detectors/ source"


def test_failure_finding_schema_itself_defaults_remediation_proposals_to_empty():
    from catalog.schemas.finding import FailureFinding

    assert FailureFinding.model_fields["remediation_proposals"].default_factory() == []


# ---------------------------------------------------------------------
# no unauthorized network targets
# ---------------------------------------------------------------------


async def test_all_requests_target_only_the_configured_base_url():
    targets = []

    def handler(request: httpx.Request) -> httpx.Response:
        targets.append(request.url.host)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    cp = ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))
    await cp.list_incidents()
    assert set(targets) == {"control-plane.invalid"}


# ---------------------------------------------------------------------
# no new scenario ID invented / no fabricated coverage
# ---------------------------------------------------------------------


def test_pipeline_findings_module_never_constructs_a_candidate_scenario_match():
    text = (_DETECTORS_ROOT / "pipeline" / "findings.py").read_text()
    assert "CandidateScenarioMatch" not in text


def test_no_detectors_module_imports_catalog_coverage_verification_bypass():
    """detectors/ must never reach into catalog's own verification
    boundary to fabricate a VERIFIED outcome -- it has no reason to
    import that module at all."""
    text = _all_source_text()
    assert "catalog.coverage.verification" not in text


def test_detectors_package_has_no_subprocess_or_eval_exec_calls():
    for path in _PY_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec"), f"{path}: unexpected {node.func.id}() call"
