"""HTTP-contract-level tests for clients/tool_gateway.py, using
httpx.MockTransport (never a real network call).

Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B: when a
verified actor is bound for the current request, execute() must relay
a derived X-Service-Assertion naming that EXACT actor, ADDITIVE to
(never a replacement for) the existing TOOL_GATEWAY_EXECUTION_TOKEN
Bearer auth -- tool-gateway forwards this header, unverified by
itself, to its own GetProposal/StartExecution/RecordExecutionResult
calls against control-plane (see
services/tool-gateway/internal/api/execute.go), which is the only
party that actually verifies it."""

import httpx
import jwt
import pytest

from agent_runtime_service.authz import ActorContext, bind_actor
from agent_runtime_service.clients.tool_gateway import ToolGatewayClient, ToolGatewayUnavailableError
from agent_runtime_service.config import ServiceAssertionSettings

_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret="test-shared-assertion-secret",
    issuer="web-console",
    audience="agent-runtime-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    investigator_audience="investigator-service",
)

_EXECUTE_RESPONSE = {"proposal_id": "11111111-1111-1111-1111-111111111111", "status": "succeeded"}


def _client(handler, **kwargs) -> ToolGatewayClient:
    return ToolGatewayClient(
        "http://tool-gateway",
        "test-execution-token",
        2.0,
        10.0,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_a_bound_actor_is_relayed_alongside_the_execution_token_never_a_replacement():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=_EXECUTE_RESPONSE)

    client = _client(handler, service_assertion_settings=_ASSERTION_SETTINGS)
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")

    with bind_actor(actor):
        await client.execute("11111111-1111-1111-1111-111111111111")

    # ADDITIVE: the execution token is STILL sent -- this is the ONE
    # thing that proves the call genuinely came from a holder of
    # TOOL_GATEWAY_EXECUTION_TOKEN at all.
    assert seen_headers.get("authorization") == "Bearer test-execution-token"
    assert "x-service-assertion" in seen_headers
    payload = jwt.decode(
        seen_headers["x-service-assertion"], _ASSERTION_SETTINGS.secret, algorithms=["HS256"], audience="control-plane"
    )
    assert payload["iss"] == "agent-runtime-service"
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "OWNER"


async def test_with_no_bound_actor_only_the_execution_token_is_sent():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=_EXECUTE_RESPONSE)

    client = _client(handler, service_assertion_settings=_ASSERTION_SETTINGS)
    await client.execute("11111111-1111-1111-1111-111111111111")

    assert seen_headers.get("authorization") == "Bearer test-execution-token"
    assert "x-service-assertion" not in seen_headers


async def test_execute_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/remediation-actions/execute"
        return httpx.Response(200, json=_EXECUTE_RESPONSE)

    result = await _client(handler).execute("11111111-1111-1111-1111-111111111111")
    assert result.status == "succeeded"


async def test_execute_unreachable_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ToolGatewayUnavailableError):
        await _client(handler).execute("11111111-1111-1111-1111-111111111111")
