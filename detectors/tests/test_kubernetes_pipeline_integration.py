"""Gate F (Phase 12A): end-to-end pipeline integration tests for the
additive, opt-in Kubernetes observation stage -- real pipeline code
(`detectors.pipeline.run.run_pipeline`), synthetic Kubernetes API
responses via httpx.MockTransport, never a mocked function returning
a preset final answer."""

from datetime import UTC, datetime, timedelta

import httpx

from detectors.clients.kubernetes_client import KubernetesClient
from detectors.pipeline.run import run_pipeline
from detectors.schemas.kubernetes import CollectionOutcome

NOW = datetime.now(UTC) - timedelta(minutes=1)


def _k8s_client(handler) -> KubernetesClient:
    return KubernetesClient("https://k8s.invalid:6443", "reliability-sandbox", transport=httpx.MockTransport(handler))


def _pod(name, waiting_reason=None, phase="Running"):
    cs = {"name": "app", "image": "nginx", "ready": True, "restartCount": 0, "state": {"running": {}}}
    if waiting_reason:
        cs = {"name": "app", "image": "nginx", "ready": False, "restartCount": 0, "state": {"waiting": {"reason": waiting_reason}}}
    return {
        "metadata": {"name": name, "namespace": "reliability-sandbox", "uid": "u-1"},
        "spec": {"nodeName": "node-1"},
        "status": {"phase": phase, "containerStatuses": [cs], "conditions": []},
    }


def _list_handler(pods=None, deployments=None, replicasets=None, events=None, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/pods" in path:
            return httpx.Response(status_code, json={"items": pods or []})
        if "/deployments" in path:
            return httpx.Response(status_code, json={"items": deployments or []})
        if "/replicasets" in path:
            return httpx.Response(status_code, json={"items": replicasets or []})
        if "/events" in path:
            return httpx.Response(status_code, json={"items": events or []})
        return httpx.Response(404)

    return handler


async def test_no_kubernetes_client_means_not_executed_never_a_failure_of_other_stages():
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, kubernetes_client=None, now=NOW)
    assert ("kubernetes_observation", "no Kubernetes client was supplied") in report.checks_not_executed
    assert report.k8s_findings == []
    assert report.k8s_collection_results == []
    # the pipeline itself still completes successfully -- no exception, a real (empty) report
    assert report.summary


async def test_kubernetes_client_supplied_produces_real_findings_end_to_end():
    handler = _list_handler(pods=[_pod("image-pull-demo-x", waiting_reason="ImagePullBackOff")])
    k8s_client = _k8s_client(handler)
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, kubernetes_client=k8s_client, now=NOW)

    assert len(report.k8s_findings) == 1
    assert report.k8s_findings[0].detector_id == "image_pull_backoff"
    assert len(report.findings) == 1
    assert report.findings[0].observed_service_or_resource == "Pod/reliability-sandbox/image-pull-demo-x"
    assert report.findings[0].candidate_known_scenario_matches == []
    assert report.findings[0].remediation_proposals == []


async def test_healthy_kubernetes_cluster_produces_zero_k8s_findings():
    handler = _list_handler(pods=[_pod("healthy-web-x")])
    k8s_client = _k8s_client(handler)
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, kubernetes_client=k8s_client, now=NOW)
    assert report.k8s_findings == []
    collection = {cr.resource_kind: cr.outcome for cr in report.k8s_collection_results}
    assert collection["Pod"] == CollectionOutcome.SUCCESS


async def test_forbidden_kubernetes_api_never_produces_a_false_healthy_result():
    handler = _list_handler(status_code=403)
    k8s_client = _k8s_client(handler)
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, kubernetes_client=k8s_client, now=NOW)
    assert report.k8s_findings == []
    assert any(cr.outcome == CollectionOutcome.FORBIDDEN for cr in report.k8s_collection_results)
    assert any("kubernetes_pod_detectors" in name for name, _ in report.checks_not_executed)


async def test_kubernetes_unavailable_never_produces_a_false_healthy_result():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    k8s_client = _k8s_client(handler)
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, kubernetes_client=k8s_client, now=NOW)
    assert report.k8s_findings == []
    assert any(cr.outcome == CollectionOutcome.UNAVAILABLE for cr in report.k8s_collection_results)


async def test_kubernetes_and_prometheus_findings_are_never_auto_correlated():
    """No attributable evidence exists between the K8s sandbox and the
    Prometheus-monitored services -- they must never be merged into
    one correlation group."""
    from detectors.clients.prometheus_client import PrometheusClient

    def prom_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    def k8s_handler(request: httpx.Request) -> httpx.Response:
        if "/pods" in request.url.path:
            return httpx.Response(200, json={"items": [_pod("oom-demo-x")]})
        return httpx.Response(200, json={"items": []})

    prom_client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(prom_handler))
    k8s_client = _k8s_client(k8s_handler)
    report = await run_pipeline(prometheus_client=prom_client, tempo_client=None, control_plane_client=None, kubernetes_client=k8s_client, now=NOW)
    assert report.correlation_groups == []  # K8s findings are not even submitted as correlation items
