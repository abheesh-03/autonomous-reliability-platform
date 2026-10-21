"""Gate C: the dependency-graph contract. Every edge here is built
ONLY from real span parent/child structure actually observed in a real
trace -- never from an imagined static service list, and never merely
from two services appearing in the same time window. Everything this
module ever produces is OBSERVED_DEPENDENCY; the stronger,
incident-specific CANDIDATE_PROPAGATION/POSSIBLE_ROOT_CAUSE labels are
produced one layer up, in `detectors.dependencies.propagation`, and
only when actual anomaly/error evidence -- not mere temporal
correlation -- justifies them."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class SpanKind(str, Enum):
    SERVER = "SPAN_KIND_SERVER"
    CLIENT = "SPAN_KIND_CLIENT"
    INTERNAL = "SPAN_KIND_INTERNAL"
    PRODUCER = "SPAN_KIND_PRODUCER"
    CONSUMER = "SPAN_KIND_CONSUMER"
    UNSPECIFIED = "SPAN_KIND_UNSPECIFIED"
    UNKNOWN = "unknown"  # this repo observed a kind string outside the above


class SpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service_name: str | None = None
    kind: str | None = None
    start_time_unix_nano: int | None = None
    end_time_unix_nano: int | None = None
    # None = no status object was present on the span (unknown/unset,
    # per the OTLP spec's own STATUS_CODE_UNSET) -- never defaulted to
    # either True or False when genuinely absent.
    error: bool | None = None


class TraceParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    spans: list[SpanRecord]
    malformed_span_count: int
    # Correction-round Issue 4B: spans whose own decoded traceId did
    # NOT match the trace id this parse was actually requested for --
    # rejected, never trusted as evidence for the requested trace.
    trace_id_mismatch_count: int = 0
    has_cycle: bool
    root_span_ids: list[str]
    # A span whose parent_span_id is set but whose parent was not found
    # among this trace's own returned spans -- a real, common symptom
    # of sampling/truncation, never silently treated as "no parent".
    spans_with_missing_parent: list[str]


class DependencyEdgeLabel(str, Enum):
    OBSERVED_DEPENDENCY = "observed_dependency"
    CANDIDATE_PROPAGATION = "candidate_propagation"
    POSSIBLE_ROOT_CAUSE = "possible_root_cause"


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream_service: str
    downstream_service: str
    label: DependencyEdgeLabel
    observation_count: int
    observed_window_start: str
    observed_window_end: str
    related_trace_ids: list[str]
    supporting_span_ids: list[str]
    latency_contribution_ms: float | None = None
    error_observed: bool = False
    missing_data_caveats: list[str] = []


class DependencyGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[DependencyEdge]
    observed_window_start: str
    observed_window_end: str
    traces_considered: int
    traces_with_cycles_skipped: int
    services_observed: list[str]


class PropagationPath(BaseModel):
    """A candidate, EVIDENCE-GROUNDED explanation for why a downstream
    service shows symptoms -- never a proven causal claim. See
    `detectors.dependencies.propagation` for how `supporting_edges` and
    `supporting_anomaly_detector_ids` are actually required, not
    inferred from timing alone."""

    model_config = ConfigDict(extra="forbid")

    path_id: str
    services_in_path: list[str]  # ordered upstream -> downstream
    supporting_edges: list[DependencyEdge]
    candidate_root_cause_service: str | None
    supporting_anomaly_detector_ids: list[str]
    confidence: float
    rationale: str
