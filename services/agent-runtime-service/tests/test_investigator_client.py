"""HTTP-contract-level tests for clients/investigator.py, using
httpx.MockTransport -- covers "investigator unavailable" and
"malformed investigator response"."""

import httpx
import jwt
import pytest

from agent_runtime_service.authz import ActorContext, bind_actor
from agent_runtime_service.clients.investigator import (
    InvestigatorClient,
    InvestigatorOutputError,
    InvestigatorUnavailableError,
)
from agent_runtime_service.config import ServiceAssertionSettings
from tests.conftest import SAMPLE_INCIDENT_ID, investigation_report_json

_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret="test-shared-assertion-secret",
    issuer="web-console",
    audience="agent-runtime-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    investigator_audience="investigator-service",
)


# ---------------------------------------------------------------------
# Phase 14 correction round, Blocker 1 / Task 2 audit: when a verified
# actor is bound for the current request, this client must relay a
# FRESH, further-derived X-Service-Assertion naming that EXACT actor,
# never the bare static caller token -- and must still fall back to
# that static token when no actor is bound (legacy/local-dev mode).
# ---------------------------------------------------------------------


async def test_a_bound_actor_is_relayed_as_a_derived_assertion_not_the_bare_token():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=investigation_report_json())

    client = InvestigatorClient(
        "http://investigator-service",
        2.0,
        10.0,
        transport=httpx.MockTransport(handler),
        internal_caller_token="bare-static-caller-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="ENGINEER")

    with bind_actor(actor):
        await client.investigate(SAMPLE_INCIDENT_ID)

    assert "x-service-assertion" in seen_headers
    # ADDITIVE, never a replacement -- the static caller token is still
    # sent alongside the derived assertion (investigator-service's own
    # require_internal_caller gate is unaffected either way).
    assert seen_headers.get("x-internal-service-token") == "bare-static-caller-token"
    payload = jwt.decode(
        seen_headers["x-service-assertion"],
        _ASSERTION_SETTINGS.secret,
        algorithms=["HS256"],
        audience="investigator-service",
    )
    assert payload["iss"] == "agent-runtime-service"
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "ENGINEER"


async def test_with_no_bound_actor_only_the_bare_caller_token_is_sent():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=investigation_report_json())

    client = InvestigatorClient(
        "http://investigator-service",
        2.0,
        10.0,
        transport=httpx.MockTransport(handler),
        internal_caller_token="bare-static-caller-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    await client.investigate(SAMPLE_INCIDENT_ID)

    assert seen_headers.get("x-internal-service-token") == "bare-static-caller-token"
    assert "x-service-assertion" not in seen_headers


async def test_investigate_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/investigations"
        return httpx.Response(200, json=investigation_report_json())

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    report = await client.investigate(SAMPLE_INCIDENT_ID)
    assert report.incident_id == SAMPLE_INCIDENT_ID
    assert len(report.observations) == 1


async def test_investigate_503_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "no LLM provider is configured"})

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorUnavailableError):
        await client.investigate(SAMPLE_INCIDENT_ID)


async def test_connection_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorUnavailableError):
        await client.investigate(SAMPLE_INCIDENT_ID)


async def test_malformed_response_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totally": "wrong shape"})

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorOutputError):
        await client.investigate(SAMPLE_INCIDENT_ID)


async def test_non_json_response_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorOutputError):
        await client.investigate(SAMPLE_INCIDENT_ID)


async def test_unavailable_error_never_forwards_raw_response_body():
    """Defense in depth: the raw body (which could, in principle,
    carry an upstream provider-shaped detail string) is never embedded
    in the raised exception's own message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "sk-should-never-leak-this-secret"})

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorUnavailableError) as exc_info:
        await client.investigate(SAMPLE_INCIDENT_ID)
    assert "sk-should-never-leak-this-secret" not in str(exc_info.value)


async def test_output_error_never_leaks_pydantic_validation_error_input_value():
    """Phase 7 correction round (finding #5): independent review
    reproduced 'sk-THIS-SHOULD-NOT-BE-PERSISTED' appearing directly in
    str(InvestigatorOutputError) because the old code concatenated
    pydantic's own ValidationError string, which includes each failing
    field's input_value verbatim. Proves the fix: a fake secret placed
    in a field that fails shape validation must never appear in the
    raised exception's own message, and the message must be the fixed,
    generic contract-violation string (never ad hoc per-field text)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = investigation_report_json()
        # incident_status_at_investigation fails its Literal validation
        # -- pydantic's ValidationError would normally quote this exact
        # value verbatim in its error string.
        body["incident_status_at_investigation"] = "sk-THIS-SHOULD-NOT-BE-PERSISTED"
        return httpx.Response(200, json=body)

    client = InvestigatorClient("http://investigator-service", 2.0, 10.0, transport=httpx.MockTransport(handler))
    with pytest.raises(InvestigatorOutputError) as exc_info:
        await client.investigate(SAMPLE_INCIDENT_ID)
    assert "sk-THIS-SHOULD-NOT-BE-PERSISTED" not in str(exc_info.value)
    assert str(exc_info.value) == "investigator-service response did not match the expected response contract"
