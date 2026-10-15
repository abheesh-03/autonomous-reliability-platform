"""HTTP-contract-level tests for clients/control_plane.py, using
httpx.MockTransport (never a real network call) -- same convention
every other service in this platform already establishes."""

import httpx
import pytest

from agent_runtime_service.clients.control_plane import (
    ControlPlaneClient,
    ControlPlaneOutputError,
    ControlPlaneUnavailableError,
    IncidentNotFoundError,
)
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json


async def test_get_incident_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=incident_json())

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    incident = await client.get_incident(str(SAMPLE_INCIDENT_ID))
    assert incident.id == SAMPLE_INCIDENT_ID


async def test_get_incident_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "incident not found"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(IncidentNotFoundError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_get_incident_5xx_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneUnavailableError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_connection_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneUnavailableError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_malformed_shape_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totally": "wrong shape"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_non_json_response_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_output_error_never_leaks_the_raw_field_value():
    """Phase 7 correction round (finding #5): independent review
    reproduced a secret-shaped value from pydantic's own
    ValidationError string (which includes input_value verbatim)
    leaking through a raised exception's message. Proves the fix:
    a field whose value is a fake secret must never appear in the
    raised ControlPlaneOutputError's own str()."""

    def handler(request: httpx.Request) -> httpx.Response:
        # 'severity' fails its Literal validation -- pydantic's
        # ValidationError would normally quote this exact bad value in
        # its error string.
        body = incident_json()
        body["severity"] = "sk-THIS-SHOULD-NOT-BE-PERSISTED-OR-LEAKED"
        return httpx.Response(200, json=body)

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError) as exc_info:
        await client.get_incident(str(SAMPLE_INCIDENT_ID))
    assert "sk-THIS-SHOULD-NOT-BE-PERSISTED-OR-LEAKED" not in str(exc_info.value)
    assert str(exc_info.value) == "control-plane response did not match the expected response contract"


async def test_client_never_calls_a_write_http_verb_at_the_ast_level():
    """Belt-and-suspenders alongside test_read_only_guarantees.py's own
    module-wide AST check -- this client specifically."""
    import ast
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src"
        / "agent_runtime_service"
        / "clients"
        / "control_plane.py"
    )
    tree = ast.parse(path.read_text())
    write_verbs = {"post", "put", "patch", "delete"}
    found = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in write_verbs}
    assert not found, f"control_plane.py calls write HTTP verb(s): {found}"
