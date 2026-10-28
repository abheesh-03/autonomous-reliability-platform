"""Phase 16 Gate 4: turns one validated OTLP metrics export (JSON or
protobuf -- see ingestion/otlp_protobuf.py, which converts a protobuf
body into the exact same OtlpExportMetricsRequest shape before this
module ever sees it) into a list of trusted, ready-to-store
ParsedTelemetryPoint rows.

This module NEVER reads a client-supplied organization id, service id,
or `service.name` resource attribute -- there is no parameter for one,
and no field on OtlpExportMetricsRequest is ever interpreted as an
identity claim. The caller (api/telemetry_ingest.py) supplies the
trusted organization_id/service_id itself, derived from the
authenticated integration credential, entirely separately from
anything this module parses out of the request body.

CORRECTION ROUND (independent review):
  - item 1: a histogram's `aggregationTemporality` is now checked and
    enforced as DELTA-only -- see `_require_delta_temporality`.
  - item 7: a metric's `unit` is validated against a fixed set of
    supported duration units and explicitly converted to seconds (never
    silently assumed to already be seconds); a data point whose
    `startTimeUnixNano` is present but inconsistent with its
    `timeUnixNano` (start after end) is dropped as malformed.
"""

from datetime import UTC, datetime, timedelta

from control_plane.domain.telemetry import (
    AGGREGATION_TEMPORALITY_DELTA,
    AGGREGATION_TEMPORALITY_NAMES,
    OtlpExportMetricsRequest,
    OtlpHistogramDataPoint,
    OtlpMetric,
    ParsedTelemetryPoint,
    SUPPORTED_DURATION_UNIT_SECONDS_PER_UNIT,
    SUPPORTED_METRIC_NAME,
)

# Gate 4: "data validation" -- a data point whose own timestamp claims
# to be from further in the past, or further in the future, than this
# is rejected outright (never silently clamped/accepted) -- bounds how
# stale or how forward-dated a single accepted point can ever be,
# independent of this service's own "stale data" dashboard threshold
# (repositories/telemetry_repository.py), which is about ABSENCE of
# new data, not a single malformed timestamp.
MAX_POINT_AGE = timedelta(hours=24)
MAX_POINT_FUTURE_SKEW = timedelta(minutes=5)


class TelemetryIngestionRejected(Exception):
    """Raised for a structurally-valid-JSON payload that is still
    semantically rejected (unsupported metric, no histogram data,
    every point out of the accepted time window, ...). Always a 400 at
    the route layer -- never a 500, since nothing here is this
    service's own fault."""


def _require_delta_temporality(metric: OtlpMetric) -> None:
    """Item 1: reject anything that is not explicitly DELTA, before a
    single data point is processed -- summing repeated CUMULATIVE (or
    unspecified) exports as if each were a fresh delta double-counts
    (or worse) every request after the first export. No conversion is
    attempted; see this module's own docstring for why."""
    temporality = metric.histogram.aggregationTemporality if metric.histogram else None
    if temporality != AGGREGATION_TEMPORALITY_DELTA:
        received = AGGREGATION_TEMPORALITY_NAMES.get(temporality, str(temporality))
        raise TelemetryIngestionRejected(
            f"metric {SUPPORTED_METRIC_NAME!r} must declare histogram aggregationTemporality=1 (DELTA); "
            f"received {received} ({temporality!r}). CUMULATIVE or unspecified temporality is rejected "
            "outright to avoid double-counting repeated cumulative exports as new requests."
        )


def _resolve_duration_unit_factor(metric: OtlpMetric) -> float:
    """Item 7: require an explicit, supported duration unit -- never
    assume a missing/unrecognized unit already means seconds."""
    if metric.unit not in SUPPORTED_DURATION_UNIT_SECONDS_PER_UNIT:
        supported = ", ".join(sorted(SUPPORTED_DURATION_UNIT_SECONDS_PER_UNIT))
        raise TelemetryIngestionRejected(
            f"metric {SUPPORTED_METRIC_NAME!r} declared unsupported unit {metric.unit!r}; supported units: {supported}"
        )
    return SUPPORTED_DURATION_UNIT_SECONDS_PER_UNIT[metric.unit]


def _status_code_from_attributes(point: OtlpHistogramDataPoint) -> tuple[str | None, str | None, int | None]:
    method: str | None = None
    route: str | None = None
    status_code: int | None = None
    for attr in point.attributes:
        if attr.key == "http.request.method" and attr.value.stringValue is not None:
            method = attr.value.stringValue
        elif attr.key == "http.route" and attr.value.stringValue is not None:
            route = attr.value.stringValue
        elif attr.key == "http.response.status_code" and attr.value.intValue is not None:
            try:
                status_code = int(attr.value.intValue)
            except (TypeError, ValueError):
                status_code = None
    return method, route, status_code


def extract_points(
    request: OtlpExportMetricsRequest, *, now: datetime | None = None
) -> tuple[list[ParsedTelemetryPoint], int]:
    """Returns (accepted_points, rejected_count) across the whole
    export. `aggregationTemporality`/`unit` are validated per METRIC
    (item 1/7) and reject the entire export outright if wrong -- there
    is no safe partial interpretation of a mislabeled temporality or
    unit. Within an otherwise-valid metric, an individual data point
    outside the accepted time window, with an inconsistent start/end
    timestamp, is simply dropped and counted in `rejected_count` (Gate
    4/item 2: "data validation" + OTLP partial-success semantics),
    while the request as a whole still succeeds for every other valid
    point it contains. Raises TelemetryIngestionRejected only when
    NOTHING in the entire export was usable at all (no histogram data
    points for the one supported metric name, or every point was
    dropped)."""
    reference_now = now or datetime.now(UTC)
    earliest = reference_now - MAX_POINT_AGE
    latest = reference_now + MAX_POINT_FUTURE_SKEW

    points: list[ParsedTelemetryPoint] = []
    rejected_count = 0
    saw_any_supported_metric = False

    for resource_metrics in request.resourceMetrics:
        for scope_metrics in resource_metrics.scopeMetrics:
            for metric in scope_metrics.metrics:
                if metric.name != SUPPORTED_METRIC_NAME:
                    continue
                if metric.histogram is None:
                    continue
                saw_any_supported_metric = True
                _require_delta_temporality(metric)
                unit_factor = _resolve_duration_unit_factor(metric)
                for data_point in metric.histogram.dataPoints:
                    try:
                        observed_at = datetime.fromtimestamp(int(data_point.timeUnixNano) / 1_000_000_000, tz=UTC)
                    except (TypeError, ValueError, OverflowError, OSError):
                        rejected_count += 1
                        continue
                    if observed_at < earliest or observed_at > latest:
                        rejected_count += 1
                        continue
                    if data_point.startTimeUnixNano is not None:
                        try:
                            start_nanos = int(data_point.startTimeUnixNano)
                            end_nanos = int(data_point.timeUnixNano)
                        except (TypeError, ValueError):
                            rejected_count += 1
                            continue
                        if start_nanos > end_nanos:
                            # Item 7: "inconsistent histogram data" --
                            # a delta interval cannot end before it
                            # starts.
                            rejected_count += 1
                            continue
                    count = int(data_point.count)
                    if count < 1:
                        rejected_count += 1
                        continue
                    method, route, status_code = _status_code_from_attributes(data_point)
                    points.append(
                        ParsedTelemetryPoint(
                            observed_at=observed_at,
                            http_method=method,
                            http_route=route,
                            http_status_code=status_code,
                            request_count=count,
                            duration_sum_seconds=data_point.sum * unit_factor,
                            is_error=status_code is not None and status_code >= 500,
                        )
                    )

    if not saw_any_supported_metric:
        raise TelemetryIngestionRejected(
            f"no data for the one supported metric ({SUPPORTED_METRIC_NAME!r}, histogram) was present"
        )
    if not points:
        raise TelemetryIngestionRejected(
            "every data point in this export was outside the accepted observation window or malformed"
        )
    return points, rejected_count
