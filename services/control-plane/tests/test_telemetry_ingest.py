"""Phase 16 Gate 4/8: POST /api/v1/telemetry/otlp/v1/metrics.

Real credential hashing/verification throughout -- a real CSPRNG secret
is generated and hashed via core/credentials.py exactly as the real
create-credential endpoint would, never a hand-waved stand-in token.
Covers the Gate 8 negative-control list this endpoint itself is
responsible for: missing/invalid/revoked credential, spoofed
organization label (there is no code path to even supply one),
oversized/malformed payload, empty telemetry, and rate limiting.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from control_plane.api.dependencies import (
    get_incident_repository,
    get_integration_credential_repository,
    get_service_repository,
    get_telemetry_repository,
)
from control_plane.core.credentials import format_bearer_token, generate_credential_id, generate_secret, hash_secret
from control_plane.core.rate_limit import AUTH_FAILURE_RATE_LIMITER, INGESTION_RATE_LIMITER
from control_plane.main import app
from tests.conftest import FakeIncidentRepository
from tests.test_integrations import FakeIntegrationCredentialRepo, FakeServiceRepo, SERVICE_A_ID
from tests.test_organization_scoping import ORG_A


class FakeTelemetryRepository:
    """Item 5: dedup is approximated here too (the same stable-
    timeseries-identity tuple V16's real unique index enforces), so the
    route/service logic above the storage layer can be exercised
    without a real database -- the REAL, PostgreSQL-backed proof of
    `ON CONFLICT ... DO NOTHING` under concurrency is
    scripts/verify-telemetry-correction.sh, not this fake (same
    established convention as FakeIncidentRepository's own upsert
    dedup; see tests/conftest.py's own docstring)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seen_keys: set[tuple] = set()

    def _dedup_key(self, service_id, point: dict) -> tuple:
        return (
            str(service_id),
            point["observed_at"],
            point.get("http_method") or "",
            point.get("http_route") or "",
            point.get("http_status_code") if point.get("http_status_code") is not None else -1,
        )

    async def insert_batch(self, *, organization_id, service_id, integration_credential_id, points):
        inserted = 0
        for point in points:
            key = self._dedup_key(service_id, point)
            if key in self._seen_keys:
                continue
            self._seen_keys.add(key)
            self.rows.append(
                {
                    "organization_id": organization_id,
                    "service_id": service_id,
                    "integration_credential_id": integration_credential_id,
                    **point,
                }
            )
            inserted += 1
        return inserted

    async def get_window_aggregate(self, *, organization_id, service_id, since, until):
        matched = [
            r
            for r in self.rows
            if str(r["organization_id"]) == str(organization_id)
            and str(r["service_id"]) == str(service_id)
            and since <= r["observed_at"] < until
        ]
        request_count = sum(r["request_count"] for r in matched)
        error_count = sum(r["request_count"] for r in matched if r["is_error"])
        duration_sum = sum(r.get("duration_sum_seconds", 0.0) for r in matched)
        return {
            "request_count": request_count,
            "error_count": error_count,
            "last_observed_at": max((r["observed_at"] for r in matched), default=None),
            # Item 4: a real, correctly-weighted mean -- the same
            # formula the real SQL aggregate now uses, never a
            # percentile of per-row means.
            "mean_latency_seconds": (duration_sum / request_count) if request_count > 0 else None,
        }

    async def get_last_observed_at(self, *, organization_id, service_id):
        matched = [
            r for r in self.rows if str(r["organization_id"]) == str(organization_id) and str(r["service_id"]) == str(service_id)
        ]
        return max((r["observed_at"] for r in matched), default=None)


def _active_credential(services, credentials):
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


def _histogram_payload(
    *,
    status_code: int = 200,
    count: int = 1,
    sum_seconds: float = 0.05,
    when: datetime | None = None,
    aggregation_temporality: int | None = 1,
    unit: str | None = "s",
    start_when: datetime | None = None,
    route: str = "/work",
):
    observed = when or datetime.now(UTC)
    nanos = int(observed.timestamp() * 1_000_000_000)
    histogram: dict = {
        "dataPoints": [
            {
                "attributes": [
                    {"key": "http.request.method", "value": {"stringValue": "GET"}},
                    {"key": "http.route", "value": {"stringValue": route}},
                    {"key": "http.response.status_code", "value": {"intValue": str(status_code)}},
                ],
                "timeUnixNano": str(nanos),
                "count": str(count),
                "sum": sum_seconds,
            }
        ]
    }
    if start_when is not None:
        histogram["dataPoints"][0]["startTimeUnixNano"] = str(int(start_when.timestamp() * 1_000_000_000))
    if aggregation_temporality is not None:
        histogram["aggregationTemporality"] = aggregation_temporality
    metric: dict = {"name": "http.server.request.duration", "histogram": histogram}
    if unit is not None:
        metric["unit"] = unit
    return {"resourceMetrics": [{"scopeMetrics": [{"metrics": [metric]}]}]}


@pytest.fixture(autouse=True)
def _clean_rate_limiters():
    yield
    AUTH_FAILURE_RATE_LIMITER._events.clear()
    INGESTION_RATE_LIMITER._events.clear()


def test_missing_credential_is_401(client):
    _use()
    try:
        response = client.post("/api/v1/telemetry/otlp/v1/metrics", json=_histogram_payload())
    finally:
        _clear()
    assert response.status_code == 401


def test_malformed_bearer_token_is_401(client):
    _use()
    try:
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    finally:
        _clear()
    assert response.status_code == 401


def test_invalid_credential_is_401(client):
    _use()
    try:
        fake_token = format_bearer_token(generate_credential_id(), generate_secret())
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(),
            headers={"Authorization": f"Bearer {fake_token}"},
        )
    finally:
        _clear()
    assert response.status_code == 401


def test_wrong_secret_for_a_real_credential_id_is_401(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        credential_id = token.split(".")[0]
        wrong_token = format_bearer_token(credential_id, generate_secret())
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(),
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
    finally:
        _clear()
    assert response.status_code == 401


def test_revoked_credential_is_401(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        credentials.rows[0]["status"] = "revoked"
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 401


def test_cross_organization_credential_cannot_be_used_against_a_different_services_data(client):
    """Proves a credential bound to Org A's service only ever writes
    into Org A's own telemetry -- there is no field on the request a
    caller could use to redirect it elsewhere."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert all(str(r["organization_id"]) == str(ORG_A) for r in telemetry.rows)
        assert all(str(r["service_id"]) == str(SERVICE_A_ID) for r in telemetry.rows)
    finally:
        _clear()


def test_valid_credential_accepts_real_telemetry(client):
    """Item 2: a fully-accepted export returns HTTP 200 with the real
    OTLP `ExportMetricsServiceResponse` empty-success shape (`{}`) --
    not a custom 202/`accepted_data_points` body."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(count=5, sum_seconds=0.5),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() == {}
        assert len(telemetry.rows) == 1
        assert telemetry.rows[0]["request_count"] == 5
        assert credentials.rows[0]["last_verified_telemetry_at"] is not None
    finally:
        _clear()


def test_empty_telemetry_is_rejected_with_a_clear_error(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json={"resourceMetrics": []},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400


def test_malformed_otlp_payload_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json={"resourceMetrics": "this should be a list"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 422


def test_unsupported_metric_name_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = {
            "resourceMetrics": [
                {"scopeMetrics": [{"metrics": [{"name": "some.other.metric", "histogram": {"dataPoints": []}}]}]}
            ]
        }
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400


def test_stale_data_point_outside_accepted_window_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        ancient = datetime.now(UTC) - timedelta(days=30)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(when=ancient),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400


def test_duplicate_retried_submission_is_deduplicated_and_stored_once(client):
    """Item 5 (correction round -- this test's PREVIOUS name,
    `..._is_accepted_idempotently_without_error`, claimed "idempotent"
    while asserting the duplicate was stored TWICE, which is not
    idempotent at all -- a real OTel SDK retry naturally re-sends the
    exact same DELTA export, and storing it twice silently inflates
    request_count/error-rate/mean-latency and the incident detector's
    own window aggregate.

    Retrying the EXACT same payload twice must never error (an
    at-least-once delivery contract), but the retried observation must
    be durably deduplicated -- stored exactly once, not twice."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = _histogram_payload()
        first = client.post("/api/v1/telemetry/otlp/v1/metrics", json=payload, headers={"Authorization": f"Bearer {token}"})
        second = client.post("/api/v1/telemetry/otlp/v1/metrics", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(telemetry.rows) == 1
    finally:
        _clear()


def test_distinct_intervals_are_both_accepted_and_not_deduplicated(client):
    """A genuinely distinct interval (a different `observed_at`) must
    never be mistaken for a duplicate -- dedup is keyed on the real
    timeseries identity, not merely "same credential, same route"."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        now = datetime.now(UTC)
        first = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(when=now),
            headers={"Authorization": f"Bearer {token}"},
        )
        second = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(when=now + timedelta(seconds=5)),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(telemetry.rows) == 2
    finally:
        _clear()


def test_successive_delta_exports_are_not_double_counted(client):
    """Item 1: two successive, genuinely distinct DELTA exports (each
    reporting its own real count for its own real interval) must sum
    correctly -- never the inflation a mishandled CUMULATIVE export (or
    a parser that ignores temporality) would produce."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        now = datetime.now(UTC)
        client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(count=3, sum_seconds=0.3, when=now, start_when=now - timedelta(seconds=5)),
            headers={"Authorization": f"Bearer {token}"},
        )
        client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(
                count=4, sum_seconds=0.4, when=now + timedelta(seconds=5), start_when=now
            ),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert len(telemetry.rows) == 2
        assert sum(r["request_count"] for r in telemetry.rows) == 7
    finally:
        _clear()


def test_oversized_payload_is_rejected_by_the_asgi_body_size_guard(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        # Exceeds MAX_TELEMETRY_BODY_BYTES (512 KiB) via one enormous
        # attribute value -- the ASGI middleware must reject this before
        # it is ever parsed as JSON at all.
        huge_payload = _histogram_payload()
        huge_payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"][0]["attributes"].append(
            {"key": "padding", "value": {"stringValue": "x" * (600 * 1024)}}
        )
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=huge_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 413


def test_excessive_request_rate_is_rate_limited(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        statuses = []
        for _ in range(65):
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses
        assert statuses.count(200) <= 60
    finally:
        _clear()


def test_repeated_auth_failures_are_rate_limited(client):
    _use()
    try:
        fake_token = format_bearer_token(generate_credential_id(), generate_secret())
        statuses = []
        for _ in range(15):
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": f"Bearer {fake_token}"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses
    finally:
        _clear()


def test_many_different_fake_credential_ids_from_one_source_are_still_rate_limited(client):
    """Item 6 (correction round): the previous round's auth-failure
    limiter keyed its budget by the credential id the CALLER CLAIMED --
    entirely attacker-controlled -- so an attacker could reset their
    own budget forever by simply fabricating a new id on every request.
    Proves that no longer works: 15 requests, each with a DIFFERENT
    fabricated credential id, from the SAME source, must still trip the
    limiter (keyed on the real connecting address now, never the
    claimed id)."""
    _use()
    try:
        statuses = []
        for _ in range(15):
            fake_token = format_bearer_token(generate_credential_id(), generate_secret())
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": f"Bearer {fake_token}"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses
    finally:
        _clear()


def test_missing_authorization_header_is_rate_limited(client):
    """Item 6: a missing header is just as cheap an auth-failure probe
    as a malformed one, and must be bounded the same way."""
    _use()
    try:
        statuses = []
        for _ in range(15):
            resp = client.post("/api/v1/telemetry/otlp/v1/metrics", json=_histogram_payload())
            statuses.append(resp.status_code)
        assert all(s == 401 for s in statuses[:10])
        assert 429 in statuses
    finally:
        _clear()


def test_malformed_authorization_header_is_rate_limited(client):
    _use()
    try:
        statuses = []
        for _ in range(15):
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": "Bearer not-a-real-token"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses
    finally:
        _clear()


def test_repeated_invalid_secret_for_the_same_real_credential_id_is_rate_limited(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        credential_id = token.split(".")[0]
        statuses = []
        for _ in range(15):
            wrong_token = format_bearer_token(credential_id, generate_secret())
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": f"Bearer {wrong_token}"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses
    finally:
        _clear()


def test_different_legitimate_credentials_have_independent_ingestion_budgets(client):
    """The INGESTION_RATE_LIMITER (distinct from the auth-failure
    limiter item 6 fixes) is keyed by credential id -- correctly so,
    since only an ALREADY-AUTHENTICATED credential reaches it. Proves a
    second, different, equally-legitimate credential is not penalized
    by the first one's own ingestion volume."""
    services, credentials, _, _ = _use()
    try:
        token_a = _active_credential(services, credentials)
        service_b_id = uuid.uuid4()
        services.rows.append({"id": service_b_id, "organization_id": ORG_A, "name": "other-service"})
        credentials.rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": ORG_A,
                "service_id": service_b_id,
                "connection_type": "opentelemetry",
                "credential_id": (cred_id_b := generate_credential_id()),
                "credential_secret_hash": hash_secret(secret_b := generate_secret()),
                "status": "active",
                "created_by_user_id": "user-1",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "revoked_at": None,
                "last_verified_telemetry_at": None,
            }
        )
        token_b = format_bearer_token(cred_id_b, secret_b)

        for _ in range(60):
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(),
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert resp.status_code == 200

        # Credential A's budget is now exhausted...
        exhausted = client.post(
            "/api/v1/telemetry/otlp/v1/metrics", json=_histogram_payload(), headers={"Authorization": f"Bearer {token_a}"}
        )
        assert exhausted.status_code == 429

        # ...but credential B, a different, equally-legitimate
        # credential, is completely unaffected.
        unaffected = client.post(
            "/api/v1/telemetry/otlp/v1/metrics", json=_histogram_payload(), headers={"Authorization": f"Bearer {token_b}"}
        )
        assert unaffected.status_code == 200
    finally:
        _clear()


def test_elevated_error_rate_produces_a_real_tenant_scoped_incident(client):
    services, credentials, telemetry, incidents = _use()
    try:
        token = _active_credential(services, credentials)
        now = datetime.now(UTC)
        for i in range(4):
            # Explicit, distinct timestamps -- item 5's new dedup must
            # never merge 4 genuinely distinct observations into fewer
            # than 4 just because two calls happened to land in the
            # same microsecond. Offsets are into the PAST (never the
            # future) relative to `now` captured before the loop --
            # the detector's own window check compares each point's
            # `observed_at` against the REAL wall-clock "now" at the
            # moment each request is handled, which is always >= this
            # captured `now`; a future-dated point would otherwise be
            # excluded from the detector's own window and undercount
            # window_request_count below MIN_REQUESTS_FOR_EVALUATION.
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(status_code=500, when=now - timedelta(seconds=(3 - i))),
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
        assert len(incidents.rows) == 1
        assert str(incidents.rows[0]["organization_id"]) == str(ORG_A)
        assert incidents.rows[0]["source"] == "otel-telemetry"
        # REGRESSION: upsert_firing_incident does not commit itself
        # (see incident_repository.py's own docstring) -- a real,
        # PostgreSQL-backed run of this exact flow silently discarded
        # the incident until ingestion/telemetry_threshold_detector.py
        # was fixed to call repo.commit() explicitly. The in-memory
        # fake repository cannot by itself catch a missing commit (it
        # has no real transaction to roll back), so this assertion is
        # the one thing standing between a future regression here and
        # the same silent-no-incident bug recurring undetected by this
        # suite -- the real finding is documented in
        # docs/architecture/phase-16-secure-telemetry-onboarding.md.
        assert incidents.commit_count >= 1
    finally:
        _clear()


def test_healthy_traffic_never_creates_an_incident(client):
    services, credentials, telemetry, incidents = _use()
    try:
        token = _active_credential(services, credentials)
        now = datetime.now(UTC)
        for i in range(4):
            resp = client.post(
                "/api/v1/telemetry/otlp/v1/metrics",
                json=_histogram_payload(status_code=200, when=now - timedelta(seconds=(3 - i))),
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
        assert incidents.rows == []
    finally:
        _clear()


# --- Item 1: OTLP histogram temporality -----------------------------


def test_cumulative_temporality_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(aggregation_temporality=2),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400
    assert "DELTA" in response.json()["detail"]


def test_unspecified_temporality_is_rejected(client):
    """A metric that omits `aggregationTemporality` entirely (real
    clients always set it, but a malformed/legacy one might not) is
    treated exactly like UNSPECIFIED (0) -- rejected, never silently
    assumed to be the safe DELTA case."""
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(aggregation_temporality=None),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400
    assert "DELTA" in response.json()["detail"]


# --- Item 2: OTLP/HTTP response contract ------------------------------


def test_partial_success_response_reports_dropped_points_without_failing_the_batch(client):
    """One valid point + one stale (out-of-window) point in the SAME
    export: the batch is still accepted (HTTP 200, not 400 -- a real
    exporter would otherwise treat the whole export as a hard failure
    and may retry it forever), but the response's `partialSuccess`
    honestly reports that one point was dropped."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = _histogram_payload()
        stale = _histogram_payload(when=datetime.now(UTC) - timedelta(days=30))
        payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"].append(
            stale["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"][0]
        )
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        _clear()
    assert response.status_code == 200
    body = response.json()
    assert body["partialSuccess"]["rejectedDataPoints"] == "1"
    assert len(telemetry.rows) == 1


# --- Item 7: unit/count/sum validation --------------------------------


def test_unsupported_duration_unit_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(unit="minutes"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400
    assert "unit" in response.json()["detail"]


def test_missing_duration_unit_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(unit=None),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400


def test_millisecond_duration_unit_is_correctly_converted_to_seconds(client):
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(unit="ms", sum_seconds=50, count=1),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 200
    assert telemetry.rows[0]["duration_sum_seconds"] == 0.05


def test_count_exceeding_the_bound_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(count=10_000_000),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 422


def test_non_numeric_count_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = _histogram_payload()
        payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"][0]["count"] = "not-a-number"
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        _clear()
    assert response.status_code == 422


def _post_raw_json_with_literal_token(client, token: str, payload: dict, literal_replacement: tuple[str, str]):
    """httpx's own `json=` kwarg refuses to serialize a Python
    float('nan')/float('inf') at all (it raises before a request is
    even sent) -- a real adversarial client is under no such
    obligation and could send the literal (non-RFC-8259, but widely
    tolerated by lenient parsers including Python's own stdlib
    `json.loads`, which this endpoint's JSON path uses) `NaN`/
    `Infinity` token directly. This builds the request body as raw
    text with that literal substituted in, bypassing httpx's own
    client-side guard so the SERVER's own defense (`allow_inf_nan=False`
    on the Pydantic field) is what is actually being tested."""
    import json as _json

    placeholder, literal = literal_replacement
    body_text = _json.dumps(payload).replace(f'"{placeholder}"', literal)
    return client.post(
        "/api/v1/telemetry/otlp/v1/metrics",
        content=body_text.encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def test_nan_sum_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = _histogram_payload()
        payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"][0]["sum"] = "__NAN__"
        response = _post_raw_json_with_literal_token(client, token, payload, ("__NAN__", "NaN"))
    finally:
        _clear()
    assert response.status_code == 422


def test_infinite_sum_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        payload = _histogram_payload()
        payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"][0]["sum"] = "__INF__"
        response = _post_raw_json_with_literal_token(client, token, payload, ("__INF__", "Infinity"))
    finally:
        _clear()
    assert response.status_code == 422


def test_sum_exceeding_the_bound_is_rejected(client):
    services, credentials, _, _ = _use()
    try:
        token = _active_credential(services, credentials)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(sum_seconds=10_000_000.0),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 422


def test_inconsistent_start_after_end_timestamp_is_dropped_as_a_partial_rejection(client):
    """Item 7: a data point whose `startTimeUnixNano` is AFTER its own
    `timeUnixNano` describes an interval that ends before it starts --
    structurally inconsistent, dropped rather than stored as a
    nonsensical negative-duration interval."""
    services, credentials, telemetry, _ = _use()
    try:
        token = _active_credential(services, credentials)
        now = datetime.now(UTC)
        response = client.post(
            "/api/v1/telemetry/otlp/v1/metrics",
            json=_histogram_payload(when=now, start_when=now + timedelta(seconds=5)),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _clear()
    assert response.status_code == 400
    assert len(telemetry.rows) == 0
