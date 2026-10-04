"""Bounded telemetry query tests for Prometheus/Loki/Tempo clients
(Phase 5 §9: "Bounded telemetry queries"). Every client is exercised
against httpx.MockTransport fakes returning MORE data than the
configured bound, proving the client itself enforces the bound rather
than trusting the (fake, here; real, in production) source to behave.
"""

from datetime import UTC, datetime, timedelta

import httpx

from investigator_service.clients.loki import LokiClient, LokiUnavailableError
from investigator_service.clients.prometheus import PrometheusClient, PrometheusUnavailableError
from investigator_service.clients.tempo import TempoClient, TempoUnavailableError

# Phase 5 correction round #3: raw bytes that are not valid JSON at
# all -- resp.json() itself raises on this, exercising a different
# code path than "valid JSON, wrong shape" below.
NOT_JSON_BODY = b"this is not json {{{"

WINDOW_START = datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(minutes=30)


async def test_prometheus_client_runs_only_the_four_allowlisted_queries():
    seen_queries = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        seen_queries.append(params["query"])
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    summaries = await client.query_window(WINDOW_START, WINDOW_END)
    assert len(summaries) == 4
    assert len(seen_queries) == 4
    # Never anything the request/LLM could have influenced -- these
    # are the exact, fixed PromQL strings from the allowlist.
    assert all("service_name" in q or "otelcol_receiver" in q or q.startswith("up{") for q in seen_queries)


async def test_prometheus_client_reports_no_samples_without_crashing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    summaries = await client.query_window(WINDOW_START, WINDOW_END)
    assert all(s.sample_count == 0 for s in summaries)


async def test_prometheus_client_unavailable_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END)
        assert False, "expected PrometheusUnavailableError"
    except PrometheusUnavailableError:
        pass


async def test_loki_client_bounds_line_count_and_length():
    # Server returns 500 lines of 2000 chars each -- far beyond any
    # realistic bound.
    huge_values = [[str(1_700_000_000_000_000_000 + i), "X" * 2000] for i in range(500)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"result": [{"stream": {"service": "checkout-service"}, "values": huge_values}]},
            },
        )

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    lines = await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
    assert len(lines) == 20
    assert all(len(line.message) <= 100 for line in lines)


async def test_loki_client_unavailable_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
        assert False, "expected LokiUnavailableError"
    except LokiUnavailableError:
        pass


async def test_loki_client_query_only_targets_real_app_service_labels():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        captured["query"] = params["query"]
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
    for svc in ("checkout-service", "payment-service", "inventory-service", "notification-service"):
        assert svc in captured["query"]


async def test_tempo_client_bounds_trace_count():
    many_traces = [
        {
            "traceID": f"{i:032x}",
            "rootServiceName": "checkout-service",
            "rootTraceName": "POST /checkouts",
            "startTimeUnixNano": "1700000000000000000",
            "durationMs": 25,
        }
        for i in range(50)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"traces": many_traces})

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    traces = await client.search_window(WINDOW_START, WINDOW_END, max_traces=5)
    assert len(traces) == 5


async def test_tempo_client_never_fabricates_a_trace_id():
    """No traces found -> empty list, never a trace ID synthesized
    from the window or any other input."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"traces": []})

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    traces = await client.search_window(WINDOW_START, WINDOW_END, max_traces=5)
    assert traces == []


async def test_tempo_client_unavailable_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.search_window(WINDOW_START, WINDOW_END, max_traces=5)
        assert False, "expected TempoUnavailableError"
    except TempoUnavailableError:
        pass


# --- Phase 5 correction round #3: malformed-response handling -------

async def test_prometheus_client_handles_non_json_200_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NOT_JSON_BODY, headers={"content-type": "application/json"})

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END)
        assert False, "expected PrometheusUnavailableError"
    except PrometheusUnavailableError:
        pass


async def test_prometheus_client_handles_unexpected_result_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        # "result" is a string, not a list -- iterating it yields
        # characters, and calling .get() on a character must fail
        # cleanly rather than crash the service.
        return httpx.Response(200, json={"status": "success", "data": {"result": "not-a-list"}})

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END)
        assert False, "expected PrometheusUnavailableError"
    except PrometheusUnavailableError:
        pass


async def test_prometheus_client_skips_a_single_invalid_sample_without_failing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {"values": [["not-a-timestamp", "1"], [1700000000, "also-not-a-number"], [1700000001, "2"]]}
                    ]
                },
            },
        )

    client = PrometheusClient(
        "http://prometheus.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    # Must NOT raise -- individual bad samples are skipped, not fatal.
    summaries = await client.query_window(WINDOW_START, WINDOW_END)
    assert all(s.sample_count <= 1 for s in summaries)


async def test_loki_client_handles_non_json_200_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NOT_JSON_BODY, headers={"content-type": "application/json"})

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
        assert False, "expected LokiUnavailableError"
    except LokiUnavailableError:
        pass


async def test_loki_client_handles_unexpected_result_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": "not-a-list"}})

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
        assert False, "expected LokiUnavailableError"
    except LokiUnavailableError:
        pass


async def test_loki_client_skips_entries_with_invalid_timestamp_or_non_string_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {"service": "checkout-service"},
                            "values": [
                                ["not-a-timestamp", "real message"],
                                ["1700000000000000000", 12345],  # message is not a string
                                ["1700000001000000000", "good message"],
                            ],
                        }
                    ]
                },
            },
        )

    client = LokiClient(
        "http://loki.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    lines = await client.query_window(WINDOW_START, WINDOW_END, max_lines=20, max_line_length=100)
    assert len(lines) == 1
    assert lines[0].message == "good message"


async def test_tempo_client_search_handles_non_json_200_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NOT_JSON_BODY, headers={"content-type": "application/json"})

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.search_window(WINDOW_START, WINDOW_END, max_traces=5)
        assert False, "expected TempoUnavailableError"
    except TempoUnavailableError:
        pass


async def test_tempo_client_search_handles_unexpected_traces_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"traces": "not-a-list"})

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    try:
        await client.search_window(WINDOW_START, WINDOW_END, max_traces=5)
        assert False, "expected TempoUnavailableError"
    except TempoUnavailableError:
        pass


async def test_tempo_get_trace_detail_returns_none_never_raises_on_malformed_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NOT_JSON_BODY, headers={"content-type": "application/json"})

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    detail = await client.get_trace_detail("abcd" * 8)
    assert detail is None


async def test_tempo_get_trace_detail_returns_none_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    detail = await client.get_trace_detail("abcd" * 8)
    assert detail is None


async def test_tempo_get_trace_detail_summarizes_real_span_relationships():
    trace_id = "abcd" * 8

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout-service"}}]},
                            "scopeSpans": [{"spans": [{"spanId": "AAA="}]}],  # no parentSpanId -> root
                        },
                        {
                            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment-service"}}]},
                            "scopeSpans": [{"spans": [{"spanId": "BBB=", "parentSpanId": "AAA="}]}],
                        },
                    ]
                }
            },
        )

    client = TempoClient(
        "http://tempo.invalid", connect_timeout=1.0, request_timeout=1.0, transport=httpx.MockTransport(handler)
    )
    detail = await client.get_trace_detail(trace_id)
    assert detail is not None
    assert detail.span_count == 2
    assert detail.service_names == ("checkout-service", "payment-service")
    assert detail.root_span_services == ("checkout-service",)
