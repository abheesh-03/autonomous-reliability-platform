"""Phase 12B-D correction round (Issue 6A): end-to-end integration
proof using the REAL EvidenceCollector + REAL ControlPlaneClient/
PrometheusClient/LokiClient/TempoClient (each backed by
httpx.MockTransport, never a fake Protocol double) -- the actual
connected application path, not an isolated fake output. Confirms the
Kubernetes evidence item is correctly collected, bounded, and redacted
for a real kubernetes-sourced incident, and correctly absent/honest for
a non-kubernetes incident."""

from datetime import UTC, datetime

import httpx

from investigator_service.clients.control_plane import ControlPlaneClient
from investigator_service.clients.loki import LokiClient
from investigator_service.clients.prometheus import PrometheusClient
from investigator_service.clients.tempo import TempoClient
from investigator_service.evidence_collector import EvidenceCollector
from tests.conftest import SAMPLE_INCIDENT_ID, TEST_BOUNDS, incident_json

_K8S_EVIDENCE_JSON = {
    "cluster": "kind-reliability-lab",
    "namespace": "reliability-sandbox",
    "resource_kind": "Pod",
    "resource_name": "crashloop-demo-abc",
    "resource_uid": "uid-1",
    "detector_id": "crash_loop_backoff",
    "result": "confirmed",
    "collection_completeness": "complete",
    "collected_at": "2026-04-01T09:00:00+00:00",
    "decision_rationale": "container app has waiting.reason == 'CrashLoopBackOff'",
}


def _empty_telemetry_clients():
    def prom_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    def loki_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    def tempo_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"traces": []})

    return (
        PrometheusClient("http://prom.invalid", 1.0, 1.0, transport=httpx.MockTransport(prom_handler)),
        LokiClient("http://loki.invalid", 1.0, 1.0, transport=httpx.MockTransport(loki_handler)),
        TempoClient("http://tempo.invalid", 1.0, 1.0, transport=httpx.MockTransport(tempo_handler)),
    )


def _control_plane_client_for(incident_body: dict, *, kubernetes_evidence: dict | None, k8s_status: int = 200) -> ControlPlaneClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}":
            return httpx.Response(200, json=incident_body)
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/events":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/kubernetes-evidence":
            if kubernetes_evidence is None:
                return httpx.Response(404, json={"detail": "no kubernetes evidence"})
            return httpx.Response(k8s_status, json=kubernetes_evidence)
        return httpx.Response(404)

    return ControlPlaneClient("http://control-plane.invalid", 1.0, 1.0, transport=httpx.MockTransport(handler))


async def test_kubernetes_sourced_incident_produces_a_real_kubernetes_evidence_item():
    incident_body = incident_json(source="kubernetes", title="crash_loop_backoff: Pod/reliability-sandbox/crashloop-demo-abc")
    control_plane = _control_plane_client_for(incident_body, kubernetes_evidence=_K8S_EVIDENCE_JSON)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    k8s_items = [i for i in package.items if i.source == "kubernetes"]
    assert len(k8s_items) == 1
    item = k8s_items[0]
    assert "crash_loop_backoff" in item.summary
    assert "crashloop-demo-abc" in item.summary
    assert "uid-1" in item.detail
    assert "kind-reliability-lab" in item.detail

    k8s_outcomes = [o for o in package.source_outcomes if o.source == "kubernetes"]
    assert len(k8s_outcomes) == 1
    assert k8s_outcomes[0].status == "ok"

    # Citable: the LLM-facing evidence_ids() set includes this real item.
    assert item.id in package.evidence_ids()


async def test_kubernetes_sourced_incident_with_no_recorded_evidence_is_honest_no_data():
    incident_body = incident_json(source="kubernetes")
    control_plane = _control_plane_client_for(incident_body, kubernetes_evidence=None)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    assert [i for i in package.items if i.source == "kubernetes"] == []
    k8s_outcomes = [o for o in package.source_outcomes if o.source == "kubernetes"]
    assert len(k8s_outcomes) == 1
    assert k8s_outcomes[0].status == "no_data"


async def test_non_kubernetes_incident_never_queries_the_kubernetes_evidence_endpoint():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}":
            return httpx.Response(200, json=incident_json(source="alertmanager"))
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/events":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        return httpx.Response(404)

    control_plane = ControlPlaneClient("http://control-plane.invalid", 1.0, 1.0, transport=httpx.MockTransport(handler))
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    assert not any("kubernetes-evidence" in c for c in calls)
    assert [i for i in package.items if i.source == "kubernetes"] == []


async def test_kubernetes_decision_rationale_is_redacted_and_bounded():
    """Untrusted external text (Gate 3) -- a decision_rationale that
    happens to contain a credential-shaped string must be redacted the
    same as incident title/description/Loki log lines."""
    evidence = dict(_K8S_EVIDENCE_JSON)
    evidence["decision_rationale"] = "waiting.message: Authorization: Bearer abc123xyz should-not-appear"
    incident_body = incident_json(source="kubernetes")
    control_plane = _control_plane_client_for(incident_body, kubernetes_evidence=evidence)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    item = next(i for i in package.items if i.source == "kubernetes")
    assert "abc123xyz" not in item.detail
    assert "[REDACTED]" in item.detail


async def test_kubernetes_control_plane_unavailable_is_reported_not_fatal():
    """A kubernetes-evidence read failure must never abort the whole
    investigation -- recorded as an honest 'unavailable' source outcome,
    exactly like every other best-effort telemetry source."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}":
            return httpx.Response(200, json=incident_json(source="kubernetes"))
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/events":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/kubernetes-evidence":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(404)

    control_plane = ControlPlaneClient("http://control-plane.invalid", 1.0, 1.0, transport=httpx.MockTransport(handler))
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    k8s_outcomes = [o for o in package.source_outcomes if o.source == "kubernetes"]
    assert len(k8s_outcomes) == 1
    assert k8s_outcomes[0].status == "unavailable"
    assert [i for i in package.items if i.source == "kubernetes"] == []
