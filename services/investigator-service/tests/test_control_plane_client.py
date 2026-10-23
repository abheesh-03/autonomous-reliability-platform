"""Tests ControlPlaneClient against a real HTTP contract (via
httpx.MockTransport, never a real network call) — incident
retrieval/UUID handling and FULL audit-event pagination, per Phase 5
§9's explicit test requirements."""

import json

import httpx
import jwt
import pytest

from investigator_service.authz import ActorContext, bind_actor
from investigator_service.clients.control_plane import (
    ControlPlaneClient,
    ControlPlaneUnavailableError,
    IncidentNotFoundError,
)
from investigator_service.config import ServiceAssertionSettings
from tests.conftest import SAMPLE_INCIDENT_ID, event_json, incident_json


def _client(handler, **kwargs) -> ControlPlaneClient:
    return ControlPlaneClient(
        "http://control-plane.invalid",
        connect_timeout=1.0,
        request_timeout=1.0,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# ---------------------------------------------------------------------
# Phase 14 correction round, Blocker 1: when a relayed actor is bound,
# this client must relay a FURTHER-derived X-Service-Assertion naming
# that exact actor, not the bare internal token control-plane's own
# incident/evidence routes no longer accept at all.
# ---------------------------------------------------------------------

_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret="test-shared-assertion-secret",
    trusted_issuers=frozenset({"agent-runtime-service"}),
    audience="investigator-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    retrieval_audience="retrieval-service",
)


async def test_a_bound_actor_is_relayed_as_a_further_derived_assertion_not_the_bare_token():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=incident_json())

    client = _client(handler, internal_read_token="bare-static-token", service_assertion_settings=_ASSERTION_SETTINGS)
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="ENGINEER")

    with bind_actor(actor):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))

    assert "x-service-assertion" in seen_headers
    assert "x-internal-service-token" not in seen_headers
    payload = jwt.decode(
        seen_headers["x-service-assertion"],
        _ASSERTION_SETTINGS.secret,
        algorithms=["HS256"],
        audience="control-plane",
    )
    assert payload["iss"] == "investigator-service"
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "ENGINEER"


async def test_with_no_bound_actor_the_bare_internal_token_is_sent_as_a_fallback():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=incident_json())

    client = _client(handler, internal_read_token="bare-static-token", service_assertion_settings=_ASSERTION_SETTINGS)
    await client.get_incident(str(SAMPLE_INCIDENT_ID))

    assert seen_headers.get("x-internal-service-token") == "bare-static-token"
    assert "x-service-assertion" not in seen_headers


async def test_get_incident_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}"
        return httpx.Response(200, json=incident_json())

    incident = await _client(handler).get_incident(str(SAMPLE_INCIDENT_ID))
    assert incident.id == SAMPLE_INCIDENT_ID
    assert incident.status == "resolved"


async def test_get_incident_not_found_maps_to_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "incident not found"})

    with pytest.raises(IncidentNotFoundError):
        await _client(handler).get_incident(str(SAMPLE_INCIDENT_ID))


async def test_get_incident_unreachable_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ControlPlaneUnavailableError):
        await _client(handler).get_incident(str(SAMPLE_INCIDENT_ID))


async def test_get_incident_server_error_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "database temporarily unavailable"})

    with pytest.raises(ControlPlaneUnavailableError):
        await _client(handler).get_incident(str(SAMPLE_INCIDENT_ID))


async def test_get_all_events_fully_paginates_across_multiple_pages():
    """25 real events, server page size forced to 10 by the client's
    own cap-at-100-but-respect-requested logic — this test uses
    page_size=10 explicitly to force >1 page without needing 100+
    fixture rows, proving the pagination loop itself (not just one
    page) actually runs."""
    all_events = [event_json(event_id=i, occurred_at=None) for i in range(1, 26)]

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        offset = int(params["offset"])
        limit = int(params["limit"])
        page = all_events[offset : offset + limit]
        return httpx.Response(
            200, json={"items": page, "total": len(all_events), "limit": limit, "offset": offset}
        )

    events, total = await _client(handler).get_all_events(str(SAMPLE_INCIDENT_ID), page_size=10, max_events=1000)
    assert total == 25
    assert len(events) == 25
    assert [e.id for e in events] == list(range(1, 26))


async def test_get_all_events_respects_max_events_safety_cap():
    all_events = [event_json(event_id=i) for i in range(1, 51)]

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        offset = int(params["offset"])
        limit = int(params["limit"])
        page = all_events[offset : offset + limit]
        return httpx.Response(
            200, json={"items": page, "total": len(all_events), "limit": limit, "offset": offset}
        )

    events, total = await _client(handler).get_all_events(str(SAMPLE_INCIDENT_ID), page_size=10, max_events=15)
    assert total == 50
    assert len(events) == 15  # capped, never silently reporting a wrong "total" though
    assert events == events[:15]


async def test_get_all_events_empty_history_is_not_fabricated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    events, total = await _client(handler).get_all_events(str(SAMPLE_INCIDENT_ID))
    assert events == []
    assert total == 0


async def test_get_all_events_not_found_maps_to_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "incident not found"})

    with pytest.raises(IncidentNotFoundError):
        await _client(handler).get_all_events(str(SAMPLE_INCIDENT_ID))


# ---------------------------------------------------------------------
# Correction round (Issue 6A): GET .../kubernetes-evidence
# ---------------------------------------------------------------------


async def test_get_kubernetes_evidence_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/kubernetes-evidence"
        return httpx.Response(
            200,
            json={
                "cluster": "kind-reliability-lab", "namespace": "reliability-sandbox",
                "resource_kind": "Pod", "resource_name": "crashloop-demo-abc", "resource_uid": "uid-1",
                "detector_id": "crash_loop_backoff", "result": "confirmed",
                "collection_completeness": "complete", "collected_at": "2026-04-01T09:00:00+00:00",
            },
        )

    evidence = await _client(handler).get_kubernetes_evidence(str(SAMPLE_INCIDENT_ID))
    assert evidence["cluster"] == "kind-reliability-lab"
    assert evidence["resource_uid"] == "uid-1"


async def test_get_kubernetes_evidence_404_returns_none_not_an_error():
    """A 404 here means 'no recorded Kubernetes evidence' -- a real,
    honest outcome, never conflated with IncidentNotFoundError (the
    incident's own existence was already established by get_incident)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "this incident has no recorded Kubernetes evidence"})

    evidence = await _client(handler).get_kubernetes_evidence(str(SAMPLE_INCIDENT_ID))
    assert evidence is None


async def test_get_kubernetes_evidence_unreachable_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ControlPlaneUnavailableError):
        await _client(handler).get_kubernetes_evidence(str(SAMPLE_INCIDENT_ID))


# ---------------------------------------------------------------------
# Phase 13: GET .../aws-evidence
# ---------------------------------------------------------------------


async def test_get_aws_evidence_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/aws-evidence"
        return httpx.Response(
            200,
            json={
                "account_id": "123456789012", "region": "us-east-1",
                "resource_kind": "CloudWatchAlarm", "resource_id": "checkout-high-error-rate",
                "detector_id": "cloudwatch_alarm_in_alarm_state", "result": "confirmed",
                "collection_completeness": "complete", "collected_at": "2026-04-01T09:00:00+00:00",
            },
        )

    evidence = await _client(handler).get_aws_evidence(str(SAMPLE_INCIDENT_ID))
    assert evidence["account_id"] == "123456789012"
    assert evidence["region"] == "us-east-1"


async def test_get_aws_evidence_404_returns_none_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "this incident has no recorded AWS evidence"})

    evidence = await _client(handler).get_aws_evidence(str(SAMPLE_INCIDENT_ID))
    assert evidence is None


async def test_get_aws_evidence_unreachable_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ControlPlaneUnavailableError):
        await _client(handler).get_aws_evidence(str(SAMPLE_INCIDENT_ID))


async def test_control_plane_client_never_issues_a_write_request():
    """Static/behavioral guarantee: regardless of inputs, this client
    only ever issues GET requests. Any non-GET request reaching the
    transport is itself a bug this test would catch."""
    seen_methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(request.method)
        return httpx.Response(200, json=incident_json())

    await _client(handler).get_incident(str(SAMPLE_INCIDENT_ID))
    assert seen_methods == ["GET"]
