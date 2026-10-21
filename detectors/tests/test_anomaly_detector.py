"""Gate H (ANOMALY): exercises the real detector/algorithm code
against synthetic Prometheus responses via httpx.MockTransport --
never a mocked function returning a preset final verdict."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from detectors.anomaly.detector import (
    AnomalyThresholds,
    detect_error_rate_deviation,
    detect_latency_deviation,
    detect_telemetry_pipeline_health,
)
from detectors.clients.prometheus_client import PrometheusClient, PrometheusUnavailableError
from detectors.schemas.anomaly import DetectionResult

# Relative to "now" (not a fixed calendar date) -- the client enforces
# a real MAX_LOOKBACK bound, so a fixed past date would eventually (or,
# depending on the clock, immediately) fall outside it.
OBSERVATION_END = datetime.now(UTC) - timedelta(minutes=1)
BOUNDARY = OBSERVATION_END - timedelta(minutes=10)
BASELINE_START = BOUNDARY - timedelta(hours=1)


def _series(values: list[float], start: datetime, step_seconds: int = 60) -> list[list]:
    return [[(start + timedelta(seconds=i * step_seconds)).timestamp(), v] for i, v in enumerate(values)]


def _query_kind(promql: str) -> str:
    if "5.." in promql:
        return "errors"
    if "histogram_quantile" in promql:
        return "latency"
    if "refused" in promql:
        return "refused"
    if "up{job" in promql:
        return "up"
    if "http_server_request_duration_seconds_count" in promql:
        return "total"
    raise AssertionError(f"unrecognized promql in test: {promql}")


def _make_transport(datasets: dict[str, list[list]], *, status_code: int = 200, malformed: bool = False, unreachable: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        params = dict(httpx.QueryParams(request.url.query.decode()))
        kind = _query_kind(params["query"])
        if malformed:
            return httpx.Response(200, content=b"not json {{{")
        values = datasets.get(kind, [])
        return httpx.Response(status_code, json={"status": "success", "data": {"result": [{"values": values}] if values else []}})

    return httpx.MockTransport(handler)


def _client(datasets: dict[str, list[list]], **kwargs) -> PrometheusClient:
    return PrometheusClient("http://prometheus.invalid", transport=_make_transport(datasets, **kwargs))


# ---------------------------------------------------------------------
# error-rate deviation
# ---------------------------------------------------------------------


async def test_normal_traffic_is_no_anomaly():
    baseline_errors = [0.5] * 30
    baseline_total = [50.0] * 30
    obs_errors = [0.6] * 5
    obs_total = [50.0] * 5
    client = _client(
        {
            "errors": _series(baseline_errors, BASELINE_START) + _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.NO_ANOMALY


async def test_sustained_error_increase_is_anomaly_detected():
    baseline_errors = [0.5] * 30
    baseline_total = [50.0] * 30
    obs_errors = [25.0] * 5  # ~50% error rate, sustained
    obs_total = [50.0] * 5
    client = _client(
        {
            "errors": _series(baseline_errors, BASELINE_START) + _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.ANOMALY_DETECTED
    assert result.persistence_fraction == 1.0


async def test_transient_single_spike_is_no_anomaly_not_sustained():
    baseline_errors = [0.5] * 30
    baseline_total = [50.0] * 30
    # Only the FIRST of 5 observation samples spikes -- 1/5 = 20%
    # persistence, below the 60% default requirement.
    obs_errors = [25.0, 0.5, 0.5, 0.5, 0.5]
    obs_total = [50.0] * 5
    client = _client(
        {
            "errors": _series(baseline_errors, BASELINE_START) + _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.NO_ANOMALY
    assert result.persistence_fraction == pytest.approx(0.2)


async def test_low_traffic_is_insufficient_data_not_anomaly():
    """A single error out of near-zero traffic must never register as
    a high-confidence anomaly -- the volume guard must catch it."""
    baseline_errors = [0.01] * 30
    baseline_total = [0.02] * 30
    obs_errors = [0.01] * 5
    obs_total = [0.02] * 5  # far below min_volume_per_second
    client = _client(
        {
            "errors": _series(baseline_errors, BASELINE_START) + _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA
    assert "volume" in result.decision_rationale


async def test_empty_baseline_is_insufficient_data():
    obs_errors = [25.0] * 5
    obs_total = [50.0] * 5
    client = _client({"errors": _series(obs_errors, BOUNDARY), "total": _series(obs_total, BOUNDARY)})
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA
    assert result.data_completeness.baseline_sample_count == 0


async def test_missing_metric_entirely_is_insufficient_data():
    client = _client({})  # no data for any query at all
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA


async def test_stale_data_outside_observation_window_is_insufficient_data():
    """All returned samples are timestamped well before the observation
    window even started -- must not be silently treated as covering it."""
    stale_errors = [25.0] * 10
    stale_total = [50.0] * 10
    client = _client(
        {
            "errors": _series(stale_errors, BASELINE_START),  # all before BOUNDARY
            "total": _series(stale_total, BASELINE_START),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA
    assert result.data_completeness.observation_sample_count == 0


async def test_malformed_prometheus_response_is_telemetry_unavailable():
    client = _client({}, malformed=True)
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.TELEMETRY_UNAVAILABLE


async def test_upstream_unreachable_is_telemetry_unavailable():
    client = _client({}, unreachable=True)
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.TELEMETRY_UNAVAILABLE


async def test_non_200_status_is_telemetry_unavailable():
    client = _client({}, status_code=500)
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.TELEMETRY_UNAVAILABLE


async def test_first_ever_sustained_error_spike_is_detected_despite_empty_baseline_error_series():
    """Correction-round Issue 1 reproduction: a healthy baseline with
    CONFIRMED real traffic (20 samples @ 50 req/s) and zero 5xx EVER
    recorded -- Prometheus's own real semantics mean the 5xx-filtered
    query returns an EMPTY series for that window, not literal zeros.
    A sustained, real error spike in the observation window must still
    be detected as ANOMALY_DETECTED, never INSUFFICIENT_DATA."""
    baseline_total = [50.0] * 20
    obs_errors = [25.0] * 5
    obs_total = [50.0] * 5
    client = _client(
        {
            # NOTHING for the baseline window in "errors" -- confirmed
            # zero (via real, positive total traffic), never missing.
            "errors": _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.ANOMALY_DETECTED
    assert result.data_completeness.baseline_sample_count == 20
    assert result.data_completeness.derived_zero_error_sample_count == 20
    assert result.baseline.median == 0.0


async def test_confirmed_zero_error_baseline_requires_real_total_traffic_not_fabricated():
    """Negative control: if TOTAL traffic is ALSO absent for the
    baseline window (genuinely unavailable, not merely zero-error),
    the absence of an error series must NEVER be treated as a
    confirmed healthy baseline -- INSUFFICIENT_DATA, never a
    fabricated 0% error rate from nothing."""
    obs_errors = [25.0] * 5
    obs_total = [50.0] * 5
    client = _client({"errors": _series(obs_errors, BOUNDARY), "total": _series(obs_total, BOUNDARY)})
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA
    assert result.data_completeness.baseline_sample_count == 0
    assert result.data_completeness.derived_zero_error_sample_count in (0, None)


async def test_transient_spike_against_a_derived_zero_baseline_is_still_no_anomaly():
    """The persistence guard must still protect against one isolated
    spike even when the baseline itself was derived (confirmed-zero)
    rather than directly observed."""
    baseline_total = [50.0] * 20
    # Only the FIRST of 5 observation samples spikes.
    obs_errors = [25.0, 0.5, 0.5, 0.5, 0.5]
    obs_total = [50.0] * 5
    client = _client(
        {
            "errors": _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.NO_ANOMALY
    assert result.persistence_fraction == pytest.approx(0.2)


async def test_low_traffic_with_derived_zero_baseline_is_still_insufficient_data_not_anomaly():
    """A confirmed-zero-error baseline must not bypass the volume
    guard -- near-zero observation traffic stays INSUFFICIENT_DATA."""
    baseline_total = [50.0] * 20
    obs_errors = [0.01] * 5
    obs_total = [0.02] * 5
    client = _client(
        {
            "errors": _series(obs_errors, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_error_rate_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA
    assert "volume" in result.decision_rationale


async def test_anomaly_result_requires_no_scenario_match_at_all():
    """Anomalous data without any catalog scenario match is still a
    complete, valid, first-class finding -- the schema carries no
    scenario_id field whatsoever."""
    assert "scenario_id" not in type(
        await detect_error_rate_deviation(
            _client({"errors": _series([25.0] * 5, BOUNDARY), "total": _series([50.0] * 5, BOUNDARY),
                     }), "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END,
        )
    ).model_fields


# ---------------------------------------------------------------------
# latency deviation
# ---------------------------------------------------------------------


async def test_sustained_latency_increase_is_anomaly_detected():
    baseline_latency = [0.1] * 30
    baseline_total = [50.0] * 30
    obs_latency = [2.5] * 5
    obs_total = [50.0] * 5
    client = _client(
        {
            "latency": _series(baseline_latency, BASELINE_START) + _series(obs_latency, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_latency_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.ANOMALY_DETECTED


async def test_latency_low_traffic_is_insufficient_data():
    baseline_latency = [0.1] * 30
    baseline_total = [0.02] * 30
    obs_latency = [2.5] * 5
    obs_total = [0.02] * 5
    client = _client(
        {
            "latency": _series(baseline_latency, BASELINE_START) + _series(obs_latency, BOUNDARY),
            "total": _series(baseline_total, BASELINE_START) + _series(obs_total, BOUNDARY),
        }
    )
    result = await detect_latency_deviation(client, "checkout-service", BASELINE_START, BOUNDARY, OBSERVATION_END)
    assert result.result == DetectionResult.INSUFFICIENT_DATA


# ---------------------------------------------------------------------
# telemetry pipeline health
# ---------------------------------------------------------------------


async def test_telemetry_healthy_is_no_anomaly():
    client = _client({"up": _series([1.0] * 10, BASELINE_START) + _series([1.0] * 5, BOUNDARY), "refused": _series([0.0] * 5, BOUNDARY)})
    result = await detect_telemetry_pipeline_health(client, BOUNDARY, OBSERVATION_END, BASELINE_START)
    assert result.result == DetectionResult.NO_ANOMALY


async def test_telemetry_scrape_down_is_anomaly_detected():
    client = _client({"up": _series([1.0] * 10, BASELINE_START) + _series([0.0] * 5, BOUNDARY), "refused": _series([0.0] * 5, BOUNDARY)})
    result = await detect_telemetry_pipeline_health(client, BOUNDARY, OBSERVATION_END, BASELINE_START)
    assert result.result == DetectionResult.ANOMALY_DETECTED


async def test_telemetry_refusing_is_anomaly_detected():
    client = _client({"up": _series([1.0] * 5, BOUNDARY), "refused": _series([5.0] * 5, BOUNDARY)})
    result = await detect_telemetry_pipeline_health(client, BOUNDARY, OBSERVATION_END, BASELINE_START)
    assert result.result == DetectionResult.ANOMALY_DETECTED


async def test_telemetry_no_data_at_all_is_insufficient_data():
    client = _client({})
    result = await detect_telemetry_pipeline_health(client, BOUNDARY, OBSERVATION_END, BASELINE_START)
    assert result.result == DetectionResult.INSUFFICIENT_DATA


async def test_telemetry_unreachable_is_telemetry_unavailable():
    client = _client({}, unreachable=True)
    result = await detect_telemetry_pipeline_health(client, BOUNDARY, OBSERVATION_END, BASELINE_START)
    assert result.result == DetectionResult.TELEMETRY_UNAVAILABLE
