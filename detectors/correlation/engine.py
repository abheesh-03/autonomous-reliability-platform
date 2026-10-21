"""Gate E: the deterministic correlation engine.

Two tiers, never conflated (correction-round Issue 3, tightened again
in the final evidence-integrity round -- Issue A):

  STRONG (drives an actual merge into one `CorrelationGroup`):
    1. a shared, validated trace id;
    2. a matching exact incident source fingerprint;
    3. their time windows overlap AND an `OBSERVED_DEPENDENCY` edge
       connects their services AND that edge's own `related_trace_ids`
       are ATTRIBUTABLE TO BOTH findings -- i.e. the edge's trace
       evidence overlaps with finding A's own `trace_ids` AND ALSO
       with finding B's own `trace_ids` (either the same shared trace
       id, which the "shared trace id" rule above would already catch
       directly, or two different ids, one matching each finding).
       `edge.error_observed` is never, on its own or combined with
       only a ONE-SIDED trace match, sufficient -- a generic observed
       error on a dependency edge could belong to any occurrence of
       that edge, not necessarily either of these two SPECIFIC
       findings (Issue A's exact reproduction: an edge whose evidence
       belongs to an unrelated third trace C must never strongly
       correlate findings A and B). Aggregate, non-trace-attributed
       findings (e.g. Prometheus-metric-only anomalies, which always
       carry empty `trace_ids`) can therefore never reach STRONG via
       this path -- their dependency association is always, honestly,
       reported as tentative instead of a fabricated incident-level
       trace linkage.

  WEAK (recorded as a `TentativeAssociation`, NEVER merged):
    4. their time windows overlap AND they merely share a service
       identity, with no trace/fingerprint/doubly-attributed-edge
       link; or
    5. their time windows overlap AND a dependency edge connects their
       services, but with no evidence, a generic unattributed error,
       or only a ONE-SIDED trace match (attributable to just one of
       the two findings, which says nothing about the other).

Grouping uses union-find over STRONG links only, so strong
correlation is transitive within one run (A-B strong, B-C strong =>
A,B,C one group) -- but a WEAK link never calls union(), so it can
never, even transitively through a chain of other items, collapse an
otherwise-unrelated cluster. `correlation_group_id` is derived from a
stable hash of the SORTED member item ids -- reproducible for a fixed
input set and algorithm version, never dependent on input order or a
mutable counter; the same applies to `TentativeAssociation.item_ids`.
"""

import hashlib

from detectors.schemas.correlation import CorrelationGroup, CorrelationInput, TentativeAssociation
from detectors.schemas.dependency import DependencyEdge, DependencyGraph

ALGORITHM_VERSION = "v1"

# A weak association is always reported at a low, fixed confidence --
# never implying it is anything more than a plausible, unmerged pairing.
_WEAK_ASSOCIATION_CONFIDENCE = 0.25


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self._parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic tie-break -- always attach the
            # lexicographically larger root under the smaller, so the
            # final grouping never depends on call order.
            if ra < rb:
                self._parent[rb] = ra
            else:
                self._parent[ra] = rb


def _windows_overlap(a: CorrelationInput, b: CorrelationInput) -> bool:
    return a.window_start <= b.window_end and b.window_start <= a.window_end


def _edge_connects(edge: DependencyEdge, a_services: frozenset[str], b_services: frozenset[str]) -> bool:
    return (edge.upstream_service in a_services and edge.downstream_service in b_services) or (
        edge.upstream_service in b_services and edge.downstream_service in a_services
    )


def _edge_has_incident_relevant_evidence(edge: DependencyEdge, a: CorrelationInput, b: CorrelationInput) -> bool:
    """Issue A fix: an edge existing in the graph is structural, not
    evidentiary -- and a bare `error_observed=True` is GENERIC (the
    error could belong to any occurrence of that dependency, not
    necessarily either of these two specific findings). The edge is
    only ATTRIBUTABLE to this specific (a, b) pair when its own
    `related_trace_ids` overlap with BOTH finding A's trace ids AND
    finding B's trace ids -- never a one-sided match (attributable to
    only one of the two, which establishes nothing about the other),
    and never `error_observed` alone with no trace corroboration."""
    if not edge.related_trace_ids:
        return False
    edge_traces = set(edge.related_trace_ids)
    return bool(edge_traces & a.trace_ids) and bool(edge_traces & b.trace_ids)


def _find_connecting_edge(
    a: CorrelationInput, b: CorrelationInput, graph: DependencyGraph | None, *, require_evidence: bool
) -> DependencyEdge | None:
    if graph is None:
        return None
    for edge in graph.edges:
        if not _edge_connects(edge, a.services, b.services):
            continue
        if require_evidence and not _edge_has_incident_relevant_evidence(edge, a, b):
            continue
        if not require_evidence and _edge_has_incident_relevant_evidence(edge, a, b):
            continue  # already classified as evidenced -- let the strong-tier check claim it instead
        return edge
    return None


def _classify_link(
    a: CorrelationInput, b: CorrelationInput, graph: DependencyGraph | None
) -> tuple[str | None, str | None]:
    """Returns (strength, reason) -- strength is 'strong', 'weak', or
    None (no basis for any association at all)."""
    shared_traces = a.trace_ids & b.trace_ids
    if shared_traces:
        return "strong", f"shared trace id(s): {sorted(shared_traces)}"
    if a.fingerprint is not None and a.fingerprint == b.fingerprint:
        return "strong", f"matching source fingerprint: {a.fingerprint}"

    if not _windows_overlap(a, b):
        return None, None

    evidenced_edge = _find_connecting_edge(a, b, graph, require_evidence=True)
    if evidenced_edge is not None:
        return "strong", (
            f"overlapping time window + observed dependency edge {evidenced_edge.upstream_service} -> "
            f"{evidenced_edge.downstream_service} whose own related_trace_ids="
            f"{evidenced_edge.related_trace_ids} are attributable to BOTH findings' own trace ids "
            f"(a={sorted(a.trace_ids)}, b={sorted(b.trace_ids)})"
        )

    shared_services = a.services & b.services
    if shared_services:
        return "weak", (
            f"overlapping time window + shared service(s) {sorted(shared_services)} only -- no shared trace id, "
            "fingerprint, or doubly-attributed dependency edge"
        )

    unevidenced_edge = _find_connecting_edge(a, b, graph, require_evidence=False)
    if unevidenced_edge is not None:
        return "weak", (
            f"overlapping time window + a dependency edge {unevidenced_edge.upstream_service} -> "
            f"{unevidenced_edge.downstream_service} exists in the graph (error_observed="
            f"{unevidenced_edge.error_observed}), but its trace evidence is not attributable to BOTH "
            "findings specifically -- a generic or one-sided edge can never establish shared incident identity"
        )

    return None, None


def correlate(
    items: list[CorrelationInput],
    dependency_graph: DependencyGraph | None = None,
) -> tuple[list[CorrelationGroup], list[TentativeAssociation]]:
    # Deduplicate deterministic repeated observations (same item_id
    # submitted more than once) before any linking runs.
    by_id: dict[str, CorrelationInput] = {}
    for item in items:
        by_id.setdefault(item.item_id, item)
    ids = sorted(by_id.keys())

    uf = _UnionFind(ids)
    strong_link_reasons: dict[tuple[str, str], str] = {}
    weak_links: list[tuple[str, str, str]] = []

    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1 :]:
            a, b = by_id[a_id], by_id[b_id]
            strength, reason = _classify_link(a, b, dependency_graph)
            if strength == "strong":
                uf.union(a_id, b_id)
                strong_link_reasons[(a_id, b_id)] = reason
            elif strength == "weak":
                weak_links.append((a_id, b_id, reason))

    clusters: dict[str, list[str]] = {}
    for item_id in ids:
        root = uf.find(item_id)
        clusters.setdefault(root, []).append(item_id)

    groups: list[CorrelationGroup] = []
    for member_ids in clusters.values():
        if len(member_ids) < 2:
            continue  # a correlation group requires at least two STRONGLY linked items -- singletons are reported elsewhere, never suppressed
        member_ids_sorted = sorted(member_ids)
        group_hash = hashlib.sha256("|".join(member_ids_sorted).encode()).hexdigest()[:12]
        group_id = f"corr-{group_hash}"

        members = [by_id[i] for i in member_ids_sorted]
        correlated_services = sorted({s for m in members for s in m.services})
        shared_evidence = sorted(
            {
                strong_link_reasons[(a, b)]
                for idx, a in enumerate(member_ids_sorted)
                for b in member_ids_sorted[idx + 1 :]
                if (a, b) in strong_link_reasons
            }
        )
        independently_observed_anomalies = sorted({m.item_id for m in members if m.kind == "anomaly"})
        evidence_gaps = []
        if dependency_graph is None:
            evidence_gaps.append("no dependency graph was supplied -- edge-based correlation was unavailable for this run")

        groups.append(
            CorrelationGroup(
                correlation_group_id=group_id,
                grouped_finding_ids=member_ids_sorted,
                correlated_services=correlated_services,
                shared_evidence=shared_evidence,
                correlation_rationale=(
                    f"{len(member_ids_sorted)} finding(s) linked via STRONG evidence only: {'; '.join(shared_evidence)}"
                ),
                confidence=min(0.5 + 0.15 * (len(shared_evidence) - 1), 0.9) if shared_evidence else 0.5,
                independently_observed_anomalies=independently_observed_anomalies,
                evidence_gaps=evidence_gaps,
                root_cause_hypotheses=[
                    f"these findings may share a common cause via: {reason}" for reason in shared_evidence
                ],
                algorithm_version=ALGORITHM_VERSION,
            )
        )

    groups.sort(key=lambda g: g.correlation_group_id)

    # Weak links between items that ALSO ended up in the same strong
    # group (via some other, genuine strong path) are redundant --
    # reported once, as the group, never duplicated as a tentative
    # association too.
    tentative_associations = [
        TentativeAssociation(
            item_ids=sorted([a_id, b_id]),
            rationale=reason,
            confidence=_WEAK_ASSOCIATION_CONFIDENCE,
            algorithm_version=ALGORITHM_VERSION,
        )
        for a_id, b_id, reason in weak_links
        if uf.find(a_id) != uf.find(b_id)
    ]
    tentative_associations.sort(key=lambda t: t.item_ids)

    return groups, tentative_associations
