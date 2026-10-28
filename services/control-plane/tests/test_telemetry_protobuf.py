"""Phase 16 correction round, item 3: proves this endpoint genuinely
decodes a REAL OTLP/HTTP protobuf body -- built here with the
project's own `opentelemetry-proto` generated message classes, the
exact same classes the real official OpenTelemetry SDK exporters use
to build the identical wire bytes. This is a unit-level proof that the
decode path (ingestion/otlp_protobuf.py) is correct; the SEPARATE,
real official-SDK-against-the-live-stack proof (not a pytest -- it
needs a running server) is
scripts/verify-telemetry-correction.sh's own "official SDK" section,
documented in docs/architecture/phase-16-secure-telemetry-onboarding.md
Gate 3.
"""

import time
import uuid
from datetime import UTC, datetime

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.metrics.v1 import metrics_pb2

from control_plane.api.dependencies import (
    get_incident_repository,
    get_integration_credential_repository,
    get_service_repository,
    get_telemetry_repository,
)
from control_plane.core.credentials import format_bearer_token, hash_secret
from control_plane.core.rate_limit import AUTH_FAILURE_RATE_LIMITER, INGESTION_RATE_LIMITER
from control_plane.main import app
from tests.conftest import FakeIncidentRepository
from tests.test_integrations import FakeIntegrationCredentialRepo, FakeServiceRepo, SERVICE_A_ID
from tests.test_organization_scoping import ORG_A
from tests.test_telemetry_ingest import FakeTelemetryRepository


def _build_real_protobuf_export(
    *, status_code: int = 200, count: int = 1, sum_seconds: float = 0.05, temporality=None
) -> bytes:
    """Builds a REAL `ExportMetricsServiceRequest` protobuf message
    using the official generated classes -- the exact same message
    type the real OTLPMetricExporter (opentelemetry-exporter-otlp-
    proto-http) serializes via `.SerializeToString()` before sending
    it with `Content-Type: application/x-protobuf`."""
    temporality = metrics_pb2.AGGREGATION_TEMPORALITY_DELTA if temporality is None else temporality
    req = ExportMetricsServiceRequest()
    rm = req.resource_metrics.add()
    sm = rm.scope_metrics.add()
    metric = sm.metrics.add()
    metric.name = "http.server.request.duration"
    metric.unit = "s"
    metric.histogram.aggregation_temporality = temporality
    now_nanos = int(time.time() * 1_000_000_000)
    dp = metric.histogram.data_points.add()
    dp.start_time_unix_nano = now_nanos - 2_000_000_000
    dp.time_unix_nano = now_nanos
    dp.count = count
    dp.sum = sum_seconds
    method_attr = dp.attributes.add()
    method_attr.key = "http.request.method"
    method_attr.value.string_value = "GET"
    route_attr = dp.attributes.add()
    route_attr.key = "http.route"
    route_attr.value.string_value = "/work"
    status_attr = dp.attributes.add()
    status_attr.key = "http.response.status_code"
    status_attr.value.int_value = status_code
    return req.SerializeToString()


def _active_credential(services, credentials):
    from control_plane.core.credentials import generate_credential_id, generate_secret

    credential_id = generate_credential_id()
    secret = generate_secret()
    credentials.rows.append(
        {
            "id": uuid.uuid4(),
            "organization_id": ORG_A,
            "service_id": SERVICE_A_ID,
            "connection_type": "opentelemetry",
            "credential_id": credential_id,
            "credential_secret_hash": hash_secret(secret),
            "status": "active",
            "created_by_user_id": "user-1",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "revoked_at": None,
            "last_verified_telemetry_at": None,
        }
    )
    return format_bearer_token(credential_id, secret)


def _use():
    services = FakeServiceRepo([{"id": SERVICE_A_ID, "organization_id": ORG_A, "name": "checkout-api"}])
    credentials = FakeIntegrationCredentialRepo()
    telemetry = FakeTelemetryRepository()
    incidents = FakeIncidentRepository([])
    app.dependency_overrides[get_service_repository] = lambda: services
    app.dependency_overrides[get_integration_credential_repository] = lambda: credentials
    app.dependency_overrides[get_telemetry_repository] = lambda: telemetry
    app.dependency_overrides[get_incident_repository] = lambda: incidents
    return services, credentials, telemetry, incidents


def _clear():
    app.dependency_overrides.pop(get_service_repository, None)
    app.dependency_overrides.pop(get_integration_credential_repository, None)
    app.dependency_overrides.pop(get_telemetry_repository, None)
    app.dependency_overrides.pop(get_incident_repository, None)
    AUTH_FAILURE_RATE_LIMITER._events.clear()
    INGESTION_RATE_LIMITER._events.clear()


def test_real_otlp_protobuf_body_is_accepted(client):
    """Proves the decode path end to end: a genuine protobuf-encoded
    ExportMetricsServiceRequest, sent with the real
    `application/x-protobuf` content type, is accepted and its data
    reaches storage -- never silently dropped or misparsed."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        body = _build_real_protobuf_export(count=7, sum_seconds=0.7)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            content=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 200
        assert response.json() == {}
        assert len(telemetry.rows) == 1
        assert telemetry.rows[0]["request_count"] == 7
    finally:
        _clear()


def test_real_otlp_protobuf_cumulative_temporality_is_rejected(client):
    """Item 1 applies identically to the protobuf path -- no separate,
    looser validation path for protobuf bodies."""
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        body = _build_real_protobuf_export(temporality=metrics_pb2.AGGREGATION_TEMPORALITY_CUMULATIVE)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            content=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
        )
    finally:
        _clear()
    assert response.status_code == 400
    assert "DELTA" in response.json()["detail"]


def test_malformed_protobuf_body_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            content=bytes([0xFF] * 32),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
        )
    finally:
        _clear()
    assert response.status_code == 400


def test_unrecognized_content_type_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            content=b"whatever",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
    finally:
        _clear()
    assert response.status_code == 415
