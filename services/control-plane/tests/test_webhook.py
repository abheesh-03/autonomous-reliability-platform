"""Unit tests for POST /internal/v1/alertmanager/webhook (Phase 3C).

Like test_incidents.py, these use the in-memory FakeIncidentRepository
(conftest.py) via FastAPI's dependency_overrides — no real database.
Real PostgreSQL atomic-upsert/deduplication behavior is proven
separately by scripts/verify-webhook-ingestion.sh; see that script's
and conftest.FakeIncidentRepository's own docstrings. These tests
exist to prove the route/validation/auth/mapping layer behaves
correctly in isolation.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError

from control_plane.api.webhook_limits import MAX_WEBHOOK_BODY_BYTES

from control_plane.api.dependencies import get_incident_repository
from control_plane.main import app
from tests.conftest import WEBHOOK_TOKEN, make_incident_row

WEBHOOK_URL = "/internal/v1/alertmanager/webhook"
AUTH_HEADERS = {"Authorization": f"Bearer {WEBHOOK_TOKEN}"}


def _alert(**overrides) -> dict:
    now = datetime.now(UTC).isoformat()
    alert = {
        "status": "firing",
        "labels": {"alertname": "TelemetryPipelineUnavailable", "severity": "critical"},
        "annotations": {"summary": "OTel Collector scrape target is down", "description": "detailed text"},
        "startsAt": now,
        "fingerprint": "fp-abc123",
    }
    alert.update(overrides)
    return alert


def _payload(*alerts: dict, status: str = "firing") -> dict:
    return {
        "version": "4",
        "groupKey": "{}:{alertname=...}",
        "status": status,
        "receiver": "control-plane-webhook",
        "alerts": list(alerts) or [_alert()],
    }


def test_valid_authenticated_firing_payload_creates_incident(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 200
    body = response.json()
    assert body == {"firing_processed": 1, "resolved_ignored": 0, "incidents_created": 1, "incidents_updated": 0}
    assert len(repo.rows) == 1
    assert repo.rows[0]["source"] == "alertmanager"
    assert repo.rows[0]["source_fingerprint"] == "fp-abc123"
    assert repo.rows[0]["status"] == "open"
    assert repo.rows[0]["resolved_at"] is None


def test_missing_bearer_token_returns_401(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, json=_payload(_alert()))

    assert response.status_code == 401
    assert repo.rows == []


def test_incorrect_bearer_token_returns_401(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, headers={"Authorization": "Bearer wrong-token"}, json=_payload(_alert()))

    assert response.status_code == 401
    assert repo.rows == []


def test_malformed_payload_returns_422(use_repository, client):
    use_repository([])

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json={"not": "a valid alertmanager payload"})

    assert response.status_code == 422


def test_missing_required_label_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(labels={"severity": "critical"})  # no alertname

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_unsupported_severity_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(labels={"alertname": "X", "severity": "catastrophic"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_invalid_fingerprint_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(fingerprint="   ")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_invalid_timestamp_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(startsAt="not-a-timestamp")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_empty_alert_batch_returns_422(use_repository, client):
    use_repository([])

    body = _payload()
    body["alerts"] = []
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=body)

    assert response.status_code == 422


def test_multi_alert_notification_creates_distinct_incidents(use_repository, client):
    repo = use_repository([])

    alert_a = _alert(fingerprint="fp-a")
    alert_b = _alert(fingerprint="fp-b")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert_a, alert_b))

    assert response.status_code == 200
    body = response.json()
    assert body["firing_processed"] == 2
    assert body["incidents_created"] == 2
    fingerprints = {row["source_fingerprint"] for row in repo.rows}
    assert fingerprints == {"fp-a", "fp-b"}


def test_mixed_firing_and_resolved_notification(use_repository, client):
    repo = use_repository([])

    firing = _alert(fingerprint="fp-firing")
    resolved = _alert(fingerprint="fp-resolved", status="resolved", labels={"alertname": "X"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(firing, resolved, status="firing"))

    assert response.status_code == 200
    body = response.json()
    assert body == {"firing_processed": 1, "resolved_ignored": 1, "incidents_created": 1, "incidents_updated": 0}
    assert len(repo.rows) == 1
    assert repo.rows[0]["source_fingerprint"] == "fp-firing"


def test_resolved_only_notification_creates_no_incident(use_repository, client):
    repo = use_repository([])

    resolved = _alert(fingerprint="fp-resolved-only", status="resolved", labels={"alertname": "X"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body == {"firing_processed": 0, "resolved_ignored": 1, "incidents_created": 0, "incidents_updated": 0}
    assert repo.rows == []


def test_summary_and_description_mapping(use_repository, client):
    repo = use_repository([])

    alert = _alert(annotations={"summary": "Custom summary text", "description": "Custom description text"})

    client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert repo.rows[0]["title"] == "Custom summary text"
    assert repo.rows[0]["description"] == "Custom description text"


def test_safe_title_fallback_to_alertname(use_repository, client):
    repo = use_repository([])

    alert = _alert(annotations={}, labels={"alertname": "FallbackAlertName", "severity": "warning"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    assert repo.rows[0]["title"] == "FallbackAlertName"
    assert repo.rows[0]["description"] is None


def test_duplicate_firing_preserves_incident_identity(use_repository, client):
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-dup",
        status="acknowledged",
        first_seen_at=datetime.now(UTC) - timedelta(hours=1),
    )
    repo = use_repository([existing])

    alert = _alert(fingerprint="fp-dup")
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body == {"firing_processed": 1, "resolved_ignored": 0, "incidents_created": 0, "incidents_updated": 1}
    assert len(repo.rows) == 1
    assert repo.rows[0]["id"] == existing["id"]
    assert repo.rows[0]["first_seen_at"] == existing["first_seen_at"]
    # Status is preserved, not reset to "open".
    assert repo.rows[0]["status"] == "acknowledged"


def test_database_error_during_ingestion_returns_503_not_success(use_repository, client):
    class _BrokenRepository:
        async def upsert_firing_incident(self, **kwargs):
            raise OperationalError("INSERT ...", {}, Exception("connection refused, password=supersecret"))

        async def commit(self):
            raise AssertionError("commit() must never be reached if upsert_firing_incident raised")

    app.dependency_overrides[get_incident_repository] = lambda: _BrokenRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "supersecret" not in response.text


def test_database_outage_produces_503(use_repository, client):
    class _OutageRepository:
        async def upsert_firing_incident(self, **kwargs):
            raise OperationalError("INSERT ...", {}, Exception("could not connect to server"))

        async def commit(self):
            raise AssertionError("commit() must never be reached after a connection failure")

    app.dependency_overrides[get_incident_repository] = lambda: _OutageRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503


def test_dns_resolution_failure_also_produces_503(use_repository, client):
    # A real integration run (scripts/verify-webhook-ingestion.sh,
    # section 9) found that fully stopping PostgreSQL can surface as a
    # raw socket.gaierror from asyncpg, never wrapped into a
    # SQLAlchemyError — main.py registers a second handler
    # (OSError -> 503) specifically so this still returns 503, not an
    # unhandled 500. This test reproduces that at the unit level.
    class _DnsFailureRepository:
        async def upsert_firing_incident(self, **kwargs):
            import socket

            raise socket.gaierror("[Errno -2] Name or service not known")

        async def commit(self):
            raise AssertionError("commit() must never be reached after a connection failure")

    app.dependency_overrides[get_incident_repository] = lambda: _DnsFailureRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}


def test_no_secrets_in_auth_error_responses(use_repository, client):
    use_repository([])

    missing = client.post(WEBHOOK_URL, json=_payload(_alert()))
    wrong = client.post(WEBHOOK_URL, headers={"Authorization": "Bearer wrong-token"}, json=_payload(_alert()))

    for response in (missing, wrong):
        assert response.status_code == 401
        assert WEBHOOK_TOKEN not in response.text


def test_unconfigured_server_secret_fails_closed(use_repository, client):
    use_repository([])
    original = app.state.webhook_token
    app.state.webhook_token = None
    try:
        response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))
        assert response.status_code == 401
    finally:
        app.state.webhook_token = original


def test_oversized_body_returns_413(use_repository, client):
    repo = use_repository([])

    oversized = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        content=oversized,
    )

    assert response.status_code == 413
    assert repo.rows == []
    assert WEBHOOK_TOKEN not in response.text


def test_oversized_body_with_understated_content_length_still_returns_413(use_repository, client):
    # The real byte-count enforcement (not just the Content-Length
    # header) is what must catch this — a client could omit the header
    # entirely (chunked transfer-encoding) or simply lie about it.
    repo = use_repository([])

    oversized = b"y" * (MAX_WEBHOOK_BODY_BYTES + 1)
    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json", "Content-Length": "10"},
        content=oversized,
    )

    assert response.status_code == 413
    assert repo.rows == []


def test_body_at_the_size_limit_is_not_rejected_for_size(use_repository, client):
    # A payload AT the byte limit must not be rejected by the size
    # guard itself — it may still fail Pydantic validation (expected,
    # since this specific oversized-but-well-formed-looking body isn't
    # a real alert payload), but that must surface as 422, not 413.
    use_repository([])

    body = b'{"padding": "' + b"z" * (MAX_WEBHOOK_BODY_BYTES - 20) + b'"}'
    assert len(body) <= MAX_WEBHOOK_BODY_BYTES

    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        content=body,
    )

    assert response.status_code != 413
