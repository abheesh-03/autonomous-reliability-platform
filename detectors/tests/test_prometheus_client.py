"""Gate B client-layer tests: bounded windows, response validation,
non-finite value handling, service allowlist, retries."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from detectors.clients.prometheus_client import (
    ALLOWED_SERVICES,
    MAX_WINDOW,
    PrometheusClient,
    PrometheusClientError,
    PrometheusUnavailableError,
    error_count_query,
    total_count_query,
)

WINDOW_END = datetime.now(UTC) - timedelta(minutes=1)
WINDOW_START = WINDOW_END - timedelta(minutes=10)


def test_error_count_query_rejects_service_outside_allowlist():
    with pytest.raises(PrometheusClientError, match="ALLOWED_SERVICES"):
        error_count_query("totally-unregistered-service")


def test_allowed_services_are_exactly_the_four_otel_instrumented_services():
    assert ALLOWED_SERVICES == {"checkout-service", "payment-service", "inventory-service", "notification-service"}


async def test_window_wider_than_max_window_is_rejected():
    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(PrometheusClientError, match="MAX_WINDOW"):
        await client.query_range("k", "up", WINDOW_START, WINDOW_START + MAX_WINDOW + timedelta(seconds=1))


async def test_window_further_back_than_max_lookback_is_rejected():
    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    far_past = datetime.now(UTC) - timedelta(days=2)
    with pytest.raises(PrometheusClientError, match="MAX_LOOKBACK"):
        await client.query_range("k", "up", far_past, far_past + timedelta(minutes=5))


async def test_non_finite_values_are_dropped_not_coerced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "values": [
                                [WINDOW_START.timestamp(), "1.0"],
                                [WINDOW_START.timestamp() + 60, "NaN"],
                                [WINDOW_START.timestamp() + 120, "+Inf"],
                                [WINDOW_START.timestamp() + 180, "-Inf"],
                                [WINDOW_START.timestamp() + 240, "2.0"],
                            ]
                        }
                    ]
                },
            },
        )

    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(handler))
    series = await client.query_range("k", "up", WINDOW_START, WINDOW_END)
    assert [s.value for s in series.samples] == [1.0, 2.0]
    assert series.malformed_value_count == 3


async def test_malformed_pair_shape_is_dropped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "success", "data": {"result": [{"values": [[WINDOW_START.timestamp(), "1.0", "extra"]]}]}},
        )

    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(handler))
    series = await client.query_range("k", "up", WINDOW_START, WINDOW_END)
    assert series.samples == ()
    assert series.malformed_value_count == 1


async def test_non_json_response_raises_unavailable():
    client = PrometheusClient(
        "http://prometheus.invalid", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"{{{not json"))
    )
    with pytest.raises(PrometheusUnavailableError):
        await client.query_range("k", "up", WINDOW_START, WINDOW_END)


async def test_wrong_shape_response_raises_unavailable():
    client = PrometheusClient(
        "http://prometheus.invalid",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "success", "data": {"result": "not-a-list"}})),
    )
    with pytest.raises(PrometheusUnavailableError):
        await client.query_range("k", "up", WINDOW_START, WINDOW_END)


async def test_non_200_raises_unavailable():
    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(PrometheusUnavailableError):
        await client.query_range("k", "up", WINDOW_START, WINDOW_END)


async def test_retries_before_succeeding():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise httpx.ConnectError("transient", request=request)
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    client = PrometheusClient("http://prometheus.invalid", max_retries=2, transport=httpx.MockTransport(handler))
    series = await client.query_range("k", "up", WINDOW_START, WINDOW_END)
    assert attempts["count"] == 2
    assert series.samples == ()


async def test_exhausting_retries_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("persistent", request=request)

    client = PrometheusClient("http://prometheus.invalid", max_retries=1, transport=httpx.MockTransport(handler))
    with pytest.raises(PrometheusUnavailableError):
        await client.query_range("k", "up", WINDOW_START, WINDOW_END)


async def test_excessive_result_volume_is_rejected_not_buffered_unbounded():
    huge_values = [[WINDOW_START.timestamp() + i, "1.0"] for i in range(10_000)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": huge_values}]}})

    client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(handler))
    with pytest.raises(PrometheusUnavailableError, match="unbounded"):
        await client.query_range("k", "up", WINDOW_START, WINDOW_END)
