"""Liveness/readiness unit tests.

Readiness is exercised against a fake engine (never a real database —
see conftest.py's module docstring for why that's intentional): the
fake stands in at the same "engine" boundary main.py's lifespan uses,
so these tests prove the readiness handler's own logic (translate a
connection failure into 503 without leaking it; report 200 when the
query succeeds) without needing a live PostgreSQL. The real
200-when-actually-ready and 503-during-a-real-restart cases are proven
by scripts/verify-control-plane.sh against the real stack — that is
the acceptance-level proof, not these.
"""


class _FakeConnection:
    async def execute(self, *args, **kwargs):
        return None


class _FakeConnectCM:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, *exc_info):
        return False


class _FakeEngineReady:
    def connect(self):
        return _FakeConnectCM(_FakeConnection())


class _FakeEngineBroken:
    def connect(self):
        raise RuntimeError("simulated connection failure: host unreachable, password=supersecret")


def test_liveness_returns_200_without_database(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}


def test_readiness_returns_200_when_database_reachable(client):
    client.app.state.db_engine = _FakeEngineReady()

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_503_when_database_unavailable(client):
    client.app.state.db_engine = _FakeEngineBroken()

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "unavailable"}
    # The underlying exception message (which could contain connection
    # details) must never reach the HTTP response body.
    assert "supersecret" not in response.text
    assert "unreachable" not in response.text
