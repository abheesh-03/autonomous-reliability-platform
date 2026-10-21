"""Gate B: the anomaly-detection result contract. Every detector run
-- regardless of outcome -- produces exactly one `AnomalyDetectionResult`,
carrying enough evidence (actual observed/baseline values, the exact
algorithm/threshold used, and data-completeness) for a human or a
downstream consumer to judge the call themselves, never just a bare
verdict."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class DetectionResult(str, Enum):
    ANOMALY_DETECTED = "anomaly_detected"
    NO_ANOMALY = "no_anomaly"
    # Real samples exist but too few (or too little underlying traffic
    # volume) to support a confident statistical judgment -- NEVER
    # conflated with NO_ANOMALY (which asserts the system looks
    # healthy) or with TELEMETRY_UNAVAILABLE (which asserts the source
    # itself could not even be queried).
    INSUFFICIENT_DATA = "insufficient_data"
    # Prometheus itself could not be reached or returned a malformed
    # response for this query -- a collection failure, never evidence
    # that the monitored application itself is unhealthy.
    TELEMETRY_UNAVAILABLE = "telemetry_unavailable"


class WindowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: str
    window_end: str
    sample_count: int
    median: float | None = None
    mad: float | None = None  # median absolute deviation
    max_value: float | None = None
    min_value: float | None = None


class DataCompleteness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_sample_count: int
    baseline_sample_count: int
    malformed_value_count: int
    volume_sample_count: int | None = None
    # Correction-round Issue 1: how many ratio samples were DERIVED as
    # a confirmed zero-error observation (real, positive total traffic
    # at that timestamp, but no matching error-series sample) rather
    # than directly computed from two matching real samples -- always
    # explicit, never silently folded into observation/baseline counts
    # with no trace of which were derived.
    derived_zero_error_sample_count: int | None = None
    notes: str


class EvidenceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str
    query: str
    collected_at: str


class AnomalyDetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector_id: str
    algorithm_id: str
    algorithm_version: str
    metric_key: str
    service: str
    result: DetectionResult
    observation: WindowSummary
    baseline: WindowSummary
    threshold_used: float
    deviation_score: float | None = None
    persistence_fraction: float | None = None
    decision_rationale: str
    data_completeness: DataCompleteness
    evidence: EvidenceProvenance
