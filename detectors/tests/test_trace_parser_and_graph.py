"""Gate H (DEPENDENCY/TRACING): exercises the real OTLP-JSON span
parser, cycle detection, and dependency-graph builder against
synthetic (but structurally real-shaped) Tempo trace bodies."""

import base64
import os

from detectors.dependencies.graph import build_dependency_graph
from detectors.dependencies.propagation import build_propagation_paths
from detectors.traces.parser import parse_trace_detail
from datetime import UTC, datetime, timedelta

WINDOW_START = datetime(2026, 6, 1, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(minutes=10)


def _b64_of_hex(hex_str: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_str)).decode()


TRACE_ID = "11" * 16
SPAN_A = "aa" * 8  # checkout server span (root)
SPAN_B = "bb" * 8  # checkout -> payment client span
SPAN_C = "cc" * 8  # payment server span
SPAN_D = "dd" * 8  # payment -> inventory client span (3-hop chain)
SPAN_E = "ee" * 8  # inventory server span


def _span(span_id, parent_id, service, kind, start_ns=1000, end_ns=2000, error=None, trace_id=TRACE_ID):
    span = {
        "traceId": _b64_of_hex(trace_id),
        "spanId": _b64_of_hex(span_id),
        "kind": kind,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
    }
    if parent_id is not None:
        span["parentSpanId"] = _b64_of_hex(parent_id)
    if error is not None:
        span["status"] = {"code": "STATUS_CODE_ERROR" if error else "STATUS_CODE_OK"}
    return span, service


def _trace_body(*span_service_pairs) -> dict:
    by_service: dict[str, list[dict]] = {}
    for span, service in span_service_pairs:
        by_service.setdefault(service, []).append(span)
    resource_spans = []
    for service, spans in by_service.items():
        resource_spans.append(
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
                "scopeSpans": [{"spans": spans}],
            }
        )
    return {"trace": {"resourceSpans": resource_spans}}


# ---------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------


def test_normal_single_service_trace_parses_with_one_root_no_cycle():
    body = _trace_body(_span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"))
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 1
    assert result.root_span_ids == [SPAN_A]
    assert result.has_cycle is False
    assert result.spans_with_missing_parent == []


def test_multi_service_dependency_chain_parses_all_spans():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "checkout-service", "SPAN_KIND_CLIENT"),
        _span(SPAN_C, SPAN_B, "payment-service", "SPAN_KIND_SERVER"),
        _span(SPAN_D, SPAN_C, "payment-service", "SPAN_KIND_CLIENT"),
        _span(SPAN_E, SPAN_D, "inventory-service", "SPAN_KIND_SERVER"),
    )
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 5
    assert result.root_span_ids == [SPAN_A]
    assert result.has_cycle is False


def test_missing_parent_span_is_recorded_not_silently_dropped():
    """A partial/sampled trace: SPAN_C's parent (SPAN_B) was never
    returned by Tempo at all."""
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_C, SPAN_B, "payment-service", "SPAN_KIND_SERVER"),  # parent SPAN_B absent
    )
    result = parse_trace_detail(TRACE_ID, body)
    assert result.spans_with_missing_parent == [SPAN_C]


def test_ambiguous_service_identity_span_has_none_service_name():
    body = {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},  # no service.name attribute at all
                    "scopeSpans": [{"spans": [_span(SPAN_A, None, "ignored", "SPAN_KIND_SERVER")[0]]}],
                }
            ]
        }
    }
    result = parse_trace_detail(TRACE_ID, body)
    assert result.spans[0].service_name is None


def test_duplicate_span_ids_do_not_crash_parsing_or_cycle_detection():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),  # duplicate span_id
    )
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 2  # both kept, never silently deduplicated or crashed on
    assert result.has_cycle is False


def test_malformed_trace_body_produces_zero_spans_not_a_crash():
    result = parse_trace_detail(TRACE_ID, {"trace": "not-a-dict"})
    assert result.spans == []

    result2 = parse_trace_detail(TRACE_ID, "not-even-a-dict")
    assert result2.spans == []
    assert result2.malformed_span_count == 1


def test_non_object_resource_does_not_crash_the_parser():
    """Correction-round Issue 4A exact reproduction: `resource` is a
    bare string, not an object -- must never raise AttributeError."""
    body = {"trace": {"resourceSpans": [{"resource": "not-an-object", "scopeSpans": []}]}}
    result = parse_trace_detail(TRACE_ID, body)  # must not raise
    assert result.spans == []


def test_malformed_service_name_attribute_value_does_not_crash():
    """`value` under the service.name attribute is itself malformed
    (not an object) -- the span must still parse, with service_name=None."""
    body = {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": "not-an-object"}]},
                    "scopeSpans": [{"spans": [_span(SPAN_A, None, "ignored", "SPAN_KIND_SERVER")[0]]}],
                }
            ]
        }
    }
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 1
    assert result.spans[0].service_name is None


def test_incorrect_nested_types_for_scopespans_and_spans_are_malformed_not_crashes():
    body_bad_scope_spans = {
        "trace": {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": "not-a-list"}]}
    }
    result1 = parse_trace_detail(TRACE_ID, body_bad_scope_spans)
    assert result1.spans == []
    assert result1.malformed_span_count == 1

    body_bad_spans_list = {
        "trace": {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [{"spans": "not-a-list"}]}]}
    }
    result2 = parse_trace_detail(TRACE_ID, body_bad_spans_list)
    assert result2.spans == []
    assert result2.malformed_span_count == 1


def test_invalid_trace_and_span_ids_are_rejected_as_malformed():
    body = {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [{"spans": [
                        {"traceId": "not-valid-base64!!!", "spanId": _b64_of_hex(SPAN_A), "kind": "SPAN_KIND_SERVER"}
                    ]}],
                }
            ]
        }
    }
    result = parse_trace_detail(TRACE_ID, body)
    assert result.spans == []
    assert result.malformed_span_count == 1


def test_mismatched_requested_and_returned_trace_id_is_rejected_not_trusted():
    """Correction-round Issue 4B exact reproduction: the requested
    trace id is 'bbbb...', but the returned spans belong to 'aaaa...'
    -- must be rejected (trace_id_mismatch_count), never silently
    accepted as evidence for the requested trace."""
    requested_trace_id = "bb" * 16
    actual_span_trace_id = "aa" * 16
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER", trace_id=actual_span_trace_id),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER", trace_id=actual_span_trace_id),
    )
    result = parse_trace_detail(requested_trace_id, body)
    assert result.spans == []
    assert result.trace_id_mismatch_count == 2

    # And critically: no dependency edge can ever be attributed to the
    # requested trace from rejected, mismatched evidence.
    graph = build_dependency_graph([result], WINDOW_START, WINDOW_END)
    assert graph.edges == []


def test_partially_valid_trace_keeps_the_valid_spans_and_counts_the_rest():
    """A mix of one genuinely valid span and one malformed span in the
    SAME trace response (same resourceSpans/scopeSpans entry) -- the
    valid span must still be kept, and the malformed one counted,
    never silently dropped with no trace."""
    valid_span, _ = _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER")
    body = {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout-service"}}]},
                    "scopeSpans": [{"spans": [valid_span, "not-a-span-object"]}],
                }
            ]
        }
    }
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 1
    assert result.spans[0].span_id == SPAN_A
    assert result.malformed_span_count == 1


def test_valid_multi_service_trace_still_extracts_correctly_after_hardening():
    """Non-regression: the hardening in this correction round must not
    break ordinary, well-formed multi-service trace extraction."""
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "checkout-service", "SPAN_KIND_CLIENT"),
        _span(SPAN_C, SPAN_B, "payment-service", "SPAN_KIND_SERVER"),
    )
    result = parse_trace_detail(TRACE_ID, body)
    assert len(result.spans) == 3
    assert result.malformed_span_count == 0
    assert result.trace_id_mismatch_count == 0
    assert result.has_cycle is False


def test_cyclic_span_structure_is_detected_and_does_not_hang():
    """SPAN_A's parent is SPAN_B and SPAN_B's parent is SPAN_A -- a
    genuine cycle. Must terminate and report has_cycle=True."""
    body = _trace_body(
        _span(SPAN_A, SPAN_B, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "checkout-service", "SPAN_KIND_CLIENT"),
    )
    result = parse_trace_detail(TRACE_ID, body)
    assert result.has_cycle is True


def test_status_absent_is_none_not_coerced_to_false():
    body = _trace_body(_span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER", error=None))
    result = parse_trace_detail(TRACE_ID, body)
    assert result.spans[0].error is None


def test_status_error_is_captured_true():
    body = _trace_body(_span(SPAN_A, None, "payment-service", "SPAN_KIND_SERVER", error=True))
    result = parse_trace_detail(TRACE_ID, body)
    assert result.spans[0].error is True


# ---------------------------------------------------------------------
# dependency graph
# ---------------------------------------------------------------------


def test_pipeline_continuation_when_one_trace_is_malformed():
    """Correction-round Issue 4: a batch containing one fully
    malformed trace response (non-object resource) alongside one
    genuinely valid trace must still produce a correct dependency
    graph from the valid trace -- a malformed trace must never abort
    the whole batch."""
    malformed_body = {"trace": {"resourceSpans": [{"resource": "not-an-object", "scopeSpans": []}]}}
    malformed_result = parse_trace_detail("22" * 16, malformed_body)
    assert malformed_result.spans == []  # confirmed malformed, not crashed

    valid_body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER"),
    )
    valid_result = parse_trace_detail(TRACE_ID, valid_body)

    graph = build_dependency_graph([malformed_result, valid_result], WINDOW_START, WINDOW_END)
    assert graph.traces_considered == 2
    assert len(graph.edges) == 1
    assert (graph.edges[0].upstream_service, graph.edges[0].downstream_service) == ("checkout-service", "payment-service")


def test_dependency_graph_builds_observed_edges_from_real_chain():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER", start_ns=0, end_ns=5000),
        _span(SPAN_B, SPAN_A, "checkout-service", "SPAN_KIND_CLIENT", start_ns=100, end_ns=4900),
        _span(SPAN_C, SPAN_B, "payment-service", "SPAN_KIND_SERVER", start_ns=200, end_ns=4800),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert (edge.upstream_service, edge.downstream_service) == ("checkout-service", "payment-service")
    assert edge.observation_count == 1
    assert edge.latency_contribution_ms == (4800 - 200) / 1_000_000


def test_cyclic_trace_is_skipped_entirely_from_graph_building():
    body = _trace_body(
        _span(SPAN_A, SPAN_B, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_CLIENT"),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    assert graph.edges == []
    assert graph.traces_with_cycles_skipped == 1


def test_same_service_parent_child_is_not_a_dependency_edge():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "checkout-service", "SPAN_KIND_INTERNAL"),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    assert graph.edges == []


def test_unrelated_trace_in_same_window_contributes_independent_edges_only():
    """Two traces in the same window touching entirely different
    services must never be merged into one fabricated cross-trace
    edge."""
    trace_id_1 = "11" * 16
    trace_id_2 = "22" * 16
    body1 = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER", trace_id=trace_id_1),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER", trace_id=trace_id_1),
    )
    body2 = _trace_body(
        _span(SPAN_D, None, "notification-service", "SPAN_KIND_SERVER", trace_id=trace_id_2),
        _span(SPAN_E, SPAN_D, "inventory-service", "SPAN_KIND_SERVER", trace_id=trace_id_2),
    )
    trace1 = parse_trace_detail(trace_id_1, body1)
    trace2 = parse_trace_detail(trace_id_2, body2)
    graph = build_dependency_graph([trace1, trace2], WINDOW_START, WINDOW_END)
    pairs = {(e.upstream_service, e.downstream_service) for e in graph.edges}
    assert pairs == {("checkout-service", "payment-service"), ("notification-service", "inventory-service")}


def test_zero_duration_span_still_counts_as_valid_timing_not_missing():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER", start_ns=0, end_ns=0),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    assert graph.edges[0].latency_contribution_ms == 0.0
    assert graph.edges[0].missing_data_caveats == []


# ---------------------------------------------------------------------
# propagation (no unsupported causal claims)
# ---------------------------------------------------------------------


def test_propagation_path_created_when_upstream_anomalous():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER"),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    paths = build_propagation_paths(graph, anomalous_services={"payment-service": ["error_rate_deviation"], "checkout-service": ["latency_deviation"]})
    assert len(paths) == 1
    assert paths[0].candidate_root_cause_service == "payment-service"
    assert paths[0].confidence < 1.0
    assert "CANDIDATE" in paths[0].rationale


def test_no_propagation_path_without_any_supporting_evidence():
    """An observed edge alone, with NEITHER side anomalous nor any
    error observed, must never produce an unsupported causal claim."""
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER"),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    paths = build_propagation_paths(graph, anomalous_services={})
    assert paths == []


def test_propagation_path_created_from_error_observed_even_without_upstream_anomaly_flag():
    body = _trace_body(
        _span(SPAN_A, None, "checkout-service", "SPAN_KIND_SERVER"),
        _span(SPAN_B, SPAN_A, "payment-service", "SPAN_KIND_SERVER", error=True),
    )
    trace_result = parse_trace_detail(TRACE_ID, body)
    graph = build_dependency_graph([trace_result], WINDOW_START, WINDOW_END)
    paths = build_propagation_paths(graph, anomalous_services={"checkout-service": ["latency_deviation"]})
    assert len(paths) == 1
    assert paths[0].confidence < 1.0
