"""Gate H (CORRELATION): exercises the real deterministic correlation
engine against synthetic inputs. `correlate()` returns
`(groups, tentative_associations)` -- STRONG links merge into a
`CorrelationGroup`; WEAK links (shared service + overlapping window
alone, or a dependency edge with no evidence, a generic unattributed
error, or only a ONE-SIDED trace match) are recorded as
`TentativeAssociation`s and NEVER merged (correction-round Issue 3,
tightened further in the final evidence-integrity round's Issue A:
`error_observed` alone is never sufficient -- an edge must be
attributable, via its own `related_trace_ids`, to BOTH findings'
trace ids specifically)."""

import random
from datetime import UTC, datetime, timedelta

from detectors.correlation.engine import correlate
from detectors.schemas.correlation import CorrelationInput
from detectors.schemas.dependency import DependencyEdge, DependencyEdgeLabel, DependencyGraph

T0 = datetime(2026, 6, 1, tzinfo=UTC)


def _item(item_id, services, start_offset_min=0, end_offset_min=5, trace_ids=frozenset(), fingerprint=None, kind="anomaly"):
    return CorrelationInput(
        item_id=item_id,
        kind=kind,
        services=frozenset(services),
        window_start=T0 + timedelta(minutes=start_offset_min),
        window_end=T0 + timedelta(minutes=end_offset_min),
        trace_ids=trace_ids,
        fingerprint=fingerprint,
    )


def _graph(*edges: tuple[str, str], related_trace_ids: tuple[str, ...] = ("unrelated-structural-trace",), error_observed: bool = False) -> DependencyGraph:
    """`related_trace_ids` is what the edge itself actually observed
    -- NEVER automatically attributed to any particular finding. A
    caller wanting a genuinely STRONG edge must give the two findings'
    own `trace_ids` values that overlap with `related_trace_ids` on
    BOTH sides (see `_doubly_attributed_graph` below for the common
    case). `error_observed=True` alone, with no such attribution, only
    ever produces a WEAK association (Issue A)."""
    return DependencyGraph(
        edges=[
            DependencyEdge(
                upstream_service=u, downstream_service=d, label=DependencyEdgeLabel.OBSERVED_DEPENDENCY,
                observation_count=1, observed_window_start=T0.isoformat(), observed_window_end=(T0 + timedelta(minutes=10)).isoformat(),
                related_trace_ids=list(related_trace_ids), supporting_span_ids=["s1"],
                error_observed=error_observed,
            )
            for u, d in edges
        ],
        observed_window_start=T0.isoformat(), observed_window_end=(T0 + timedelta(minutes=10)).isoformat(),
        traces_considered=1, traces_with_cycles_skipped=0, services_observed=sorted({s for pair in edges for s in pair}),
    )


# ---------------------------------------------------------------------
# strong links -- genuine merges, requiring DOUBLY-attributed trace evidence
# ---------------------------------------------------------------------


def test_genuinely_doubly_attributed_dependency_edge_is_correlated():
    """Both findings carry their own real trace ids, and the
    connecting edge's own related_trace_ids overlap with EACH of
    them specifically -- genuine, attributable evidence, not a
    generic error."""
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-checkout"})),
        _item("payment-errors", ["payment-service"], 1, 6, trace_ids=frozenset({"trace-payment"})),
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("trace-checkout", "trace-payment"))
    groups, weak = correlate(items, dependency_graph=graph)
    assert len(groups) == 1
    assert set(groups[0].grouped_finding_ids) == {"checkout-latency", "payment-errors"}
    assert weak == []


def test_duplicate_observations_are_deduplicated_not_double_grouped():
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-checkout"})),
        _item("checkout-latency", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-checkout"})),  # exact duplicate item_id
        _item("payment-errors", ["payment-service"], 1, 6, trace_ids=frozenset({"trace-payment"})),
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("trace-checkout", "trace-payment"))
    groups, _ = correlate(items, dependency_graph=graph)
    assert len(groups) == 1
    assert groups[0].grouped_finding_ids == ["checkout-latency", "payment-errors"]


def test_shared_trace_id_correlates_even_without_service_overlap_or_edge():
    items = [
        _item("finding-a", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-123"})),
        _item("finding-b", ["payment-service"], 50, 55, trace_ids=frozenset({"trace-123"})),  # far apart in time, no graph
    ]
    groups, weak = correlate(items, dependency_graph=None)
    assert len(groups) == 1
    assert "shared trace id" in groups[0].shared_evidence[0]
    assert weak == []


def test_matching_fingerprint_correlates_regardless_of_services():
    items = [
        _item("finding-a", ["checkout-service"], 0, 5, fingerprint="fp-abc"),
        _item("finding-b", ["payment-service"], 0, 5, fingerprint="fp-abc"),
    ]
    groups, _ = correlate(items, dependency_graph=None)
    assert len(groups) == 1


def test_incomplete_sources_recorded_as_evidence_gap_when_no_graph_supplied():
    items = [
        _item("finding-a", ["checkout-service"], 0, 5, fingerprint="fp-abc"),
        _item("finding-b", ["payment-service"], 0, 5, fingerprint="fp-abc"),
    ]
    groups, _ = correlate(items, dependency_graph=None)
    assert any("no dependency graph" in gap for gap in groups[0].evidence_gaps)


def test_reproducible_correlation_ids_regardless_of_input_order():
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5, trace_ids=frozenset({"t-cp"})),
        _item("payment-errors", ["payment-service"], 1, 6, trace_ids=frozenset({"t-cp", "t-pi"})),
        _item("inventory-errors", ["inventory-service"], 2, 7, trace_ids=frozenset({"t-pi"})),
    ]
    graph = DependencyGraph(
        edges=[
            DependencyEdge(
                upstream_service="checkout-service", downstream_service="payment-service", label=DependencyEdgeLabel.OBSERVED_DEPENDENCY,
                observation_count=1, observed_window_start=T0.isoformat(), observed_window_end=(T0 + timedelta(minutes=10)).isoformat(),
                related_trace_ids=["t-cp"], supporting_span_ids=["s1"],
            ),
            DependencyEdge(
                upstream_service="payment-service", downstream_service="inventory-service", label=DependencyEdgeLabel.OBSERVED_DEPENDENCY,
                observation_count=1, observed_window_start=T0.isoformat(), observed_window_end=(T0 + timedelta(minutes=10)).isoformat(),
                related_trace_ids=["t-pi"], supporting_span_ids=["s2"],
            ),
        ],
        observed_window_start=T0.isoformat(), observed_window_end=(T0 + timedelta(minutes=10)).isoformat(),
        traces_considered=1, traces_with_cycles_skipped=0,
        services_observed=["checkout-service", "payment-service", "inventory-service"],
    )

    groups_a, weak_a = correlate(items, dependency_graph=graph)
    shuffled = list(items)
    random.Random(42).shuffle(shuffled)
    groups_b, weak_b = correlate(shuffled, dependency_graph=graph)

    assert len(groups_a) == 1
    assert set(groups_a[0].grouped_finding_ids) == {"checkout-latency", "payment-errors", "inventory-errors"}
    assert [g.correlation_group_id for g in groups_a] == [g.correlation_group_id for g in groups_b]
    assert [g.grouped_finding_ids for g in groups_a] == [g.grouped_finding_ids for g in groups_b]
    assert [t.item_ids for t in weak_a] == [t.item_ids for t in weak_b]


def test_no_fabricated_root_cause_language():
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-checkout"})),
        _item("payment-errors", ["payment-service"], 1, 6, trace_ids=frozenset({"trace-payment"})),
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("trace-checkout", "trace-payment"))
    groups, _ = correlate(items, dependency_graph=graph)
    for hypothesis in groups[0].root_cause_hypotheses:
        assert "may share a common cause" in hypothesis
        assert "proven" not in hypothesis.lower() and "confirmed" not in hypothesis.lower()
    assert groups[0].confidence < 1.0


# ---------------------------------------------------------------------
# negative controls -- weak links must never merge (Issue 3 + Issue A)
# ---------------------------------------------------------------------


def test_unrelated_trace_error_edge_does_not_cause_strong_correlation():
    """Issue A exact reproduction: Finding A (checkout-service, trace
    A), Finding B (payment-service, trace B), overlapping windows. The
    observed checkout->payment edge belongs to an UNRELATED trace C
    and has error_observed=True. A generic error on a dependency edge
    must never, by itself, prove these two specific findings share an
    incident -- 0 strong groups; the structural relationship may still
    surface as a tentative association."""
    items = [
        _item("finding-a", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-A"})),
        _item("finding-b", ["payment-service"], 1, 6, trace_ids=frozenset({"trace-B"})),
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("trace-C",), error_observed=True)
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []
    assert len(weak) == 1
    assert weak[0].item_ids == ["finding-a", "finding-b"]
    assert weak[0].confidence < 0.5


def test_one_sided_trace_evidence_does_not_cause_strong_correlation():
    """The edge's related_trace_ids overlap with finding A's own
    trace (trace-A) but say NOTHING about finding B -- a one-sided
    match is insufficient to establish shared incident identity."""
    items = [
        _item("finding-a", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-A"})),
        _item("finding-b", ["payment-service"], 1, 6, trace_ids=frozenset({"trace-B"})),
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("trace-A",), error_observed=True)
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []
    assert len(weak) == 1


def test_two_independent_downstream_failures_stay_separate():
    """payment-service and inventory-service are BOTH structurally
    downstream of checkout-service, but no edge connects them directly
    at all -- must never be merged into one asserted group."""
    items = [
        _item("payment-errors", ["payment-service"], 0, 5),
        _item("inventory-errors", ["inventory-service"], 0, 5),
    ]
    graph = _graph(("checkout-service", "payment-service"), ("checkout-service", "inventory-service"))
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []  # no edge connects payment-service directly to inventory-service at all


def test_incidents_merely_sharing_an_unattributed_observed_dependency_stay_tentative():
    """An edge connects the two services and genuinely exists in the
    dependency graph, with no trace evidence tying it to EITHER of
    these two findings specifically -- weak, never merged."""
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5),
        _item("payment-errors", ["payment-service"], 1, 6),
    ]
    graph = _graph(("checkout-service", "payment-service"))
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []
    assert len(weak) == 1
    assert "not attributable to BOTH" in weak[0].rationale


def test_two_independent_incidents_remain_fully_unlinked():
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5),
        _item("notification-errors", ["notification-service"], 0, 5),
    ]
    groups, weak = correlate(items, dependency_graph=None)
    assert groups == []
    assert weak == []


def test_overlapping_but_unrelated_failures_stay_separate_even_with_a_graph():
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5),
        _item("notification-errors", ["notification-service"], 0, 5),
    ]
    # the graph exists but has NO edge connecting these two services at all
    graph = _graph(("checkout-service", "payment-service"), error_observed=True)
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []
    assert weak == []


def test_weak_evidence_shared_service_without_window_overlap_does_not_correlate_at_all():
    items = [
        _item("old-checkout-issue", ["checkout-service"], 0, 5),
        _item("new-checkout-issue", ["checkout-service"], 120, 125),  # same service, far apart in time
    ]
    groups, weak = correlate(items, dependency_graph=None)
    assert groups == []
    assert weak == []  # no window overlap -- not even a weak basis exists


def test_weak_link_does_not_transitively_collapse_an_unrelated_cluster():
    """A weakly-linked pair must never be chained through a third item
    into a merged group -- even if that third item is strongly linked
    to one of the two weak members, the weak pair itself stays
    unmerged with each other (though the strong pair merges on its
    own, correctly)."""
    items = [
        _item("checkout-weak-a", ["checkout-service"], 0, 5, trace_ids=frozenset({"trace-AAA"})),
        _item("checkout-weak-b", ["checkout-service"], 2, 7, trace_ids=frozenset({"trace-BBB"})),
        _item("payment-strong", ["payment-service"], 0, 5, trace_ids=frozenset({"trace-AAA"})),
    ]
    groups, weak = correlate(items, dependency_graph=None)
    # checkout-weak-a and payment-strong share trace-AAA -> STRONG, merge.
    assert len(groups) == 1
    assert set(groups[0].grouped_finding_ids) == {"checkout-weak-a", "payment-strong"}
    # checkout-weak-b must NOT be pulled into that group merely via its
    # weak (shared-service, overlapping-window) relationship to checkout-weak-a.
    assert "checkout-weak-b" not in groups[0].grouped_finding_ids
    assert len(weak) == 1
    assert weak[0].item_ids == ["checkout-weak-a", "checkout-weak-b"]


def test_unrelated_independent_incidents_are_not_suppressed_from_caller_view():
    """The engine returns no GROUP for unrelated items, but it never
    deletes them -- the caller (pipeline) still has both original
    CorrelationInput item_ids available independently of this result."""
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5),
        _item("notification-errors", ["notification-service"], 0, 5),
    ]
    groups, weak = correlate(items, dependency_graph=None)
    all_grouped_ids = {i for g in groups for i in g.grouped_finding_ids}
    assert all_grouped_ids == set()  # confirms: nothing fabricated, but the two original ids remain known to the caller via `items` itself
    assert {item.item_id for item in items} == {"checkout-latency", "notification-errors"}


def test_aggregate_anomalies_with_no_trace_attribution_never_reach_strong_via_an_edge():
    """Real-world case named explicitly in Issue A: aggregate
    Prometheus-metric anomalies carry NO trace ids at all (the
    pipeline's own orchestrator never attaches any). Even a fully
    evidenced, error-observed edge can never promote them to a strong
    merge -- only ever tentative."""
    items = [
        _item("checkout-latency", ["checkout-service"], 0, 5),  # trace_ids left empty, as the real pipeline does
        _item("payment-errors", ["payment-service"], 1, 6),  # trace_ids left empty
    ]
    graph = _graph(("checkout-service", "payment-service"), related_trace_ids=("some-real-trace",), error_observed=True)
    groups, weak = correlate(items, dependency_graph=graph)
    assert groups == []
    assert len(weak) == 1
