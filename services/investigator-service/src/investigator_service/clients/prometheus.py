"""Read-only Prometheus client.

Exposes exactly four ALLOWLISTED, code-defined PromQL templates —
never an arbitrary caller- or LLM-supplied query string — chosen
because they are each the real underlying metric behind one of this
repository's four existing, already-reviewed alert rules
(observability/prometheus/rules/alerts.yml): CheckoutServerErrors,
CheckoutHighLatency, TelemetryPipelineUnavailable, and
CollectorRefusingTelemetry. An incident's title/description never
reliably reveals which rule actually fired (Alertmanager's fingerprint
identifies an alert INSTANCE, not its rule name), so rather than
guessing, this client queries all four real metrics directly, scoped
to the incident's own real time window — broad enough to cover every
alert this platform can currently raise, without inventing anything
alert-specific per incident.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger("investigator_service.prometheus")


@dataclass(frozen=True)
class MetricQuery:
    key: str
    description: str
    promql: str


# The allowlist. Order is deterministic and fixed — never reordered by
# request content.
QUERIES: tuple[MetricQuery, ...] = (
    MetricQuery(
        key="checkout_5xx_rate",
        description="checkout-service HTTP 5xx rate (underlies CheckoutServerErrors)",
        promql='sum(rate(http_server_request_duration_seconds_count{service_name="checkout-service",http_response_status_code=~"5.."}[5m]))',
    ),
    MetricQuery(
        key="checkout_p95_latency_seconds",
        description="checkout-service POST /checkouts p95 latency (underlies CheckoutHighLatency)",
        promql='histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="checkout-service",http_route="/checkouts"}[5m])))',
    ),
    MetricQuery(
        key="collector_scrape_up",
        description="otel-collector / otel-collector-app-metrics scrape availability (underlies TelemetryPipelineUnavailable)",
        promql='up{job=~"otel-collector|otel-collector-app-metrics"}',
    ),
    MetricQuery(
        key="collector_refused_telemetry_rate",
        description="otel-collector refused spans/metric points rate (underlies CollectorRefusingTelemetry)",
        promql='sum(rate(otelcol_receiver_refused_spans{job="otel-collector"}[5m])) + sum(rate(otelcol_receiver_refused_metric_points{job="otel-collector"}[5m]))',
    ),
)


@dataclass(frozen=True)
class MetricSeriesSummary:
    key: str
    description: str
    promql: str
    sample_count: int
    nonzero_or_below_one_count: int
    max_value: float | None
    max_value_at: datetime | None
    last_value: float | None


class PrometheusUnavailableError(Exception):
    pass


class PrometheusClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float,
        request_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        self._transport = transport

    async def query_window(
        self, window_start: datetime, window_end: datetime, *, max_points: int = 60
    ) -> list[MetricSeriesSummary]:
        """Runs all four allowlisted queries as bounded range queries
        over [window_start, window_end], each capped to roughly
        `max_points` samples by choosing `step` from the window width
        — never an unbounded number of returned points regardless of
        how wide the incident's own window is."""
        window_seconds = max(1, int((window_end - window_start).total_seconds()))
        step = max(15, window_seconds // max_points)

        summaries: list[MetricSeriesSummary] = []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for q in QUERIES:
                summaries.append(await self._run_one(client, q, window_start, window_end, step))
        return summaries

    async def _run_one(
        self,
        client: httpx.AsyncClient,
        q: MetricQuery,
        window_start: datetime,
        window_end: datetime,
        step: int,
    ) -> MetricSeriesSummary:
        url = f"{self._base_url}/api/v1/query_range"
        params = {
            "query": q.promql,
            "start": window_start.timestamp(),
            "end": window_end.timestamp(),
            "step": f"{step}s",
        }
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise PrometheusUnavailableError(f"could not reach Prometheus at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise PrometheusUnavailableError(f"Prometheus returned HTTP {resp.status_code} for query {q.key!r}")

        # Phase 5 correction round #3: a 200 response is not
        # necessarily well-formed JSON in the expected shape. Any
        # surprise here (not valid JSON, "data"/"result" missing or
        # not the expected type, an unparseable timestamp) is a
        # collection FAILURE for this best-effort source, never an
        # uncaught exception that would crash the whole investigation.
        try:
            body = resp.json()
            if body.get("status") != "success":
                raise PrometheusUnavailableError(f"Prometheus query {q.key!r} did not report status=success")

            # "up" is the one query where LOW (not high) is the signal
            # of interest (a scrape target being down) — everything
            # else is a rate/latency where high is the signal.
            # is_up_style keys off the query itself, a fixed,
            # code-defined property, never inferred from the response
            # data.
            is_up_style = q.key == "collector_scrape_up"

            samples: list[tuple[datetime, float]] = []
            for result in body.get("data", {}).get("result", []):
                for ts, raw_value in result.get("values", []):
                    try:
                        value = float(raw_value)
                        sample_ts = datetime.fromtimestamp(float(ts), tz=window_start.tzinfo)
                    except (TypeError, ValueError, OSError, OverflowError):
                        continue
                    samples.append((sample_ts, value))
        except PrometheusUnavailableError:
            raise
        except Exception as exc:
            raise PrometheusUnavailableError(f"malformed response from Prometheus for query {q.key!r}: {exc}") from exc

        if not samples:
            return MetricSeriesSummary(
                key=q.key, description=q.description, promql=q.promql,
                sample_count=0, nonzero_or_below_one_count=0,
                max_value=None, max_value_at=None, last_value=None,
            )

        samples.sort(key=lambda pair: pair[0])
        if is_up_style:
            interesting = [(ts, v) for ts, v in samples if v < 1]
            extreme_ts, extreme_v = min(samples, key=lambda pair: pair[1])
        else:
            interesting = [(ts, v) for ts, v in samples if v > 0]
            extreme_ts, extreme_v = max(samples, key=lambda pair: pair[1])

        return MetricSeriesSummary(
            key=q.key,
            description=q.description,
            promql=q.promql,
            sample_count=len(samples),
            nonzero_or_below_one_count=len(interesting),
            max_value=extreme_v,
            max_value_at=extreme_ts,
            last_value=samples[-1][1],
        )
