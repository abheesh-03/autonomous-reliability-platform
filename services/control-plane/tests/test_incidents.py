import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError

from control_plane.api.dependencies import get_incident_repository
from control_plane.main import app
from tests.conftest import make_incident_row


def test_valid_incident_serialization(use_repository, client):
    row = make_incident_row(
        title="Checkout latency high",
        description="p95 above threshold",
        severity="critical",
        status="investigating",
    )
    use_repository([row])

    response = client.get(f"/api/v1/incidents/{row['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(row["id"])
    assert body["title"] == "Checkout latency high"
    assert body["description"] == "p95 above threshold"
    assert body["severity"] == "critical"
    assert body["status"] == "investigating"
    assert body["resolved_at"] is None
    # Timestamps serialize as ISO 8601 strings that round-trip.
    datetime.fromisoformat(body["first_seen_at"])
    datetime.fromisoformat(body["last_seen_at"])
    datetime.fromisoformat(body["created_at"])
    datetime.fromisoformat(body["updated_at"])


def test_empty_incident_collection(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents")

    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_pagination(use_repository, client):
    now = datetime.now(UTC)
    rows = [
        make_incident_row(last_seen_at=now - timedelta(minutes=i), title=f"incident-{i}")
        for i in range(5)
    ]
    use_repository(rows)

    response = client.get("/api/v1/incidents", params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2


def test_status_filtering(use_repository, client):
    open_row = make_incident_row(status="open")
    resolved_row = make_incident_row(status="resolved", resolved_at=datetime.now(UTC))
    use_repository([open_row, resolved_row])

    response = client.get("/api/v1/incidents", params={"status": "resolved"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(resolved_row["id"])


def test_severity_filtering(use_repository, client):
    critical_row = make_incident_row(severity="critical")
    info_row = make_incident_row(severity="info")
    use_repository([critical_row, info_row])

    response = client.get("/api/v1/incidents", params={"severity": "critical"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(critical_row["id"])


def test_source_filtering(use_repository, client):
    am_row = make_incident_row(source="alertmanager")
    other_row = make_incident_row(source="synthetic-check")
    use_repository([am_row, other_row])

    response = client.get("/api/v1/incidents", params={"source": "synthetic-check"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(other_row["id"])


def test_deterministic_ordering(use_repository, client):
    now = datetime.now(UTC)
    # Pre-sorted last_seen_at DESC, id DESC, matching what the real
    # repository's ORDER BY produces — the fake repository does not
    # re-sort, so this also proves the route returns rows in whatever
    # order the repository already provides, unmodified.
    newest = make_incident_row(last_seen_at=now)
    middle = make_incident_row(last_seen_at=now - timedelta(minutes=1))
    oldest = make_incident_row(last_seen_at=now - timedelta(minutes=2))
    use_repository([newest, middle, oldest])

    response = client.get("/api/v1/incidents")

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(newest["id"]), str(middle["id"]), str(oldest["id"])]


def test_incident_lookup_by_uuid(use_repository, client):
    row = make_incident_row()
    other = make_incident_row()
    use_repository([row, other])

    response = client.get(f"/api/v1/incidents/{row['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == str(row["id"])


def test_missing_incident_returns_404(use_repository, client):
    use_repository([])

    response = client.get(f"/api/v1/incidents/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "incident not found"}


def test_malformed_uuid_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents/not-a-uuid")

    assert response.status_code == 422


def test_invalid_pagination_limit_too_high_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents", params={"limit": 101})

    assert response.status_code == 422


def test_invalid_pagination_limit_too_low_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents", params={"limit": 0})

    assert response.status_code == 422


def test_invalid_pagination_negative_offset_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents", params={"offset": -1})

    assert response.status_code == 422


def test_invalid_status_filter_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents", params={"status": "triaging"})

    assert response.status_code == 422


def test_invalid_severity_filter_returns_422(use_repository, client):
    use_repository([])

    response = client.get("/api/v1/incidents", params={"severity": "catastrophic"})

    assert response.status_code == 422


def test_database_unavailable_returns_503_for_list(client):
    class _BrokenRepository:
        async def list_incidents(self, **kwargs):
            raise OperationalError("SELECT ...", {}, Exception("connection refused, password=supersecret"))

        async def get_by_id(self, incident_id):
            raise OperationalError("SELECT ...", {}, Exception("connection refused, password=supersecret"))

    app.dependency_overrides[get_incident_repository] = lambda: _BrokenRepository()

    response = client.get("/api/v1/incidents")

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "supersecret" not in response.text


def test_database_unavailable_returns_503_for_detail(client):
    class _BrokenRepository:
        async def list_incidents(self, **kwargs):
            raise OperationalError("SELECT ...", {}, Exception("connection refused, password=supersecret"))

        async def get_by_id(self, incident_id):
            raise OperationalError("SELECT ...", {}, Exception("connection refused, password=supersecret"))

    app.dependency_overrides[get_incident_repository] = lambda: _BrokenRepository()

    response = client.get(f"/api/v1/incidents/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "supersecret" not in response.text
