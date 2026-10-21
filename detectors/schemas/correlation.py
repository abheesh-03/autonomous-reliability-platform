"""Gate E: deterministic, multi-signal incident correlation.

Correction-round Issue 3: a `CorrelationGroup` (an actual MERGE of
findings) is now only ever formed from a STRONG, attributable rule --
a shared validated trace id, a matching exact incident fingerprint, or
an `OBSERVED_DEPENDENCY` edge that itself carries incident-relevant
supporting evidence (an observed error, or a trace id shared with one
of the two findings) -- never merely "two findings share a service and
their windows overlap", and never an edge that exists somewhere in the
graph with no evidence tying it to these specific findings. That
weaker combination (shared service + overlapping window, or a
structurally-present-but-unevidenced edge) is still recorded, but only
as a `TentativeAssociation` -- a plausible, WEAK, NEVER-merged
pairing, so the signal is never silently discarded, but it also never
collapses two independently-caused incidents into one asserted group.
Weak associations never participate in the union-find merge, so a
weak link can never transitively collapse an unrelated cluster, even
through a chain of other items."""

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class CorrelationInput:
    """One normalized, correlatable signal -- an anomaly result, an
    invariant violation, or a dependency-edge observation -- reduced to
    exactly what the correlation rule needs: which service(s) it
    concerns, its time window, and any trace id / incident fingerprint
    it carries."""

    item_id: str
    kind: str  # "anomaly" | "invariant_violation" | "dependency_edge"
    services: frozenset[str]
    window_start: datetime
    window_end: datetime
    trace_ids: frozenset[str] = frozenset()
    fingerprint: str | None = None


class CorrelationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_group_id: str
    grouped_finding_ids: list[str]
    correlated_services: list[str]
    shared_evidence: list[str]
    correlation_rationale: str
    confidence: float
    candidate_affected_dependency_paths: list[str] = []
    independently_observed_anomalies: list[str] = []
    evidence_gaps: list[str] = []
    root_cause_hypotheses: list[str] = []
    algorithm_version: str = "v1"


class TentativeAssociation(BaseModel):
    """A WEAK, plausible pairing that never merges -- the two
    findings' own item ids are preserved exactly as submitted, never
    folded into a `CorrelationGroup`. Confidence is always low and the
    rationale always states the specific weak signal (shared service +
    overlapping window, or an unevidenced structural dependency edge),
    never implying a stronger basis than actually exists."""

    model_config = ConfigDict(extra="forbid")

    item_ids: list[str]
    rationale: str
    confidence: float
    algorithm_version: str = "v1"
