"""Gate J `replay` support: builds fully offline, MockTransport-backed
clients from a JSON fixture file -- the SAME shape the `--synthetic`
mode of `python -m detectors replay` consumes. No network call is ever
made in this mode; every response is generated in-process from the
fixture's own data.

Fixture shape (see `detectors/tests/fixtures/cascading_failure.json`
for a worked example):

{
  "prometheus": {
    "<service>": {"errors": [...], "total": [...], "latency": [...]}
  },
  "tempo": {"upstream": "...", "downstream": "...", "downstream_error": bool} | null,
  "control_plane_incidents": [{"id": "...", "status": "...", "severity": "...", "source": "..."}]
}

Each service's three lists must together span exactly
`baseline_minutes + observation_minutes` points (default 70); they are
placed evenly across whatever window the pipeline actually requests,
so the exact sample count must match what `PipelineConfig` will ask
for (60 baseline + 10 observation samples by default).
"""

import base64
import json
import pathlib
from datetime import datetime

import httpx

from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.clients.prometheus_client import PrometheusClient
from detectors.clients.tempo_client import TempoClient


class FixtureError(Exception):
    pass


def _b64(hex_str: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_str)).decode()


def _series_over_request_window(values: list[float], params: dict[str, str]) -> list[list]:
    start, end = float(params["start"]), float(params["end"])
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [[start, values[0]]]
    return [[start + i * (end - start) / (n - 1), v] for i, v in enumerate(values)]


def _build_prometheus_client(prometheus_fixture: dict, reference_now: datetime) -> PrometheusClient:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        query = params["query"]
        if "up{job" in query:
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window([1.0] * 70, params)}]}})
        if "refused" in query:
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window([0.0] * 70, params)}]}})
        for service, data in prometheus_fixture.items():
            if f'service_name="{service}"' not in query:
                continue
            key = "errors" if "5.." in query else "latency" if "histogram_quantile" in query else "total"
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window(data.get(key, []), params)}]}})
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    # `clock` is pinned to the SAME fixed reference instant the
    # pipeline itself uses as `now` -- never real wall-clock time --
    # so the MAX_LOOKBACK bound check (which compares against "now")
    # stays satisfied regardless of when `replay` actually runs, and
    # two runs of the same fixture stay byte-for-byte deterministic.
    return PrometheusClient(
        "http://fixture.prometheus.invalid", transport=httpx.MockTransport(handler), clock=lambda: reference_now
    )


def _build_tempo_client(tempo_fixture: dict | None) -> TempoClient:
    if tempo_fixture is None:
        def empty_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"traces": []})

        return TempoClient("http://fixture.tempo.invalid", transport=httpx.MockTransport(empty_handler))

    upstream = tempo_fixture["upstream"]
    downstream = tempo_fixture["downstream"]
    downstream_error = bool(tempo_fixture.get("downstream_error", False))
    trace_id = "11" * 16
    span_a, span_b = "aa" * 8, "bb" * 8

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/search" in request.url.path:
            return httpx.Response(200, json={"traces": [{"traceID": trace_id}]})
        body = {
            "trace": {
                "resourceSpans": [
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": upstream}}]},
                        "scopeSpans": [{"spans": [
                            {"traceId": _b64(trace_id), "spanId": _b64(span_a), "kind": "SPAN_KIND_SERVER",
                             "startTimeUnixNano": "0", "endTimeUnixNano": "5000000"}
                        ]}],
                    },
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": downstream}}]},
                        "scopeSpans": [{"spans": [
                            {"traceId": _b64(trace_id), "spanId": _b64(span_b), "parentSpanId": _b64(span_a),
                             "kind": "SPAN_KIND_SERVER", "startTimeUnixNano": "100000", "endTimeUnixNano": "4900000",
                             **({"status": {"code": "STATUS_CODE_ERROR"}} if downstream_error else {})}
                        ]}],
                    },
                ]
            }
        }
        return httpx.Response(200, json=body)

    return TempoClient("http://fixture.tempo.invalid", transport=httpx.MockTransport(handler))


def _build_control_plane_client(incidents_fixture: list) -> ControlPlaneClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": incidents_fixture, "total": len(incidents_fixture), "limit": 100, "offset": 0})

    return ControlPlaneClient("http://fixture.control-plane.invalid", transport=httpx.MockTransport(handler))


def load_fixture_clients(
    fixture_path: pathlib.Path, *, reference_now: datetime
) -> tuple[PrometheusClient, TempoClient, ControlPlaneClient]:
    if not fixture_path.is_file():
        raise FixtureError(f"fixture not found: {fixture_path}")
    try:
        data = json.loads(fixture_path.read_text())
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture is not valid JSON: {exc}") from exc

    prometheus_fixture = data.get("prometheus", {})
    if not isinstance(prometheus_fixture, dict):
        raise FixtureError("fixture['prometheus'] must be an object")

    return (
        _build_prometheus_client(prometheus_fixture, reference_now),
        _build_tempo_client(data.get("tempo")),
        _build_control_plane_client(data.get("control_plane_incidents", [])),
    )
