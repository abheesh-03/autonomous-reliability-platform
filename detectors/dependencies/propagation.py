"""Gate C: builds candidate propagation explanations for an anomalous
CALLING service, using ONLY real `OBSERVED_DEPENDENCY` edges plus
actual anomaly/error evidence on the CALLEE (downstream, in the
call/trace-structural sense) side -- never from temporal co-occurrence
alone. Two services with no observed edge between them can never
produce a path here, regardless of how suspicious their timing looks.

Orientation, stated explicitly because it is easy to get backwards: a
SYMPTOM typically appears on the UPSTREAM/CALLING service (e.g.
checkout-service, which synchronously waits on its downstream calls),
while the CANDIDATE ROOT CAUSE is the DOWNSTREAM/CALLEE service it
depends on (e.g. payment-service) -- matching Gate C's own example
("a failing downstream payment authorization may cause checkout to
fail"). So this module looks for anomalous services acting as the
UPSTREAM/caller side of an observed edge, and proposes the edge's
DOWNSTREAM/callee service as the candidate explanation -- never the
reverse.

A path's `candidate_root_cause_service` is always exactly that -- a
CANDIDATE, confidence always < 1.0, and the rationale states the
specific evidence (an observed edge, plus a callee anomaly and/or an
error observed on the connecting spans) rather than asserting a proven
cause."""

from detectors.schemas.dependency import DependencyEdge, DependencyGraph, PropagationPath

# Evidence-weighted, fixed, reviewed confidence contributions -- never
# LLM-decided, never exceeding 1.0 in total.
_EDGE_OBSERVED_WEIGHT = 0.3
_UPSTREAM_ANOMALY_WEIGHT = 0.4
_EDGE_ERROR_OBSERVED_WEIGHT = 0.25
_MAX_CONFIDENCE = 0.95  # never 1.0 -- a candidate is never asserted as certain


def build_propagation_paths(
    graph: DependencyGraph,
    anomalous_services: dict[str, list[str]],  # service -> detector_ids with ANOMALY_DETECTED
) -> list[PropagationPath]:
    edges_by_upstream: dict[str, list[DependencyEdge]] = {}
    for edge in graph.edges:
        edges_by_upstream.setdefault(edge.upstream_service, []).append(edge)

    paths: list[PropagationPath] = []
    path_counter = 0
    for caller_service, caller_detector_ids in sorted(anomalous_services.items()):
        for edge in edges_by_upstream.get(caller_service, []):
            callee_service = edge.downstream_service
            callee_detector_ids = anomalous_services.get(callee_service, [])

            if not callee_detector_ids and not edge.error_observed:
                # No supporting evidence beyond the edge merely
                # existing -- an observed dependency alone is not
                # enough to propose a propagation explanation.
                continue

            confidence = _EDGE_OBSERVED_WEIGHT
            evidence_bits = [f"observed dependency {caller_service} -> {callee_service}"]
            if callee_detector_ids:
                confidence += _UPSTREAM_ANOMALY_WEIGHT
                evidence_bits.append(f"{callee_service} itself has anomaly finding(s): {callee_detector_ids}")
            if edge.error_observed:
                confidence += _EDGE_ERROR_OBSERVED_WEIGHT
                evidence_bits.append("connecting spans themselves recorded an error status")
            confidence = min(confidence, _MAX_CONFIDENCE)

            path_counter += 1
            paths.append(
                PropagationPath(
                    path_id=f"propagation-{path_counter:04d}",
                    services_in_path=[caller_service, callee_service],
                    supporting_edges=[edge],
                    candidate_root_cause_service=callee_service,
                    supporting_anomaly_detector_ids=sorted(set(caller_detector_ids) | set(callee_detector_ids)),
                    confidence=round(confidence, 3),
                    rationale=(
                        f"{caller_service} shows anomaly finding(s) {caller_detector_ids}; "
                        + "; ".join(evidence_bits)
                        + f". {callee_service} is a CANDIDATE root cause, not an established fact."
                    ),
                )
            )
    return paths
