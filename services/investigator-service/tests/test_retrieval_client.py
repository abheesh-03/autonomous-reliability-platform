"""HTTP-contract-level tests for clients/retrieval.py, using
httpx.MockTransport (never a real network call).

Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A: when a
verified actor is bound for the current request, this client must
relay a derived X-Service-Assertion naming that EXACT actor, ADDITIVE
to (never a replacement for) the existing static
RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR -- retrieval-service's own
tenant-scope decision now requires the assertion to authorize a
historical-incident search at all (see
retrieval_service.search::_resolve_historical_organization_scope's own
docstring)."""

import httpx
import jwt
import pytest

from investigator_service.authz import ActorContext, bind_actor
from investigator_service.clients.retrieval import RetrievalClient, RetrievalUnavailableError
from investigator_service.config import ServiceAssertionSettings

_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret="test-shared-assertion-secret",
    trusted_issuers=frozenset({"agent-runtime-service"}),
    audience="investigator-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    retrieval_audience="retrieval-service",
)

_RESPONSE_BODY = {"knowledge": [], "historical_incidents": [], "embedding_space": "test-space"}


def _client(handler, **kwargs) -> RetrievalClient:
    return RetrievalClient(
        "http://retrieval-service.invalid",
        connect_timeout=1.0,
        request_timeout=1.0,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_a_bound_actor_is_relayed_alongside_the_static_token_never_a_replacement():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=_RESPONSE_BODY)

    client = _client(
        handler, internal_read_token="bare-static-read-token", service_assertion_settings=_ASSERTION_SETTINGS
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="ENGINEER")

    with bind_actor(actor):
        await client.search("test query", knowledge_limit=3, historical_incident_limit=3)

    # ADDITIVE: the static token is STILL sent -- require_internal_caller's
    # own gate is unaffected by whether an actor happens to be bound.
    assert seen_headers.get("x-internal-service-token") == "bare-static-read-token"
    assert "x-service-assertion" in seen_headers
    payload = jwt.decode(
        seen_headers["x-service-assertion"],
        _ASSERTION_SETTINGS.secret,
        algorithms=["HS256"],
        audience="retrieval-service",
    )
    assert payload["iss"] == "investigator-service"
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "ENGINEER"


async def test_with_no_bound_actor_only_the_static_token_is_sent():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=_RESPONSE_BODY)

    client = _client(
        handler, internal_read_token="bare-static-read-token", service_assertion_settings=_ASSERTION_SETTINGS
    )
    await client.search("test query", knowledge_limit=3, historical_incident_limit=3)

    assert seen_headers.get("x-internal-service-token") == "bare-static-read-token"
    assert "x-service-assertion" not in seen_headers


async def test_search_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/retrieval/search"
        return httpx.Response(200, json=_RESPONSE_BODY)

    result = await _client(handler).search("test query", knowledge_limit=3, historical_incident_limit=3)
    assert result == _RESPONSE_BODY


async def test_search_non_200_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    with pytest.raises(RetrievalUnavailableError):
        await _client(handler).search("test query", knowledge_limit=3, historical_incident_limit=3)
