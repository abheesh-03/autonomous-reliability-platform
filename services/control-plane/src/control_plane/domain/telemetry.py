"""Phase 16 Gate 4: a BOUNDED, VALIDATED subset of the real OTLP/HTTP
metrics export schema (`ExportMetricsServiceRequest`).

CORRECTION ROUND (independent review): this module is now wire-format
agnostic -- the SAME shape is used whether the request arrived as real
OTLP/HTTP JSON or was converted from a real OTLP/HTTP **protobuf**
body (see `ingestion/otlp_protobuf.py`). Independent verification of
the official OpenTelemetry Python SDK's own HTTP metrics exporter
(`opentelemetry-exporter-otlp-proto-http==1.45.1`) found it hardcodes
`Content-Type: application/x-protobuf` and calls
`ExportMetricsServiceRequest.SerializeToString()` -- it has NO JSON
code path at all, regardless of `OTEL_EXPORTER_OTLP_PROTOCOL`. A
hand-rolled JSON client (samples/otel-sample-app/) is therefore NOT
proof that any official SDK is supported; protobuf support was added
specifically so a real official SDK/exporter could be exercised
end-to-end (see docs/architecture/phase-16-secure-telemetry-onboarding.md
Gate 3 section for the verification method and result).

The accepted metric shape remains narrow by design: exactly one
metric, `http.server.request.duration`, a Histogram, with UP TO three
attributes (`http.request.method`, `http.route`,
`http.response.status_code`) -- the same OTel semantic convention this
platform's own demo services already emit. Anything else (a different
metric name, a Sum/Gauge instead of a Histogram, additional
attributes) is REJECTED with a clear 400, never silently ignored or
guessed at.

TEMPORALITY (correction round): a real OTLP histogram declares
`aggregationTemporality` on the Histogram message itself -- DELTA (1)
means "since the last export," CUMULATIVE (2) means "since the
process/counter started." The previous round's parser ignored this
field entirely and treated every export as if it were a fresh delta,
which silently double-counts (or worse) a client that legitimately
sends CUMULATIVE histograms. This endpoint now REQUIRES DELTA and
rejects anything else outright (see `ingestion/telemetry_service.py`)
-- durable cumulative-to-delta conversion (tracking each timeseries'
own running total and diffing) is real, state-carrying work this
narrow MVP deliberately does not take on.

Every client-supplied field that could identify WHO this telemetry is
from (resource attributes like `service.name`, any attribute resembling
an organization id) is parsed, if present, but NEVER used to derive
trust -- organization_id/service_id are derived exclusively from the
authenticated integration credential (api/telemetry_ingest.py). This
module's own parser does not even look for such attributes; there is
no code path by which one could reach the trusted identity at all.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Gate 4: structural bounds, enforced BEFORE any aggregate processing --
# mirrors api/webhook_limits.py's own "Pydantic structural bounds cap a
# theoretical worst case" philosophy, on top of (not instead of) the
# ASGI-level raw byte-size guard (api/telemetry_limits.py).
MAX_RESOURCE_METRICS = 4
MAX_SCOPE_METRICS_PER_RESOURCE = 4
MAX_METRICS_PER_SCOPE = 4
MAX_DATA_POINTS_PER_METRIC = 200
MAX_ATTRIBUTES_PER_DATA_POINT = 16
MAX_ATTRIBUTE_STRING_LENGTH = 256

SUPPORTED_METRIC_NAME = "http.server.request.duration"

# Real OTLP `AggregationTemporality` enum values (identical in both the
# JSON and protobuf wire forms) -- see this module's own docstring for
# why only DELTA is accepted.
AGGREGATION_TEMPORALITY_UNSPECIFIED = 0
AGGREGATION_TEMPORALITY_DELTA = 1
AGGREGATION_TEMPORALITY_CUMULATIVE = 2

AGGREGATION_TEMPORALITY_NAMES = {
    AGGREGATION_TEMPORALITY_UNSPECIFIED: "UNSPECIFIED",
    AGGREGATION_TEMPORALITY_DELTA: "DELTA",
    AGGREGATION_TEMPORALITY_CUMULATIVE: "CUMULATIVE",
}

# Item 7 (correction round): a histogram data point's own duration unit
# must be an explicit, supported string -- never silently assumed to
# already be seconds. "s" is accepted as-is; "ms"/"us"/"ns" are
# accepted with an EXPLICIT conversion to seconds (ingestion/
# telemetry_service.py); anything else is rejected outright rather than
# guessed at.
SUPPORTED_DURATION_UNIT_SECONDS_PER_UNIT = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
}


class OtlpAttributeValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stringValue: str | None = Field(default=None, max_length=MAX_ATTRIBUTE_STRING_LENGTH)
    intValue: str | int | None = None
    boolValue: bool | None = None
    doubleValue: float | None = None


class OtlpAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(max_length=200)
    value: OtlpAttributeValue = Field(default_factory=OtlpAttributeValue)


# Item 7: a real count/sum is bounded by what a single export interval
# could plausibly report -- anything beyond this is treated as
# corrupt/adversarial data, never silently accepted and persisted into
# an INTEGER/DOUBLE PRECISION column that could overflow or skew every
# downstream aggregate.
MAX_HISTOGRAM_COUNT = 1_000_000
MAX_DURATION_SUM_SECONDS = 1_000_000.0


class OtlpHistogramDataPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attributes: list[OtlpAttribute] = Field(default_factory=list, max_length=MAX_ATTRIBUTES_PER_DATA_POINT)
    startTimeUnixNano: str | None = None
    timeUnixNano: str
    count: str | int
    # Item 7: `allow_inf_nan=False` rejects a literal NaN/Infinity/
    # -Infinity value outright (pydantic-core's own strict JSON parser
    # already refuses these as JSON tokens per RFC 8259, but a
    # protobuf-decoded double -- ingestion/otlp_protobuf.py -- goes
    # through Python's own float type first and could otherwise carry a
    # real NaN/Infinity through un-checked).
    sum: float = Field(ge=0, allow_inf_nan=False, le=MAX_DURATION_SUM_SECONDS)

    @field_validator("count")
    @classmethod
    def _count_is_positive_int(cls, value: str | int) -> str | int:
        parsed = int(value)
        if parsed < 1:
            raise ValueError("a histogram data point's count must be >= 1")
        if parsed > MAX_HISTOGRAM_COUNT:
            raise ValueError(f"a histogram data point's count must be <= {MAX_HISTOGRAM_COUNT}")
        return value


class OtlpHistogram(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dataPoints: list[OtlpHistogramDataPoint] = Field(default_factory=list, max_length=MAX_DATA_POINTS_PER_METRIC)
    # Required, no default -- a real OTLP histogram always declares
    # this; a client that omits it is sent UNSPECIFIED (0) by this
    # field's own absence, which is rejected exactly like CUMULATIVE
    # (see ingestion/telemetry_service.py).
    aggregationTemporality: int | None = None


class OtlpMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=200)
    unit: str | None = None
    histogram: OtlpHistogram | None = None
    # Deliberately accepted-but-rejected-later (never silently parsed
    # as a histogram): `sum`/`gauge` are real OTLP metric shapes this
    # endpoint does not support yet -- see ingestion/telemetry_service.py's
    # own explicit rejection for a non-histogram metric.
    sum: dict | None = None
    gauge: dict | None = None


class OtlpScopeMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metrics: list[OtlpMetric] = Field(default_factory=list, max_length=MAX_METRICS_PER_SCOPE)


class OtlpResourceMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scopeMetrics: list[OtlpScopeMetrics] = Field(default_factory=list, max_length=MAX_SCOPE_METRICS_PER_RESOURCE)


class OtlpExportMetricsRequest(BaseModel):
    """The real OTLP/HTTP JSON `ExportMetricsServiceRequest` top-level
    shape -- `extra="ignore"` throughout this module so a real SDK's
    additional, unsupported fields (resource attributes, scope version,
    schema URLs, ...) are tolerated/discarded rather than rejected
    outright, while the fields this endpoint actually trusts remain
    strictly bounded above."""

    model_config = ConfigDict(extra="ignore")

    resourceMetrics: list[OtlpResourceMetrics] = Field(default_factory=list, max_length=MAX_RESOURCE_METRICS)


class ParsedTelemetryPoint(BaseModel):
    """One validated, ready-to-store data point -- produced only by
    ingestion/telemetry_service.py's own extraction (never constructed
    directly from untrusted input elsewhere)."""

    observed_at: datetime
    http_method: str | None
    http_route: str | None
    http_status_code: int | None
    request_count: int
    duration_sum_seconds: float
    is_error: bool


ConnectionStatus = Literal[
    "not_configured",
    "configured_awaiting_data",
    "receiving_telemetry",
    "stale_data",
    "connection_error",
    "revoked",
]


class TelemetrySummary(BaseModel):
    """CORRECTION ROUND (independent review, item 4): the previous round
    exposed `p50_latency_seconds`/`p95_latency_seconds` computed as
    `percentile_cont` over each stored row's own MEAN duration
    (`duration_sum_seconds / request_count`) -- that is a percentile of
    per-export-interval AVERAGES, not a request-level percentile, and
    labeling it "p95" materially misrepresents what it measures (a
    single slow request inside a large batch is invisible; a batch of
    exactly one slow request is weighted the same as a batch of a
    thousand fast ones).

    Correct, bucket-level histogram quantiles (Gate 4 option A) would
    require storing each data point's real `bucketCounts`/
    `explicitBounds` -- a real, additive schema change out of scope for
    "the smallest correct solution" this round. Instead (Gate 4 option
    B): `mean_latency_seconds` is the one real, mathematically
    defensible number this data shape supports --
    `SUM(duration_sum_seconds) / SUM(request_count)` across the window,
    computed server-side (repositories/telemetry_repository.py) -- a
    true, correctly-weighted mean of every real observed request
    duration, never presented as a percentile."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    status: ConnectionStatus
    window_minutes: int
    request_count: int
    error_count: int
    request_rate_per_minute: float
    error_rate: float | None
    mean_latency_seconds: float | None
    last_observed_at: datetime | None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OtlpExportMetricsPartialSuccess(BaseModel):
    """The real OTLP `ExportMetricsPartialSuccess` shape (item 2) --
    used only when at least one data point was dropped but the batch
    was not rejected outright."""

    model_config = ConfigDict(extra="forbid")

    rejectedDataPoints: str
    errorMessage: str
