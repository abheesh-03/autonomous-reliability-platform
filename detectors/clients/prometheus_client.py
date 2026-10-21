"""A bounded, read-only Prometheus client for the detectors/ package --
independent of (never importing from, never coupled to)
`services/investigator-service`'s own client, per Phase 11B's "do not
restructure existing services" / "prefer a separate Python package"
guidance. Mirrors the SAME proven, real metric/label contract already
verified in production use by `investigator_service.clients.prometheus`
(see that module and `docs/architecture/phase-11b-autonomous-failure-
discovery.md` section 3 for the exact citation), generalized only to
be parameterized by a SERVICE ALLOWLIST rather than hardcoded to
checkout-service alone.

Verified real metric/label contract (confirmed against
`docker-compose.yml`'s own `OTEL_SERVICE_NAME` entries and
`services/investigator-service/src/investigator_service/clients/
prometheus.py`): ONLY checkout-service, payment-service,
inventory-service, and notification-service are OTel-instrumented with
`http_server_request_duration_seconds_count`/`_bucket` -- control-
plane, investigator-service, retrieval-service, agent-runtime-service,
tool-gateway, and web-console emit no such metrics. `ALLOWED_SERVICES`
below is exactly, and only, that verified set.

Every query template here is FIXED, code-defined PromQL with exactly
one substitution point (a service name drawn from `ALLOWED_SERVICES`)
-- never an arbitrary caller- or LLM-supplied query string, and never
an unbounded label match.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import httpx

logger = logging.getLogger("detectors.clients.prometheus")

# Verified against docker-compose.yml's own OTEL_SERVICE_NAME entries
# -- see this module's own docstring.
ALLOWED_SERVICES: frozenset[str] = frozenset(
    {"checkout-service", "payment-service", "inventory-service", "notification-service"}
)

MAX_LOOKBACK = timedelta(hours=24)
MAX_WINDOW = timedelta(hours=6)
MAX_POINTS = 500
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2


class PrometheusClientError(Exception):
    """A caller/configuration error -- an unknown service, a window
    exceeding the bound, etc. Never raised for a live query failure
    (see `PrometheusUnavailableError`)."""


class PrometheusUnavailableError(Exception):
    """The query could not be completed against a real Prometheus --
    unreachable, non-200, or a malformed response. Always distinct
    from 'the query succeeded and returned zero/empty data', which is
    a normal, valid result, never this exception."""


@dataclass(frozen=True)
class MetricSample:
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class MetricSeries:
    """One query's full result: the fixed PromQL actually sent, and
    every finite sample point actually returned (non-finite/malformed
    values are dropped explicitly, never coerced to 0 or silently
    kept -- see `_parse_range_response`)."""

    query_key: str
    promql: str
    samples: tuple[MetricSample, ...]
    malformed_value_count: int


def _require_allowed_service(service: str) -> None:
    if service not in ALLOWED_SERVICES:
        raise PrometheusClientError(
            f"service {service!r} is not in the verified ALLOWED_SERVICES allowlist {sorted(ALLOWED_SERVICES)}"
        )


def error_count_query(service: str) -> str:
    _require_allowed_service(service)
    return (
        f'sum(rate(http_server_request_duration_seconds_count'
        f'{{service_name="{service}",http_response_status_code=~"5.."}}[5m]))'
    )


def total_count_query(service: str) -> str:
    _require_allowed_service(service)
    return f'sum(rate(http_server_request_duration_seconds_count{{service_name="{service}"}}[5m]))'


def p95_latency_query(service: str) -> str:
    _require_allowed_service(service)
    return (
        "histogram_quantile(0.95, sum by (le) "
        f'(rate(http_server_request_duration_seconds_bucket{{service_name="{service}"}}[5m])))'
    )


def collector_scrape_up_query() -> str:
    return 'up{job=~"otel-collector|otel-collector-app-metrics"}'


def collector_refused_telemetry_query() -> str:
    return (
        'sum(rate(otelcol_receiver_refused_spans{job="otel-collector"}[5m])) '
        '+ sum(rate(otelcol_receiver_refused_metric_points{job="otel-collector"}[5m]))'
    )


class PrometheusClient:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """`clock`, when supplied, replaces `datetime.now()` for the
        MAX_LOOKBACK bound check only -- it exists so a fully
        synthetic, MockTransport-backed client (e.g.
        `detectors.cli.fixture_loader`'s offline `replay` mode) can be
        pinned to a fixed reference instant and stay byte-for-byte
        deterministic across runs. The real `analyze` (live) CLI path
        never supplies one, so every live query is still bounded
        against true wall-clock time."""
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=request_timeout)
        self._max_retries = max_retries
        self._transport = transport
        self._clock = clock

    async def query_range(
        self,
        query_key: str,
        promql: str,
        window_start: datetime,
        window_end: datetime,
        *,
        max_points: int = 120,
    ) -> MetricSeries:
        """Runs ONE fixed PromQL string as a bounded range query.
        `window_start`/`window_end` are checked against `MAX_LOOKBACK`/
        `MAX_WINDOW` BEFORE any request is sent -- a caller can never
        force an unbounded query merely by passing a wide window."""
        if window_end <= window_start:
            raise PrometheusClientError("window_end must be after window_start")
        now = self._clock() if self._clock is not None else datetime.now(window_end.tzinfo)
        if now - window_start > MAX_LOOKBACK:
            raise PrometheusClientError(
                f"window_start is more than MAX_LOOKBACK={MAX_LOOKBACK} in the past"
            )
        width = window_end - window_start
        if width > MAX_WINDOW:
            raise PrometheusClientError(f"window width {width} exceeds MAX_WINDOW={MAX_WINDOW}")

        max_points = min(max_points, MAX_POINTS)
        window_seconds = max(1, int(width.total_seconds()))
        step = max(15, window_seconds // max_points)

        url = f"{self._base_url}/api/v1/query_range"
        params = {
            "query": promql,
            "start": window_start.timestamp(),
            "end": window_end.timestamp(),
            "step": f"{step}s",
        }

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    resp = await client.get(url, params=params)
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    raise PrometheusUnavailableError(f"could not reach Prometheus at {url}: {exc}") from exc
        else:  # pragma: no cover - unreachable, loop always breaks or raises
            raise PrometheusUnavailableError(f"could not reach Prometheus at {url}: {last_exc}")

        if resp.status_code != 200:
            raise PrometheusUnavailableError(f"Prometheus returned HTTP {resp.status_code} for query {query_key!r}")

        try:
            body = resp.json()
        except Exception as exc:
            raise PrometheusUnavailableError(f"malformed (non-JSON) response for query {query_key!r}: {exc}") from exc

        if not isinstance(body, dict) or body.get("status") != "success":
            raise PrometheusUnavailableError(f"Prometheus query {query_key!r} did not report status=success")

        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise PrometheusUnavailableError(f"Prometheus query {query_key!r} returned an unexpected response shape")

        samples: list[MetricSample] = []
        malformed = 0
        total_returned = 0
        for result in data["result"]:
            if not isinstance(result, dict) or not isinstance(result.get("values"), list):
                malformed += 1
                continue
            for pair in result["values"]:
                total_returned += 1
                if total_returned > MAX_POINTS * 10:
                    # A defensive cardinality cap independent of `step`
                    # -- a misbehaving/compromised Prometheus returning
                    # far more series/points than requested can never
                    # make this client hold an unbounded amount of data.
                    raise PrometheusUnavailableError(
                        f"query {query_key!r} returned more than {MAX_POINTS * 10} total sample points -- refusing "
                        "to process an unbounded result"
                    )
                if not (isinstance(pair, list) and len(pair) == 2):
                    malformed += 1
                    continue
                ts_raw, value_raw = pair
                try:
                    ts = float(ts_raw)
                    value = float(value_raw)
                except (TypeError, ValueError):
                    malformed += 1
                    continue
                if not math.isfinite(value) or not math.isfinite(ts):
                    malformed += 1
                    continue
                samples.append(MetricSample(timestamp=datetime.fromtimestamp(ts, tz=window_start.tzinfo), value=value))

        samples.sort(key=lambda s: s.timestamp)
        return MetricSeries(query_key=query_key, promql=promql, samples=tuple(samples), malformed_value_count=malformed)
