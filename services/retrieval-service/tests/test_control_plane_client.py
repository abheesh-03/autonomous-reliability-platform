"""HTTP-contract-level tests for clients/control_plane.py, using
httpx.MockTransport (never a real network call) -- same convention
investigator_service's own test suite already establishes. Covers
Phase 6 §7's "fully paginate list/event APIs" and "an incident with no
audit events remains a valid historical record"."""

import json

import httpx

from retrieval_service.clients.control_plane import ControlPlaneClient
from tests.conftest import SAMPLE_INCIDENT_ID


def _incident_json(incident_id=SAMPLE_INCIDENT_ID) -> dict:
    return {
        "id": str(incident_id),
        "source": "alertmanager",
        "source_fingerprint": "fp",
        "title": "t",
        "description": None,
        "severity": "critical",
        "status": "resolved",
        "first_seen_at": "2026-04-01T09:00:00+00:00",
        "last_seen_at": "2026-04-01T09:05:00+00:00",
        "resolved_at": "2026-04-01T09:10:00+00:00",
        "created_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:10:00+00:00",
    }


async def test_list_all_incidents_fully_paginates():
    all_incidents = [_incident_json(incident_id=f"{i:08x}-0000-0000-0000-000000000000") for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(httpx.QueryParams(request.url.query)["offset"])
        limit = int(httpx.QueryParams(request.url.query)["limit"])
        page = all_incidents[offset : offset + limit]
        return httpx.Response(200, json={"items": page, "total": len(all_incidents), "limit": limit, "offset": offset})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    incidents = await client.list_all_incidents(page_size=2, max_incidents=100)
    assert len(incidents) == 5


async def test_list_all_incidents_respects_max_incidents_budget():
    all_incidents = [_incident_json(incident_id=f"{i:08x}-0000-0000-0000-000000000000") for i in range(10)]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(httpx.QueryParams(request.url.query)["offset"])
        limit = int(httpx.QueryParams(request.url.query)["limit"])
        page = all_incidents[offset : offset + limit]
        return httpx.Response(200, json={"items": page, "total": len(all_incidents), "limit": limit, "offset": offset})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    incidents = await client.list_all_incidents(page_size=3, max_incidents=4)
    assert len(incidents) == 4


async def test_get_all_events_empty_history_is_honest():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    events, total = await client.get_all_events(str(SAMPLE_INCIDENT_ID), max_events=200)
    assert events == []
    assert total == 0


async def test_get_all_events_fully_paginates():
    all_events = [
        {
            "id": i,
            "incident_id": str(SAMPLE_INCIDENT_ID),
            "event_type": "created" if i == 1 else "observed",
            "actor_type": "alertmanager",
            "previous_status": None if i == 1 else "open",
            "new_status": "open",
            "occurred_at": "2026-04-01T09:00:00+00:00",
            "metadata": {},
        }
        for i in range(1, 8)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(httpx.QueryParams(request.url.query)["offset"])
        limit = int(httpx.QueryParams(request.url.query)["limit"])
        page = all_events[offset : offset + limit]
        return httpx.Response(200, json={"items": page, "total": len(all_events), "limit": limit, "offset": offset})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    events, total = await client.get_all_events(str(SAMPLE_INCIDENT_ID), page_size=2, max_events=200)
    assert total == 7
    assert len(events) == 7
    assert [e.id for e in events] == list(range(1, 8))
