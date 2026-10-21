"""Gate B: the three real, statistical anomaly detectors --
error-rate deviation, latency deviation, and telemetry-pipeline
health/degradation -- each backed by the verified real Prometheus
metric contract in `detectors.clients.prometheus_client`.

Methodology (per metric shape, chosen deliberately, never uniformly
forced):

  - error-rate / latency: a robust median + median-absolute-deviation
    (MAD) baseline, a modified z-score (Iglewicz & Hoaglin's standard
    formula) on recent samples, and a PERSISTENCE requirement (a
    configurable fraction of recent samples must exceed the threshold,
    not merely the single highest one) -- this is what prevents one
    isolated spike from registering as a sustained incident. A minimum
    request-VOLUME guard (shared `total_count_query` traffic) prevents
    a near-zero-traffic window from producing a misleadingly extreme
    ratio, and a minimum sample-count guard on both baseline and
    observation prevents judging anything from too little history.
  - telemetry pipeline health: `up` is an inherently binary signal
    (scraped or not) and the refused-telemetry rate is normally
    exactly zero -- modeling either with a median/MAD baseline would
    be statistically meaningless, so this detector uses a direct,
    explainable threshold+persistence check instead. Choosing a
    different method for a differently-shaped signal is deliberate,
    not an inconsistency.

No LLM and no ML model decides any raw numeric threshold anywhere in
this module -- every threshold is a fixed, reviewed, code-defined
constant in `AnomalyThresholds`.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime

from detectors.anomaly.statistics import median_absolute_deviation, median_or_none, modified_zscore
from detectors.clients.prometheus_client import (
    MetricSeries,
    PrometheusClient,
    PrometheusUnavailableError,
    collector_refused_telemetry_query,
    collector_scrape_up_query,
    error_count_query,
    p95_latency_query,
    total_count_query,
)
from detectors.schemas.anomaly import (
    AnomalyDetectionResult,
    DataCompleteness,
    DetectionResult,
    EvidenceProvenance,
    WindowSummary,
)

ALGORITHM_ID = "robust_median_mad_zscore"
ALGORITHM_VERSION = "v1"
THRESHOLD_ALGORITHM_ID = "binary_threshold_persistence"
THRESHOLD_ALGORITHM_VERSION = "v1"


@dataclass(frozen=True)
class AnomalyThresholds:
    zscore_threshold: float = 3.5
    min_baseline_samples: int = 12
    min_observation_samples: int = 3
    min_persistence_fraction: float = 0.6
    min_volume_per_second: float = 1.0
    ratio_mad_floor: float = 0.01
    latency_mad_floor_seconds: float = 0.005
    telemetry_persistence_fraction: float = 0.5


DEFAULT_THRESHOLDS = AnomalyThresholds()


def _window_summary(values: list[float], window_start: datetime, window_end: datetime) -> WindowSummary:
    med = median_or_none(values)
    return WindowSummary(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        sample_count=len(values),
        median=med,
        mad=median_absolute_deviation(values, med) if med is not None else None,
        max_value=max(values) if values else None,
        min_value=min(values) if values else None,
    )


def _evidence(promql: str, collected_at: datetime) -> EvidenceProvenance:
    return EvidenceProvenance(source_system="prometheus", query=promql, collected_at=collected_at.isoformat())


def _unavailable_result(
    detector_id: str, metric_key: str, service: str, promql: str,
    baseline_start: datetime, boundary: datetime, observation_end: datetime, reason: str,
) -> AnomalyDetectionResult:
    return AnomalyDetectionResult(
        detector_id=detector_id,
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        metric_key=metric_key,
        service=service,
        result=DetectionResult.TELEMETRY_UNAVAILABLE,
        observation=_window_summary([], boundary, observation_end),
        baseline=_window_summary([], baseline_start, boundary),
        threshold_used=DEFAULT_THRESHOLDS.zscore_threshold,
        decision_rationale=f"Prometheus query failed: {reason}",
        data_completeness=DataCompleteness(
            observation_sample_count=0, baseline_sample_count=0, malformed_value_count=0,
            notes="query never completed -- see decision_rationale",
        ),
        evidence=_evidence(promql, observation_end),
    )


def _insufficient_data_result(
    detector_id: str, metric_key: str, service: str, promql: str,
    baseline_values: list[float], observation_values: list[float],
    baseline_start: datetime, boundary: datetime, observation_end: datetime,
    malformed: int, volume_sample_count: int | None, reason: str,
    derived_zero_error_count: int | None = None,
) -> AnomalyDetectionResult:
    return AnomalyDetectionResult(
        detector_id=detector_id,
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        metric_key=metric_key,
        service=service,
        result=DetectionResult.INSUFFICIENT_DATA,
        observation=_window_summary(observation_values, boundary, observation_end),
        baseline=_window_summary(baseline_values, baseline_start, boundary),
        threshold_used=DEFAULT_THRESHOLDS.zscore_threshold,
        decision_rationale=reason,
        data_completeness=DataCompleteness(
            observation_sample_count=len(observation_values),
            baseline_sample_count=len(baseline_values),
            malformed_value_count=malformed,
            volume_sample_count=volume_sample_count,
            derived_zero_error_sample_count=derived_zero_error_count,
            notes="insufficient basis for a statistical judgment -- see decision_rationale",
        ),
        evidence=_evidence(promql, observation_end),
    )


def _mad_decision(
    baseline_values: list[float], observation_values: list[float], *, mad_floor: float, thresholds: AnomalyThresholds
) -> tuple[DetectionResult, float, str]:
    med = statistics.median(baseline_values)
    mad = median_absolute_deviation(baseline_values, med)
    z_scores = [modified_zscore(v, med, mad, mad_floor=mad_floor) for v in observation_values]
    exceeding = sum(1 for z in z_scores if z >= thresholds.zscore_threshold)
    persistence = exceeding / len(z_scores)
    result = DetectionResult.ANOMALY_DETECTED if persistence >= thresholds.min_persistence_fraction else DetectionResult.NO_ANOMALY
    rationale = (
        f"{exceeding}/{len(z_scores)} observation samples ({persistence:.0%}) had a modified z-score >= "
        f"{thresholds.zscore_threshold:g} against baseline median={med:.6g}, MAD={mad:.6g} (floor={mad_floor:g}); "
        f"anomaly requires persistence >= {thresholds.min_persistence_fraction:.0%} of observation samples"
    )
    return result, persistence, rationale


async def detect_error_rate_deviation(
    client: PrometheusClient,
    service: str,
    baseline_start: datetime,
    boundary: datetime,
    observation_end: datetime,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> AnomalyDetectionResult:
    detector_id = "error_rate_deviation"
    metric_key = "http_5xx_fraction"
    error_promql = error_count_query(service)
    total_promql = total_count_query(service)

    try:
        error_series = await client.query_range(f"{detector_id}:errors", error_promql, baseline_start, observation_end)
        total_series = await client.query_range(f"{detector_id}:total", total_promql, baseline_start, observation_end)
    except PrometheusUnavailableError as exc:
        return _unavailable_result(detector_id, metric_key, service, error_promql, baseline_start, boundary, observation_end, str(exc))

    total_by_ts = {s.timestamp: s.value for s in total_series.samples}
    error_by_ts = {s.timestamp: s.value for s in error_series.samples}
    ratio_by_ts: dict[datetime, float] = {}
    volume_by_ts: dict[datetime, float] = {}
    derived_zero_error_timestamps: set[datetime] = set()

    # Correction-round Issue 1: iterate over VERIFIED TOTAL TRAFFIC,
    # never over the error series alone. Prometheus's own semantics:
    # a label combination (here, status=~"5..") that never fired in a
    # window produces NO data point for that timestamp -- not a
    # literal 0 -- so a healthy baseline with truly zero errors
    # legitimately returns an EMPTY error series. The previous
    # implementation only ever walked `error_series.samples`, so a
    # genuinely healthy (zero-error) baseline produced ZERO aligned
    # ratio samples and was misreported as INSUFFICIENT_DATA instead
    # of the true, confirmable "0% error rate" baseline. The fix:
    # walk the TOTAL series (confirmed real traffic) and derive a
    # zero-error observation ONLY at a timestamp where (a) total
    # traffic is itself present and positive -- i.e. actually
    # confirmed, never invented -- and (b) the error series has no
    # matching sample. Missing TOTAL traffic is never treated as zero
    # traffic (that timestamp contributes nothing at all, in either
    # direction), and a wholly unavailable/empty total series still
    # correctly falls through to INSUFFICIENT_DATA below (this loop
    # produces nothing to iterate over).
    for ts, total_v in total_by_ts.items():
        volume_by_ts[ts] = total_v
        if total_v <= 0:
            continue
        if ts in error_by_ts:
            ratio_by_ts[ts] = error_by_ts[ts] / total_v
        else:
            ratio_by_ts[ts] = 0.0
            derived_zero_error_timestamps.add(ts)

    baseline_ratio = [v for ts, v in ratio_by_ts.items() if ts < boundary]
    observation_ratio = [v for ts, v in ratio_by_ts.items() if ts >= boundary]
    observation_volume = [v for ts, v in volume_by_ts.items() if ts >= boundary]
    malformed = error_series.malformed_value_count + total_series.malformed_value_count
    derived_zero_error_count = len(derived_zero_error_timestamps)

    if len(baseline_ratio) < thresholds.min_baseline_samples or len(observation_ratio) < thresholds.min_observation_samples:
        return _insufficient_data_result(
            detector_id, metric_key, service, error_promql, baseline_ratio, observation_ratio,
            baseline_start, boundary, observation_end, malformed, len(observation_volume),
            f"too few aligned samples: baseline={len(baseline_ratio)} (need >= {thresholds.min_baseline_samples}), "
            f"observation={len(observation_ratio)} (need >= {thresholds.min_observation_samples}); "
            f"{derived_zero_error_count} sample(s) were confirmed-zero-error derivations from real, positive total "
            "traffic with no matching 5xx sample -- still not enough to reach the minimum",
            derived_zero_error_count,
        )

    mean_volume = statistics.mean(observation_volume) if observation_volume else 0.0
    if mean_volume < thresholds.min_volume_per_second:
        return _insufficient_data_result(
            detector_id, metric_key, service, error_promql, baseline_ratio, observation_ratio,
            baseline_start, boundary, observation_end, malformed, len(observation_volume),
            f"mean observation request volume {mean_volume:.4g}/s is below the minimum "
            f"{thresholds.min_volume_per_second:g}/s guard -- too little traffic to trust an error-rate ratio "
            "(never treat low-volume noise as a high-confidence anomaly, and never zero/near-zero traffic as an outage)",
            derived_zero_error_count,
        )

    result, persistence, rationale = _mad_decision(
        baseline_ratio, observation_ratio, mad_floor=thresholds.ratio_mad_floor, thresholds=thresholds
    )
    return AnomalyDetectionResult(
        detector_id=detector_id, algorithm_id=ALGORITHM_ID, algorithm_version=ALGORITHM_VERSION,
        metric_key=metric_key, service=service, result=result,
        observation=_window_summary(observation_ratio, boundary, observation_end),
        baseline=_window_summary(baseline_ratio, baseline_start, boundary),
        threshold_used=thresholds.zscore_threshold, persistence_fraction=persistence,
        decision_rationale=rationale,
        data_completeness=DataCompleteness(
            observation_sample_count=len(observation_ratio), baseline_sample_count=len(baseline_ratio),
            malformed_value_count=malformed, volume_sample_count=len(observation_volume),
            derived_zero_error_sample_count=derived_zero_error_count,
            notes=(
                f"mean observation volume {mean_volume:.4g}/s; ratio computed from real, aligned samples where "
                f"both series reported a value, plus {derived_zero_error_count} confirmed-zero-error sample(s) "
                "derived from real positive total traffic with no matching 5xx sample (never the reverse: "
                "missing total traffic is never treated as zero traffic or zero error)"
            ),
        ),
        evidence=_evidence(error_promql, observation_end),
    )


async def detect_latency_deviation(
    client: PrometheusClient,
    service: str,
    baseline_start: datetime,
    boundary: datetime,
    observation_end: datetime,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> AnomalyDetectionResult:
    detector_id = "latency_deviation"
    metric_key = "http_p95_latency_seconds"
    latency_promql = p95_latency_query(service)
    total_promql = total_count_query(service)

    try:
        latency_series = await client.query_range(f"{detector_id}:p95", latency_promql, baseline_start, observation_end)
        total_series = await client.query_range(f"{detector_id}:total", total_promql, baseline_start, observation_end)
    except PrometheusUnavailableError as exc:
        return _unavailable_result(detector_id, metric_key, service, latency_promql, baseline_start, boundary, observation_end, str(exc))

    total_by_ts = {s.timestamp: s.value for s in total_series.samples}
    baseline_values = [s.value for s in latency_series.samples if s.timestamp < boundary]
    observation_values = [s.value for s in latency_series.samples if s.timestamp >= boundary]
    observation_volume = [v for ts, v in total_by_ts.items() if ts >= boundary]
    malformed = latency_series.malformed_value_count + total_series.malformed_value_count

    if len(baseline_values) < thresholds.min_baseline_samples or len(observation_values) < thresholds.min_observation_samples:
        return _insufficient_data_result(
            detector_id, metric_key, service, latency_promql, baseline_values, observation_values,
            baseline_start, boundary, observation_end, malformed, len(observation_volume),
            f"too few p95 samples: baseline={len(baseline_values)} (need >= {thresholds.min_baseline_samples}), "
            f"observation={len(observation_values)} (need >= {thresholds.min_observation_samples}) -- "
            "histogram_quantile over too little traffic is non-finite and already filtered at the client layer",
        )

    mean_volume = statistics.mean(observation_volume) if observation_volume else 0.0
    if mean_volume < thresholds.min_volume_per_second:
        return _insufficient_data_result(
            detector_id, metric_key, service, latency_promql, baseline_values, observation_values,
            baseline_start, boundary, observation_end, malformed, len(observation_volume),
            f"mean observation request volume {mean_volume:.4g}/s is below the minimum "
            f"{thresholds.min_volume_per_second:g}/s guard -- too little traffic to trust a p95 estimate",
        )

    result, persistence, rationale = _mad_decision(
        baseline_values, observation_values, mad_floor=thresholds.latency_mad_floor_seconds, thresholds=thresholds
    )
    return AnomalyDetectionResult(
        detector_id=detector_id, algorithm_id=ALGORITHM_ID, algorithm_version=ALGORITHM_VERSION,
        metric_key=metric_key, service=service, result=result,
        observation=_window_summary(observation_values, boundary, observation_end),
        baseline=_window_summary(baseline_values, baseline_start, boundary),
        threshold_used=thresholds.zscore_threshold, persistence_fraction=persistence,
        decision_rationale=rationale,
        data_completeness=DataCompleteness(
            observation_sample_count=len(observation_values), baseline_sample_count=len(baseline_values),
            malformed_value_count=malformed, volume_sample_count=len(observation_volume),
            notes=f"mean observation volume {mean_volume:.4g}/s",
        ),
        evidence=_evidence(latency_promql, observation_end),
    )


async def detect_telemetry_pipeline_health(
    client: PrometheusClient,
    boundary: datetime,
    observation_end: datetime,
    baseline_start: datetime,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> AnomalyDetectionResult:
    """Binary/threshold methodology deliberately different from the
    two MAD-based detectors above -- see module docstring."""
    detector_id = "telemetry_pipeline_health"
    metric_key = "otel_collector_scrape_and_refusal"
    up_promql = collector_scrape_up_query()
    refused_promql = collector_refused_telemetry_query()

    try:
        up_series = await client.query_range(f"{detector_id}:up", up_promql, baseline_start, observation_end)
        refused_series = await client.query_range(f"{detector_id}:refused", refused_promql, baseline_start, observation_end)
    except PrometheusUnavailableError as exc:
        return _unavailable_result(detector_id, metric_key, "otel-collector", up_promql, baseline_start, boundary, observation_end, str(exc))

    observation_up = [s.value for s in up_series.samples if s.timestamp >= boundary]
    observation_refused = [s.value for s in refused_series.samples if s.timestamp >= boundary]
    baseline_up = [s.value for s in up_series.samples if s.timestamp < boundary]
    malformed = up_series.malformed_value_count + refused_series.malformed_value_count

    if not observation_up and not observation_refused:
        return _insufficient_data_result(
            detector_id, metric_key, "otel-collector", up_promql, baseline_up, observation_up,
            baseline_start, boundary, observation_end, malformed, None,
            "no scrape or refusal samples were returned for the observation window at all",
        )

    down_count = sum(1 for v in observation_up if v < 1)
    down_fraction = down_count / len(observation_up) if observation_up else 0.0
    refused_count = sum(1 for v in observation_refused if v > 0)
    refused_fraction = refused_count / len(observation_refused) if observation_refused else 0.0

    scrape_down = down_fraction >= thresholds.telemetry_persistence_fraction
    refusing = refused_fraction >= thresholds.telemetry_persistence_fraction
    result = DetectionResult.ANOMALY_DETECTED if (scrape_down or refusing) else DetectionResult.NO_ANOMALY
    rationale = (
        f"scrape-down: {down_count}/{len(observation_up)} samples ({down_fraction:.0%}) reported up<1; "
        f"refusing: {refused_count}/{len(observation_refused)} samples ({refused_fraction:.0%}) reported a nonzero "
        f"refused-telemetry rate; anomaly requires either fraction >= {thresholds.telemetry_persistence_fraction:.0%}"
    )
    return AnomalyDetectionResult(
        detector_id=detector_id, algorithm_id=THRESHOLD_ALGORITHM_ID, algorithm_version=THRESHOLD_ALGORITHM_VERSION,
        metric_key=metric_key, service="otel-collector", result=result,
        observation=_window_summary(observation_up, boundary, observation_end),
        baseline=_window_summary(baseline_up, baseline_start, boundary),
        threshold_used=thresholds.telemetry_persistence_fraction,
        persistence_fraction=max(down_fraction, refused_fraction),
        decision_rationale=rationale,
        data_completeness=DataCompleteness(
            observation_sample_count=len(observation_up), baseline_sample_count=len(baseline_up),
            malformed_value_count=malformed, volume_sample_count=len(observation_refused),
            notes="otel-collector scrape availability + refused-telemetry rate, not a request-volume-bound metric",
        ),
        evidence=_evidence(f"{up_promql} ; {refused_promql}", observation_end),
    )


async def run_core_anomaly_detectors(
    client: PrometheusClient,
    service: str,
    baseline_start: datetime,
    boundary: datetime,
    observation_end: datetime,
    thresholds: AnomalyThresholds = DEFAULT_THRESHOLDS,
) -> list[AnomalyDetectionResult]:
    """Runs all three core detectors for one service -- telemetry
    pipeline health is service-independent (it describes the shared
    otel-collector) and is run once per call, same as the other two,
    for pipeline simplicity (Gate F composes this per allowlisted
    service)."""
    return [
        await detect_error_rate_deviation(client, service, baseline_start, boundary, observation_end, thresholds),
        await detect_latency_deviation(client, service, baseline_start, boundary, observation_end, thresholds),
        await detect_telemetry_pipeline_health(client, boundary, observation_end, baseline_start, thresholds),
    ]
