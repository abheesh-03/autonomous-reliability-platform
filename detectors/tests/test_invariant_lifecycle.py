"""Gate H (INVARIANTS): exercises the real incident-lifecycle
invariant checker against synthetic control-plane responses."""

from datetime import UTC, datetime, timedelta

import httpx

from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.invariants.lifecycle_checker import check_incident_lifecycle_consistency
from detectors.schemas.invariant import InvariantCheckResult

WINDOW_START = datetime(2026, 6, 1, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)


def _event(id_, incident_id, event_type, actor_type, previous_status, new_status, occurred_at):
    return {
        "id": id_,
        "incident_id": incident_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "occurred_at": occurred_at,
        "metadata": {},
    }


def _events_client(events_by_incident: dict[str, list[dict]], *, unreachable: bool = False) -> ControlPlaneClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if unreachable:
            raise httpx.ConnectError("refused", request=request)
        path_parts = request.url.path.strip("/").split("/")
        incident_id = path_parts[3]  # api/v1/incidents/{id}/events
        params = dict(httpx.QueryParams(request.url.query.decode()))
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 100))
        all_events = events_by_incident.get(incident_id, [])
        page = all_events[offset : offset + limit]
        return httpx.Response(200, json={"items": page, "total": len(all_events), "limit": limit, "offset": offset})

    return ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))


def _mixed_completeness_client(
    events_by_incident: dict[str, list[dict]], incomplete_incident_ids: set[str]
) -> ControlPlaneClient:
    """Serves a COMPLETE page for every incident id except those in
    `incomplete_incident_ids`, which always report a `total` larger
    than what is ever actually returned -- simulating a source that
    never lets that one incident's pagination reach the end, while
    other incidents in the same request set are genuinely complete."""

    def handler(request: httpx.Request) -> httpx.Response:
        path_parts = request.url.path.strip("/").split("/")
        incident_id = path_parts[3]
        params = dict(httpx.QueryParams(request.url.query.decode()))
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 100))
        all_events = events_by_incident.get(incident_id, [])
        if incident_id in incomplete_incident_ids:
            page = all_events[:1]  # always truncated, regardless of offset
            return httpx.Response(200, json={"items": page, "total": len(all_events) + 50, "limit": limit, "offset": 0})
        page = all_events[offset : offset + limit]
        return httpx.Response(200, json={"items": page, "total": len(all_events), "limit": limit, "offset": offset})

    return ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))


async def test_satisfied_clean_lifecycle():
    events = {
        "inc-1": [
            _event(1, "inc-1", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-1", "observed", "alertmanager", "open", "open", "2026-06-01T00:01:00Z"),
            _event(3, "inc-1", "status_transition", "operator", "open", "acknowledged", "2026-06-01T00:02:00Z"),
            _event(4, "inc-1", "status_transition", "operator", "acknowledged", "resolved", "2026-06-01T00:03:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-1"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED
    assert report.subjects_checked == 1
    assert report.violations == []


async def test_real_illegal_transition_is_violated():
    events = {
        "inc-2": [
            _event(1, "inc-2", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            # closed has NO legal outgoing transitions -- this is illegal
            _event(2, "inc-2", "status_transition", "operator", "open", "resolved", "2026-06-01T00:01:00Z"),
            _event(3, "inc-2", "status_transition", "operator", "resolved", "closed", "2026-06-01T00:02:00Z"),
            _event(4, "inc-2", "status_transition", "operator", "closed", "open", "2026-06-01T00:03:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-2"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.VIOLATED
    assert any("illegal transition" in v.explanation for v in report.violations)


async def test_absent_source_is_source_unavailable():
    client = _events_client({}, unreachable=True)
    report = await check_incident_lifecycle_consistency(client, ["inc-3"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SOURCE_UNAVAILABLE


async def test_partial_history_never_falsely_satisfied():
    """total=50 but the client's own max_events bound is honored by
    the mock returning fewer than total -- must be INSUFFICIENT_EVIDENCE,
    never SATISFIED on a truncated view."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Always reports total=50 but only ever returns 2 items,
        # regardless of offset -- simulates a source that never lets
        # pagination actually reach the end.
        return httpx.Response(200, json={"items": [_event(1, "inc-4", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z")], "total": 50, "limit": 100, "offset": 0})

    client = ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))
    report = await check_incident_lifecycle_consistency(client, ["inc-4"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.INSUFFICIENT_EVIDENCE
    assert report.subjects_checked == 0


async def test_no_incidents_to_check_is_insufficient_evidence_never_satisfied():
    client = _events_client({})
    report = await check_incident_lifecycle_consistency(client, [], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.INSUFFICIENT_EVIDENCE


async def test_unexpected_status_value_is_violated():
    events = {
        "inc-5": [
            _event(1, "inc-5", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-5", "status_transition", "operator", "open", "totally-invented-status", "2026-06-01T00:01:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-5"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.VIOLATED
    assert any("outside the known vocabulary" in v.explanation for v in report.violations)


async def test_out_of_order_api_response_is_still_correctly_resorted():
    """The mock deliberately returns events in REVERSE id order --
    the checker must re-sort by (occurred_at, id) itself, never trust
    the raw response order."""
    events = {
        "inc-6": [
            _event(2, "inc-6", "status_transition", "operator", "open", "acknowledged", "2026-06-01T00:01:00Z"),
            _event(1, "inc-6", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-6"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED


async def test_concurrent_equal_timestamps_use_id_as_legitimate_tiebreak():
    """Two events share the EXACT same occurred_at -- a documented,
    legitimate possibility -- and must be ordered by id, never
    flagged as an ordering problem."""
    events = {
        "inc-7": [
            _event(1, "inc-7", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-7", "status_transition", "operator", "open", "investigating", "2026-06-01T00:00:00Z"),
            _event(3, "inc-7", "status_transition", "operator", "investigating", "resolved", "2026-06-01T00:00:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-7"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED


async def test_alertmanager_auto_resolution_from_any_active_status_is_legal():
    """Auto-resolution (remediating -> resolved, actor 'alertmanager')
    must never be falsely flagged -- it is a real, legal transition."""
    events = {
        "inc-8": [
            _event(1, "inc-8", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-8", "status_transition", "operator", "open", "investigating", "2026-06-01T00:01:00Z"),
            _event(3, "inc-8", "status_transition", "operator", "investigating", "remediating", "2026-06-01T00:02:00Z"),
            _event(4, "inc-8", "status_transition", "alertmanager", "remediating", "resolved", "2026-06-01T00:03:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-8"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED


async def test_eventless_incident_is_not_a_violation():
    client = _events_client({"inc-9": []})
    report = await check_incident_lifecycle_consistency(client, ["inc-9"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED
    assert report.violations == []


async def test_missing_intermediate_transition_is_violated():
    """Correction-round Issue 2 exact reproduction: 'created: None ->
    open' followed directly by 'status_transition: investigating ->
    resolved' -- individually legal per the matrix, but there is no
    recorded transition INTO 'investigating' at all. Must be VIOLATED,
    never SATISFIED."""
    events = {
        "inc-11": [
            _event(1, "inc-11", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-11", "status_transition", "operator", "investigating", "resolved", "2026-06-01T00:01:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-11"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.VIOLATED
    assert any("discontinuous history" in v.explanation for v in report.violations)


async def test_discontinuous_observed_event_is_violated():
    """An 'observed' event whose own previous_status does not match
    what the preceding history established must also be VIOLATED --
    continuity applies to 'observed' events too, not only
    'status_transition'."""
    events = {
        "inc-12": [
            _event(1, "inc-12", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-12", "status_transition", "operator", "open", "acknowledged", "2026-06-01T00:01:00Z"),
            # claims the incident was 'open' again at re-observation time, but it is actually 'acknowledged'
            _event(3, "inc-12", "observed", "alertmanager", "open", "open", "2026-06-01T00:02:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-12"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.VIOLATED
    assert any("discontinuous history" in v.explanation for v in report.violations)


async def test_correct_multi_step_history_is_satisfied():
    """A genuinely continuous, correct multi-step history (every
    transition's previous_status matches the running state) must
    remain SATISFIED."""
    events = {
        "inc-13": [
            _event(1, "inc-13", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-13", "status_transition", "operator", "open", "acknowledged", "2026-06-01T00:01:00Z"),
            _event(3, "inc-13", "observed", "alertmanager", "acknowledged", "acknowledged", "2026-06-01T00:02:00Z"),
            _event(4, "inc-13", "status_transition", "operator", "acknowledged", "investigating", "2026-06-01T00:03:00Z"),
            _event(5, "inc-13", "status_transition", "operator", "investigating", "remediating", "2026-06-01T00:04:00Z"),
            _event(6, "inc-13", "status_transition", "alertmanager", "remediating", "resolved", "2026-06-01T00:05:00Z"),
            _event(7, "inc-13", "status_transition", "operator", "resolved", "closed", "2026-06-01T00:06:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-13"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED
    assert report.violations == []


async def test_continuity_holds_across_equal_timestamps_ordered_by_id():
    """Equal-timestamp events must still be replayed in id order for
    continuity tracking -- not merely for the first-event check."""
    events = {
        "inc-14": [
            _event(1, "inc-14", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-14", "status_transition", "operator", "open", "investigating", "2026-06-01T00:00:00Z"),
            _event(3, "inc-14", "status_transition", "operator", "investigating", "resolved", "2026-06-01T00:00:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-14"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED


async def test_partial_history_with_discontinuity_stays_insufficient_evidence_not_violated_or_satisfied():
    """An incomplete (truncated) event history must never be judged
    at all -- not SATISFIED, and not VIOLATED either, since a genuine
    discontinuity cannot be distinguished from simply-missing pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [_event(2, "inc-15", "status_transition", "operator", "investigating", "resolved", "2026-06-01T00:01:00Z")],
                "total": 50,
                "limit": 100,
                "offset": 0,
            },
        )

    client = ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))
    report = await check_incident_lifecycle_consistency(client, ["inc-15"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.INSUFFICIENT_EVIDENCE
    assert report.subjects_checked == 0


async def test_valid_auto_resolution_preserves_continuity():
    """Alertmanager auto-resolution (status_transition, actor
    'alertmanager') must correctly advance the tracked state and never
    be falsely flagged as discontinuous when it legitimately follows
    the established history."""
    events = {
        "inc-16": [
            _event(1, "inc-16", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-16", "status_transition", "operator", "open", "investigating", "2026-06-01T00:01:00Z"),
            _event(3, "inc-16", "status_transition", "operator", "investigating", "remediating", "2026-06-01T00:02:00Z"),
            _event(4, "inc-16", "status_transition", "alertmanager", "remediating", "resolved", "2026-06-01T00:03:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-16"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED


async def test_observed_event_that_changes_status_is_violated():
    events = {
        "inc-10": [
            _event(1, "inc-10", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-10", "observed", "alertmanager", "open", "acknowledged", "2026-06-01T00:01:00Z"),
        ]
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-10"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.VIOLATED
    assert any("must never change status" in v.explanation for v in report.violations)


# ---------------------------------------------------------------------
# Final evidence-integrity correction round, Issue B: SATISFIED must
# only ever be returned when EVERY requested incident's history was
# completely retrieved -- a complete+clean incident sitting alongside
# an incomplete one must never make the overall result SATISFIED.
# ---------------------------------------------------------------------


async def test_one_valid_complete_plus_one_incomplete_is_insufficient_evidence():
    events = {
        "inc-complete": [
            _event(1, "inc-complete", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-complete", "status_transition", "operator", "open", "resolved", "2026-06-01T00:01:00Z"),
        ],
        "inc-incomplete": [
            _event(1, "inc-incomplete", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
        ],
    }
    client = _mixed_completeness_client(events, incomplete_incident_ids={"inc-incomplete"})
    report = await check_incident_lifecycle_consistency(
        client, ["inc-complete", "inc-incomplete"], WINDOW_START, WINDOW_END
    )
    assert report.result == InvariantCheckResult.INSUFFICIENT_EVIDENCE
    assert report.subjects_checked == 1
    assert report.violations == []
    assert "1 incident(s) had incomplete" in report.explanation


async def test_one_violated_complete_plus_one_incomplete_is_violated_with_documented_gap():
    events = {
        "inc-violated": [
            _event(1, "inc-violated", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            # closed has no legal outgoing transitions -- illegal
            _event(2, "inc-violated", "status_transition", "operator", "open", "resolved", "2026-06-01T00:01:00Z"),
            _event(3, "inc-violated", "status_transition", "operator", "resolved", "closed", "2026-06-01T00:02:00Z"),
            _event(4, "inc-violated", "status_transition", "operator", "closed", "open", "2026-06-01T00:03:00Z"),
        ],
        "inc-incomplete": [
            _event(1, "inc-incomplete", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
        ],
    }
    client = _mixed_completeness_client(events, incomplete_incident_ids={"inc-incomplete"})
    report = await check_incident_lifecycle_consistency(
        client, ["inc-violated", "inc-incomplete"], WINDOW_START, WINDOW_END
    )
    assert report.result == InvariantCheckResult.VIOLATED
    assert report.subjects_checked == 1
    assert len(report.violations) >= 1
    assert "1 incident(s) had incomplete" in report.explanation


async def test_all_complete_and_valid_is_satisfied():
    events = {
        "inc-a": [
            _event(1, "inc-a", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
            _event(2, "inc-a", "status_transition", "operator", "open", "resolved", "2026-06-01T00:01:00Z"),
        ],
        "inc-b": [
            _event(1, "inc-b", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z"),
        ],
    }
    client = _events_client(events)
    report = await check_incident_lifecycle_consistency(client, ["inc-a", "inc-b"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.SATISFIED
    assert report.subjects_checked == 2
    assert report.violations == []


async def test_all_incomplete_is_insufficient_evidence():
    events = {
        "inc-x": [_event(1, "inc-x", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z")],
        "inc-y": [_event(1, "inc-y", "created", "alertmanager", None, "open", "2026-06-01T00:00:00Z")],
    }
    client = _mixed_completeness_client(events, incomplete_incident_ids={"inc-x", "inc-y"})
    report = await check_incident_lifecycle_consistency(client, ["inc-x", "inc-y"], WINDOW_START, WINDOW_END)
    assert report.result == InvariantCheckResult.INSUFFICIENT_EVIDENCE
    assert report.subjects_checked == 0
    assert report.violations == []
