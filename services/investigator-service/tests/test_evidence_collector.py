"""EvidenceCollector tests using fake client doubles (same seam
philosophy as control-plane's FakeIncidentRepository) — never a real
network call. Covers Phase 5 §9's "source failures and partial
evidence" and "evidence package generation" requirements, and §4's
"distinguish 'no matching evidence' from 'source failed'"."""

from datetime import UTC, datetime

import pytest

from investigator_service.clients.control_plane import ControlPlaneUnavailableError, IncidentNotFoundError
from investigator_service.clients.loki import LogLine, LokiUnavailableError
from investigator_service.clients.prometheus import MetricSeriesSummary, PrometheusUnavailableError
from investigator_service.clients.tempo import TempoUnavailableError, TraceDetail, TraceSummary
from investigator_service.config import EvidenceBounds
from investigator_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot
from investigator_service.evidence_collector import EvidenceCollector
from tests.conftest import SAMPLE_INCIDENT_ID, TEST_BOUNDS

BOUNDS = TEST_BOUNDS


def _incident(**overrides) -> IncidentSnapshot:
    defaults = dict(
        id=SAMPLE_INCIDENT_ID,
        source="alertmanager",
        source_fingerprint="deadbeef12345678",
        title="checkout-service is returning HTTP 5xx errors",
        description="desc",
        severity="critical",
        status="resolved",
        first_seen_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 4, 1, 9, 5, 0, tzinfo=UTC),
        resolved_at=datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC),
        created_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return IncidentSnapshot.model_validate(defaults)


def _event(event_id: int) -> IncidentEventSnapshot:
    return IncidentEventSnapshot(
        id=event_id,
        incident_id=SAMPLE_INCIDENT_ID,
        event_type="created",
        actor_type="alertmanager",
        previous_status=None,
        new_status="open",
        occurred_at=datetime(2026, 4, 1, 9, 0, 1, tzinfo=UTC),
        metadata={"source_fingerprint": "deadbeef12345678"},
    )


class FakeControlPlane:
    def __init__(self, incident=None, events=None, events_total=None, raise_=None):
        self._incident = incident
        self._events = events or []
        self._events_total = events_total if events_total is not None else len(self._events)
        self._raise = raise_

    async def get_incident(self, incident_id):
        if self._raise:
            raise self._raise
        return self._incident

    async def get_all_events(self, incident_id, **kwargs):
        return self._events, self._events_total


class FakePrometheus:
    def __init__(self, summaries=None, raise_=None):
        self._summaries = summaries
        self._raise = raise_

    async def query_window(self, *_args, **_kwargs):
        if self._raise:
            raise self._raise
        return self._summaries or []


class FakeLoki:
    def __init__(self, lines=None, raise_=None):
        self._lines = lines
        self._raise = raise_

    async def query_window(self, *_args, **_kwargs):
        if self._raise:
            raise self._raise
        return self._lines or []


class FakeTempo:
    def __init__(self, traces=None, raise_=None, details=None):
        self._traces = traces
        self._raise = raise_
        self._details = details or {}

    async def search_window(self, *_args, **_kwargs):
        if self._raise:
            raise self._raise
        return self._traces or []

    async def get_trace_detail(self, trace_id: str):
        return self._details.get(trace_id)


def _collector(cp=None, prom=None, loki=None, tempo=None) -> EvidenceCollector:
    return EvidenceCollector(
        cp or FakeControlPlane(incident=_incident()),
        prom or FakePrometheus(),
        loki or FakeLoki(),
        tempo or FakeTempo(),
        BOUNDS,
    )


async def test_incident_retrieval_is_mandatory_and_propagates_not_found():
    collector = _collector(cp=FakeControlPlane(raise_=IncidentNotFoundError("x")))
    with pytest.raises(IncidentNotFoundError):
        await collector.collect(str(SAMPLE_INCIDENT_ID))


async def test_incident_retrieval_failure_propagates_unavailable():
    collector = _collector(cp=FakeControlPlane(raise_=ControlPlaneUnavailableError("down")))
    with pytest.raises(ControlPlaneUnavailableError):
        await collector.collect(str(SAMPLE_INCIDENT_ID))


async def test_evidence_items_get_stable_deterministic_ids():
    collector = _collector(
        cp=FakeControlPlane(incident=_incident(), events=[_event(1), _event(2)], events_total=2)
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    ids = [item.id for item in package.items]
    assert ids == [f"E{i}" for i in range(1, len(ids) + 1)]
    assert len(set(ids)) == len(ids)  # all unique


async def test_empty_audit_history_is_valid_not_fabricated():
    collector = _collector(cp=FakeControlPlane(incident=_incident(), events=[], events_total=0))
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    assert package.events == []
    assert package.events_total == 0
    cp_outcome = next(o for o in package.source_outcomes if o.source == "control_plane")
    assert cp_outcome.status == "ok"
    assert "no audit events" in cp_outcome.detail


async def test_source_failure_produces_partial_evidence_not_fabricated_data():
    collector = _collector(
        prom=FakePrometheus(raise_=PrometheusUnavailableError("timeout")),
        loki=FakeLoki(raise_=LokiUnavailableError("refused")),
        tempo=FakeTempo(raise_=TempoUnavailableError("refused")),
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    by_source = {o.source: o for o in package.source_outcomes}
    assert by_source["prometheus"].status == "unavailable"
    assert by_source["loki"].status == "unavailable"
    assert by_source["tempo"].status == "unavailable"
    # No prometheus/loki/tempo evidence items were fabricated despite
    # the failures.
    assert all(item.source == "control_plane" for item in package.items)


async def test_no_matching_evidence_is_distinguished_from_source_failure():
    collector = _collector(
        prom=FakePrometheus(
            summaries=[
                MetricSeriesSummary(
                    key="checkout_5xx_rate",
                    description="d",
                    promql="q",
                    sample_count=10,
                    nonzero_or_below_one_count=0,
                    max_value=0.0,
                    max_value_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC),
                    last_value=0.0,
                )
            ]
        ),
        loki=FakeLoki(lines=[]),
        tempo=FakeTempo(traces=[]),
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    by_source = {o.source: o for o in package.source_outcomes}
    assert by_source["prometheus"].status == "no_data"
    assert by_source["loki"].status == "no_data"
    assert by_source["tempo"].status == "no_data"


async def test_real_signal_marks_prometheus_ok():
    collector = _collector(
        prom=FakePrometheus(
            summaries=[
                MetricSeriesSummary(
                    key="checkout_5xx_rate",
                    description="d",
                    promql="q",
                    sample_count=10,
                    nonzero_or_below_one_count=3,
                    max_value=2.5,
                    max_value_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC),
                    last_value=0.0,
                )
            ]
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    by_source = {o.source: o for o in package.source_outcomes}
    assert by_source["prometheus"].status == "ok"


async def test_loki_lines_become_evidence_items_with_real_content():
    collector = _collector(
        loki=FakeLoki(
            lines=[LogLine(service="payment-service", timestamp=datetime(2026, 4, 1, 9, 1, 0, tzinfo=UTC), message="real log line")]
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    loki_items = [i for i in package.items if i.source == "loki"]
    assert len(loki_items) == 1
    assert loki_items[0].detail == "real log line"


async def test_tempo_traces_never_claim_confirmed_correlation():
    collector = _collector(
        tempo=FakeTempo(
            traces=[
                TraceSummary(
                    trace_id="abcd1234" * 4,
                    root_service_name="checkout-service",
                    root_trace_name="POST /checkouts",
                    start_time=datetime(2026, 4, 1, 9, 1, 0, tzinfo=UTC),
                    duration_ms=42,
                )
            ]
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    tempo_items = [i for i in package.items if i.source == "tempo"]
    assert len(tempo_items) == 1
    assert "NOT a confirmed causal link" in tempo_items[0].detail


async def test_total_events_vs_retrieved_events_both_reported():
    collector = _collector(
        cp=FakeControlPlane(incident=_incident(), events=[_event(1)], events_total=5)
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    assert package.events_total == 5
    assert len(package.events) == 1


async def test_truncated_audit_history_is_reported_as_partial_not_ok():
    """Phase 5 correction round #2A: a truncated mandatory retrieval
    must never be described as complete."""
    collector = _collector(
        cp=FakeControlPlane(incident=_incident(), events=[_event(1), _event(2)], events_total=50)
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    cp_outcome = next(o for o in package.source_outcomes if o.source == "control_plane")
    assert cp_outcome.status == "partial"
    assert "50" in cp_outcome.detail
    assert "2" in cp_outcome.detail
    assert "NOT the complete" in cp_outcome.detail


async def test_complete_audit_history_is_reported_as_ok_not_partial():
    collector = _collector(
        cp=FakeControlPlane(incident=_incident(), events=[_event(1), _event(2)], events_total=2)
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    cp_outcome = next(o for o in package.source_outcomes if o.source == "control_plane")
    assert cp_outcome.status == "ok"


async def test_incident_description_is_redacted_and_length_bounded():
    """Phase 5 correction round #2C/#7: incident title/description are
    unbounded, untrusted TEXT columns -- bounded and redacted before
    becoming evidence."""
    collector = _collector(
        cp=FakeControlPlane(
            incident=_incident(description="Authorization: Bearer sk-realsecrettoken1234567890"),
            events=[],
            events_total=0,
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    core_item = package.items[0]
    assert "sk-realsecrettoken1234567890" not in core_item.detail
    assert "REDACTED" in core_item.detail


async def test_incident_description_is_length_bounded():
    import dataclasses

    narrow_bounds = dataclasses.replace(BOUNDS, max_incident_text_length=50)
    collector = EvidenceCollector(
        FakeControlPlane(incident=_incident(description="X" * 10_000), events=[], events_total=0),
        FakePrometheus(),
        FakeLoki(),
        FakeTempo(),
        narrow_bounds,
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    core_item = package.items[0]
    assert "X" * 10_000 not in core_item.detail
    assert len(core_item.detail) < 10_000


async def test_loki_log_line_is_redacted():
    collector = _collector(
        loki=FakeLoki(
            lines=[
                LogLine(
                    service="payment-service",
                    timestamp=datetime(2026, 4, 1, 9, 1, 0, tzinfo=UTC),
                    message="api_key=sk-realsecrettoken1234567890 request failed",
                )
            ]
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    loki_item = next(i for i in package.items if i.source == "loki")
    assert "sk-realsecrettoken1234567890" not in loki_item.detail
    assert "REDACTED" in loki_item.detail


async def test_tempo_detail_enriches_candidate_trace_when_available():
    trace_id = "abcd1234" * 4
    collector = _collector(
        tempo=FakeTempo(
            traces=[
                TraceSummary(
                    trace_id=trace_id,
                    root_service_name="checkout-service",
                    root_trace_name="POST /checkouts",
                    start_time=datetime(2026, 4, 1, 9, 1, 0, tzinfo=UTC),
                    duration_ms=42,
                )
            ],
            details={
                trace_id: TraceDetail(
                    trace_id=trace_id,
                    span_count=7,
                    service_names=("checkout-service", "payment-service"),
                    root_span_services=("checkout-service",),
                )
            },
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    tempo_item = next(i for i in package.items if i.source == "tempo")
    assert "7 real span(s)" in tempo_item.detail
    assert "checkout-service" in tempo_item.detail
    assert "payment-service" in tempo_item.detail
    # The critical distinction must survive enrichment.
    assert "NOT a confirmed causal link" in tempo_item.detail


async def test_tempo_detail_labels_limitation_when_unavailable():
    trace_id = "abcd1234" * 4
    collector = _collector(
        tempo=FakeTempo(
            traces=[
                TraceSummary(
                    trace_id=trace_id,
                    root_service_name="checkout-service",
                    root_trace_name="POST /checkouts",
                    start_time=datetime(2026, 4, 1, 9, 1, 0, tzinfo=UTC),
                    duration_ms=42,
                )
            ],
            details={},  # no detail available for this trace_id
        )
    )
    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    tempo_item = next(i for i in package.items if i.source == "tempo")
    assert "detailed span retrieval unavailable" in tempo_item.detail
    assert "NOT a confirmed causal link" in tempo_item.detail
