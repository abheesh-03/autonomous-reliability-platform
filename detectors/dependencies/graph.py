"""Gate C: builds a `DependencyGraph` of OBSERVED_DEPENDENCY edges
ONLY -- every edge here is a direct consequence of a real parent-child
span relationship between two DIFFERENT services, aggregated across
however many parsed traces actually exhibited it. A trace flagged
`has_cycle` is skipped entirely for edge-building (never partially
trusted), so a corrupted/cyclic span structure can never corrupt the
graph or hang traversal. A span whose parent was not found in its own
trace (sampling/truncation) simply contributes no edge for that one
hop -- never a fabricated one."""

import statistics
from datetime import datetime

from detectors.schemas.dependency import DependencyEdge, DependencyEdgeLabel, DependencyGraph, TraceParseResult


def build_dependency_graph(
    trace_results: list[TraceParseResult], window_start: datetime, window_end: datetime
) -> DependencyGraph:
    traces_considered = len(trace_results)
    skipped_cyclic = 0
    services_observed: set[str] = set()
    edge_accum: dict[tuple[str, str], dict] = {}

    for tr in trace_results:
        for s in tr.spans:
            if s.service_name:
                services_observed.add(s.service_name)
        if tr.has_cycle:
            skipped_cyclic += 1
            continue

        by_id = {s.span_id: s for s in tr.spans}
        for s in tr.spans:
            if s.parent_span_id is None:
                continue
            parent = by_id.get(s.parent_span_id)
            if parent is None:
                continue  # missing parent (sampling/truncation) -- already captured in spans_with_missing_parent
            if not s.service_name or not parent.service_name or s.service_name == parent.service_name:
                continue  # not an attributable cross-service edge

            key = (parent.service_name, s.service_name)
            bucket = edge_accum.setdefault(
                key, {"trace_ids": set(), "span_ids": set(), "latencies_ms": [], "error_observed": False}
            )
            bucket["trace_ids"].add(tr.trace_id)
            bucket["span_ids"].add(s.span_id)
            if s.error is True:
                bucket["error_observed"] = True
            if (
                s.start_time_unix_nano is not None
                and s.end_time_unix_nano is not None
                and s.end_time_unix_nano >= s.start_time_unix_nano
            ):
                bucket["latencies_ms"].append((s.end_time_unix_nano - s.start_time_unix_nano) / 1_000_000)

    edges: list[DependencyEdge] = []
    for (upstream, downstream), bucket in sorted(edge_accum.items()):
        latencies = bucket["latencies_ms"]
        edges.append(
            DependencyEdge(
                upstream_service=upstream,
                downstream_service=downstream,
                label=DependencyEdgeLabel.OBSERVED_DEPENDENCY,
                observation_count=len(bucket["span_ids"]),
                observed_window_start=window_start.isoformat(),
                observed_window_end=window_end.isoformat(),
                related_trace_ids=sorted(bucket["trace_ids"]),
                supporting_span_ids=sorted(bucket["span_ids"]),
                latency_contribution_ms=statistics.median(latencies) if latencies else None,
                error_observed=bucket["error_observed"],
                missing_data_caveats=(
                    [] if latencies else ["no supporting span reported both a start and end time"]
                ),
            )
        )

    return DependencyGraph(
        edges=edges,
        observed_window_start=window_start.isoformat(),
        observed_window_end=window_end.isoformat(),
        traces_considered=traces_considered,
        traces_with_cycles_skipped=skipped_cyclic,
        services_observed=sorted(services_observed),
    )
