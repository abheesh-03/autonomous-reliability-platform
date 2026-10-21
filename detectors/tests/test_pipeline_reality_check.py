"""Gate G: the reality-check end-to-end tests. Exercises the REAL
pipeline (`detectors.pipeline.run.run_pipeline`) -- real Prometheus/
Tempo/control-plane clients, real statistical algorithms, real graph
builder, real correlation engine, real finding construction -- against
synthetic (httpx.MockTransport) data, never a mocked function
returning a preset final answer.

The scenario does NOT correspond to any of the 800 catalog scenarios:
payment-service starts returning errors; checkout-service (which calls
it) shows elevated latency as a consequence; a real trace shows the
observed dependency. This is a synthetic test, and is never claimed to
prove production coverage (see this module's own final test)."""

import base64
from datetime import UTC, datetime, timedelta

import httpx

from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.clients.prometheus_client import PrometheusClient
from detectors.clients.tempo_client import TempoClient
from detectors.pipeline.orchestrator import PipelineConfig
from detectors.pipeline.run import run_pipeline
from detectors.schemas.anomaly import DetectionResult

NOW = datetime.now(UTC) - timedelta(minutes=1)


def _b64(hex_str: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_str)).decode()


def _series_over_request_window(values: list[float], params: dict[str, str]) -> list[list]:
    """Places `values` evenly spaced across the ACTUAL [start, end]
    the client requested (never a hardcoded/independent timestamp
    basis) -- so a values list structured as "N-10 baseline points
    then 10 observation points" lands correctly on each side of the
    detector's own boundary regardless of exact window arithmetic."""
    start, end = float(params["start"]), float(params["end"])
    n = len(values)
    if n == 1:
        return [[start, values[0]]]
    return [[start + i * (end - start) / (n - 1), v] for i, v in enumerate(values)]


def _prometheus_handler(scenario: dict[str, dict[str, list]]):
    """`scenario` maps service -> {"errors":[...], "total":[...],
    "latency":[...]} -- each a baseline+observation series, structured
    as [...60 baseline points..., ...10 observation points...] to match
    PipelineConfig's default 1h baseline / 10min observation window."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query.decode()))
        query = params["query"]
        if "up{job" in query:
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window([1.0] * 70, params)}]}})
        if "refused" in query:
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window([0.0] * 70, params)}]}})

        for service, data in scenario.items():
            if f'service_name="{service}"' not in query:
                continue
            if "5.." in query:
                return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window(data["errors"], params)}]}})
            if "histogram_quantile" in query:
                return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window(data["latency"], params)}]}})
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": _series_over_request_window(data["total"], params)}]}})
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    return handler


def _healthy_series(n_baseline=60, n_obs=10):
    return {"errors": [0.5] * (n_baseline + n_obs), "total": [50.0] * (n_baseline + n_obs), "latency": [0.1] * (n_baseline + n_obs)}


def _control_plane_empty() -> ControlPlaneClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    return ControlPlaneClient("http://control-plane.invalid", transport=httpx.MockTransport(handler))


def _tempo_with_trace(upstream: str, downstream: str, *, downstream_error: bool) -> TempoClient:
    trace_id = "11" * 16
    span_a = "aa" * 8
    span_b = "bb" * 8

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

    return TempoClient("http://tempo.invalid", transport=httpx.MockTransport(handler))


async def test_unknown_cascading_failure_produces_evidence_grounded_findings_with_no_catalog_match():
    scenario = {
        "checkout-service": {"errors": [0.5] * 70, "total": [50.0] * 70, "latency": [0.1] * 60 + [2.5] * 10},
        "payment-service": {"errors": [0.5] * 60 + [25.0] * 10, "total": [50.0] * 70, "latency": [0.1] * 70},
        "inventory-service": _healthy_series(),
        "notification-service": _healthy_series(),
    }
    prom = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(_prometheus_handler(scenario)))
    tempo = _tempo_with_trace("checkout-service", "payment-service", downstream_error=True)
    cp = _control_plane_empty()

    report = await run_pipeline(prometheus_client=prom, tempo_client=tempo, control_plane_client=cp, now=NOW)

    # 1. Identify the deviation.
    anomalous = {r.service: r.detector_id for r in report.anomaly_results if r.result == DetectionResult.ANOMALY_DETECTED}
    assert anomalous.get("checkout-service") == "latency_deviation"
    assert anomalous.get("payment-service") == "error_rate_deviation"

    # 2. Associate affected services using trace evidence.
    assert report.dependency_graph is not None
    assert any(
        e.upstream_service == "checkout-service" and e.downstream_service == "payment-service"
        for e in report.dependency_graph.edges
    )

    # 3. Correlate related anomaly findings. The aggregate Prometheus
    # anomalies here carry no trace attribution of their own (the
    # orchestrator never attaches any to a metric-only finding), so
    # per the final evidence-integrity correction (Issue A) the
    # Tempo-observed edge's generic error_observed=True can never, by
    # itself, prove these two SPECIFIC findings share an incident --
    # the honest result is a tentative (weak) association, never a
    # strong, asserted group.
    assert report.correlation_groups == []
    assert len(report.tentative_associations) == 1
    assert set(report.tentative_associations[0].item_ids) == {
        "anomaly:latency_deviation:checkout-service",
        "anomaly:error_rate_deviation:payment-service",
    }

    # 4. Produce plausible investigation hypotheses, naming payment-service.
    checkout_finding = next(f for f in report.findings if f.observed_service_or_resource == "checkout-service")
    assert len(checkout_finding.hypotheses) >= 1
    assert "payment-service" in checkout_finding.hypotheses[0].likely_affected_dependencies

    # 5. Show actual supporting measurements.
    assert checkout_finding.observations[0].measured_signals
    assert checkout_finding.observations[0].measured_signals[0].observed_value != "n/a"

    # 6. Label root cause as candidate, not established fact.
    assert checkout_finding.hypotheses[0].confidence < 1.0
    assert "candidate" in checkout_finding.hypotheses[0].uncertainty_notes.lower()

    # 7. Output zero required catalog matches.
    assert all(f.candidate_known_scenario_matches == [] for f in report.findings)
    assert all(f.unresolved_classification is True for f in report.findings)

    # 8. Never invoke remediation.
    assert all(f.remediation_proposals == [] for f in report.findings)
    assert all(f.executions == [] for f in report.findings)


async def test_healthy_system_produces_zero_findings():
    scenario = {
        "checkout-service": _healthy_series(),
        "payment-service": _healthy_series(),
        "inventory-service": _healthy_series(),
        "notification-service": _healthy_series(),
    }
    prom = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(_prometheus_handler(scenario)))
    tempo = _tempo_with_trace("checkout-service", "payment-service", downstream_error=False)
    cp = _control_plane_empty()

    report = await run_pipeline(prometheus_client=prom, tempo_client=tempo, control_plane_client=cp, now=NOW)

    assert all(r.result == DetectionResult.NO_ANOMALY for r in report.anomaly_results)
    assert report.findings == []
    assert report.correlation_groups == []


async def test_unrelated_simultaneous_failures_remain_separate_findings():
    """checkout-service and notification-service BOTH show real
    anomalies at the same time, but there is no observed dependency
    edge, shared trace, or fingerprint between them -- they must
    produce two SEPARATE findings, never one fabricated correlation."""
    scenario = {
        "checkout-service": {"errors": [0.5] * 60 + [25.0] * 10, "total": [50.0] * 70, "latency": [0.1] * 70},
        "payment-service": _healthy_series(),
        "inventory-service": _healthy_series(),
        "notification-service": {"errors": [0.5] * 60 + [25.0] * 10, "total": [50.0] * 70, "latency": [0.1] * 70},
    }
    prom = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(_prometheus_handler(scenario)))
    # the only observed trace connects checkout -> payment, NOT notification
    tempo = _tempo_with_trace("checkout-service", "payment-service", downstream_error=False)
    cp = _control_plane_empty()

    report = await run_pipeline(prometheus_client=prom, tempo_client=tempo, control_plane_client=cp, now=NOW)

    assert len(report.findings) == 2
    services_with_findings = {f.observed_service_or_resource for f in report.findings}
    assert services_with_findings == {"checkout-service", "notification-service"}
    # no correlation group should merge them -- no edge, no shared trace/fingerprint
    for group in report.correlation_groups:
        assert not ({"checkout-service", "notification-service"} <= set(group.correlated_services))


def test_this_synthetic_test_never_claims_production_coverage():
    """Documentation-as-code: this module's own docstring states the
    limitation explicitly; this test exists so that claim is checked
    for presence, not merely asserted in prose that could silently rot."""
    import detectors.tests.test_pipeline_reality_check as this_module

    doc = this_module.__doc__ or ""
    assert "never claimed to" in doc and "production coverage" in doc
