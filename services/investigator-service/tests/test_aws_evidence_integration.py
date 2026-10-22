"""Phase 13: end-to-end integration proof using the REAL
EvidenceCollector + REAL ControlPlaneClient/PrometheusClient/
LokiClient/TempoClient (each backed by httpx.MockTransport, never a
fake Protocol double) -- mirrors
`test_kubernetes_evidence_integration.py`'s own structure exactly, for
the AWS source instead of Kubernetes."""

import httpx

from investigator_service.clients.control_plane import ControlPlaneClient
from investigator_service.clients.loki import LokiClient
from investigator_service.clients.prometheus import PrometheusClient
from investigator_service.clients.tempo import TempoClient
from investigator_service.evidence_collector import EvidenceCollector
from tests.conftest import SAMPLE_INCIDENT_ID, TEST_BOUNDS, incident_json

_AWS_EVIDENCE_JSON = {
    "account_id": "123456789012",
    "region": "us-east-1",
    "resource_kind": "CloudWatchAlarm",
    "resource_id": "checkout-high-error-rate",
    "resource_arn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:checkout-high-error-rate",
    "detector_id": "cloudwatch_alarm_in_alarm_state",
    "result": "confirmed",
    "collection_completeness": "complete",
    "collected_at": "2026-04-01T09:00:00+00:00",
    "decision_rationale": "CloudWatch alarm currently reports StateValue=ALARM",
    # Correction round, Issue 4: the SAME shape control-plane's own
    # GET /api/v1/incidents/{id}/aws-evidence now actually returns
    # (see domain/aws_finding.py's AwsIncidentEvidence and
    # ingestion/aws_mapping.py's aws_finding_event_metadata) -- the
    # end-to-end proof that this exact dict round-trips through real
    # ingestion is services/control-plane/tests/test_aws_ingestion.py
    # ::test_aws_evidence_preserves_decision_rationale_and_measured_evidence.
    "evidence": {
        "state_value": "ALARM", "state_reason": "Threshold Crossed: 1 datapoint was greater than 5.0",
        "namespace": "AWS/ApplicationELB", "metric_name": "HTTPCode_Target_5XX_Count",
    },
    "supporting_change_events": ["UpdateAlarm by alice at 2026-04-01T08:59:00Z"],
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


def _control_plane_client_for(incident_body: dict, *, aws_evidence: dict | None, aws_status: int = 200) -> ControlPlaneClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}":
            return httpx.Response(200, json=incident_body)
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/events":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        if path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/aws-evidence":
            if aws_evidence is None:
                return httpx.Response(404, json={"detail": "no aws evidence"})
            return httpx.Response(aws_status, json=aws_evidence)
        return httpx.Response(404)

    return ControlPlaneClient("http://control-plane.invalid", 1.0, 1.0, transport=httpx.MockTransport(handler))


async def test_aws_sourced_incident_produces_a_real_aws_evidence_item():
    incident_body = incident_json(source="aws", title="cloudwatch_alarm_in_alarm_state: aws/123456789012/us-east-1/CloudWatchAlarm/checkout-high-error-rate")
    control_plane = _control_plane_client_for(incident_body, aws_evidence=_AWS_EVIDENCE_JSON)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    aws_items = [i for i in package.items if i.source == "aws"]
    assert len(aws_items) == 1
    item = aws_items[0]
    assert "cloudwatch_alarm_in_alarm_state" in item.summary
    assert "checkout-high-error-rate" in item.summary
    assert "123456789012" in item.summary
    assert "us-east-1" in item.summary
    assert "UpdateAlarm" in item.detail
    assert "does not establish causation" in item.detail
    # Correction round, Issue 4: the original symptom (decision_rationale)
    # and its supporting measurements (the evidence dict -- CloudWatch
    # state/threshold detail) must actually be visible to the
    # investigator, not silently lost between ingestion and here.
    assert "CloudWatch alarm currently reports StateValue=ALARM" in item.detail
    assert "state_value=ALARM" in item.detail
    assert "Threshold Crossed" in item.detail
    assert "HTTPCode_Target_5XX_Count" in item.detail

    aws_outcomes = [o for o in package.source_outcomes if o.source == "aws"]
    assert len(aws_outcomes) == 1
    assert aws_outcomes[0].status == "ok"
    assert item.id in package.evidence_ids()


async def test_aws_sourced_incident_with_no_recorded_evidence_is_honest_no_data():
    incident_body = incident_json(source="aws")
    control_plane = _control_plane_client_for(incident_body, aws_evidence=None)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    assert [i for i in package.items if i.source == "aws"] == []
    aws_outcomes = [o for o in package.source_outcomes if o.source == "aws"]
    assert len(aws_outcomes) == 1
    assert aws_outcomes[0].status == "no_data"


async def test_non_aws_incident_never_queries_the_aws_evidence_endpoint():
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

    assert not any("aws-evidence" in c for c in calls)
    assert [i for i in package.items if i.source == "aws"] == []


async def test_aws_decision_rationale_is_redacted_and_bounded():
    evidence = dict(_AWS_EVIDENCE_JSON)
    evidence["decision_rationale"] = "waiting.message: Authorization: Bearer abc123xyz should-not-appear"
    incident_body = incident_json(source="aws")
    control_plane = _control_plane_client_for(incident_body, aws_evidence=evidence)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    item = next(i for i in package.items if i.source == "aws")
    assert "abc123xyz" not in item.detail
    assert "[REDACTED]" in item.detail


async def test_aws_measured_evidence_values_are_redacted_never_leaked():
    """Correction round, Issue 4: 'without leaking sensitive fields' --
    a measurement VALUE in the evidence dict is still AWS-reported,
    externally-sourced text (e.g. a CloudWatch state_reason could in
    principle echo back something credential-shaped) and must be
    redacted exactly like decision_rationale/log lines/every other
    piece of external text this collector already handles."""
    evidence = dict(_AWS_EVIDENCE_JSON)
    evidence["evidence"] = {"state_reason": "Authorization: Bearer abc123xyz should-not-appear"}
    incident_body = incident_json(source="aws")
    control_plane = _control_plane_client_for(incident_body, aws_evidence=evidence)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    item = next(i for i in package.items if i.source == "aws")
    assert "abc123xyz" not in item.detail
    assert "[REDACTED]" in item.detail


async def test_aws_control_plane_unavailable_is_reported_not_fatal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}":
            return httpx.Response(200, json=incident_json(source="aws"))
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/events":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
        if request.url.path == f"/api/v1/incidents/{SAMPLE_INCIDENT_ID}/aws-evidence":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(404)

    control_plane = ControlPlaneClient("http://control-plane.invalid", 1.0, 1.0, transport=httpx.MockTransport(handler))
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))

    aws_outcomes = [o for o in package.source_outcomes if o.source == "aws"]
    assert len(aws_outcomes) == 1
    assert aws_outcomes[0].status == "unavailable"
    assert [i for i in package.items if i.source == "aws"] == []


async def test_aws_partial_collection_completeness_is_reported_as_partial():
    evidence = dict(_AWS_EVIDENCE_JSON)
    evidence["collection_completeness"] = "partial"
    incident_body = incident_json(source="aws")
    control_plane = _control_plane_client_for(incident_body, aws_evidence=evidence)
    prometheus, loki, tempo = _empty_telemetry_clients()
    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, TEST_BOUNDS)

    package = await collector.collect(str(SAMPLE_INCIDENT_ID))
    aws_outcomes = [o for o in package.source_outcomes if o.source == "aws"]
    assert aws_outcomes[0].status == "partial"
