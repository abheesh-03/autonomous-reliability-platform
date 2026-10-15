"""Real-database regression test for the dedicated, least-privileged
checkpoint database role (Phase 7 §DO NOT USE THE EXISTING RELIABILITY
DATABASE ROLE DIRECTLY): "Prove via a REAL PostgreSQL test that the
dedicated runtime role CAN use its own checkpoint schema/tables,
CANNOT SELECT/UPDATE reliability.incidents, CANNOT SELECT
reliability.retrieval_chunks, CANNOT mutate reliability.incident_events.
Fail closed if this privilege boundary is not actually true."

This connects directly AS the `agent_runtime` role itself (never the
POSTGRES_USER superuser) using psycopg -- the exact credential
agent-runtime-service's own real deployment uses (see config.py's
CheckpointDbSettings) -- so a real PostgreSQL permission denial is
what this test proves, never a mocked assumption about what GRANTs
exist.

Same deliberate, narrow exception to "never touch a real database" as
retrieval-service's tests/test_db_transaction.py: gracefully SKIPPED
when no real database/role is reachable (e.g. the Docker-isolated
`make agent-runtime-test` run, which has no postgres service linked
and no agent_runtime role provisioned), but FAILS outright (never
skips) when AGENT_RUNTIME_REQUIRE_REAL_DB=true -- used by CI's
dedicated real-database step, so this proof is actually enforced
there. Every object this test creates in its own `agent_runtime`
schema is cleaned up in a `finally` block; it never writes to
`reliability.*` at all (that is precisely the point being proven).
"""

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from agent_runtime_service.config import CheckpointDbSettings


def _require_real_db() -> bool:
    return os.environ.get("AGENT_RUNTIME_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


def _conn_string(user: str, password: str) -> str:
    # Phase 7 correction round (follow-up), finding #4: built via
    # psycopg's own `make_conninfo` -- the SAME safe conninfo builder
    # config.py's own CheckpointDbSettings.conn_string uses -- never a
    # naive f-string/URI. A naive build here could make THIS TEST fail
    # on a password containing a reserved URI character even though the
    # real application connection (which already uses make_conninfo)
    # works fine, which would be testing the wrong thing.
    host = os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    port = os.environ.get("AGENT_RUNTIME_DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))
    database = os.environ.get("POSTGRES_DB", "")
    return make_conninfo(user=user, password=password, host=host, port=port, dbname=database)


@pytest.fixture
async def agent_runtime_conn():
    password = os.environ.get("AGENT_RUNTIME_DB_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (password and database):
        _unavailable(
            "no real AGENT_RUNTIME_DB_PASSWORD/POSTGRES_DB configured -- skipping the real-database "
            "privilege-boundary regression test"
        )
    try:
        conn = await psycopg.AsyncConnection.connect(_conn_string("agent_runtime", password), autocommit=True)
    except Exception as exc:  # noqa: BLE001 -- connection failure means "skip" or "fail", decided by _unavailable
        _unavailable(f"could not connect as the real agent_runtime role: {exc}")
        return  # pragma: no cover -- _unavailable always raises

    yield conn
    await conn.close()


async def _expect_permission_denied(conn, sql: str) -> None:
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql)
    except psycopg.errors.InsufficientPrivilege:
        return
    else:
        pytest.fail(f"expected a permission-denied error for {sql!r}, but it succeeded")


async def test_agent_runtime_role_cannot_select_incidents(agent_runtime_conn):
    await _expect_permission_denied(agent_runtime_conn, "SELECT * FROM reliability.incidents LIMIT 1")


async def test_agent_runtime_role_cannot_update_incidents(agent_runtime_conn):
    await _expect_permission_denied(agent_runtime_conn, "UPDATE reliability.incidents SET title = title")


async def test_agent_runtime_role_cannot_select_retrieval_chunks(agent_runtime_conn):
    await _expect_permission_denied(agent_runtime_conn, "SELECT * FROM reliability.retrieval_chunks LIMIT 1")


async def test_agent_runtime_role_cannot_mutate_incident_events(agent_runtime_conn):
    await _expect_permission_denied(
        agent_runtime_conn, "UPDATE reliability.incident_events SET event_type = event_type"
    )
    await _expect_permission_denied(
        agent_runtime_conn, "DELETE FROM reliability.incident_events WHERE false"
    )
    # Phase 7 correction round (finding #13): the architecture doc
    # claims denial of INSERT/UPDATE/DELETE, but only UPDATE/DELETE
    # were ever actually tested here -- added for real completeness.
    # incident_id is a real column (NOT NULL, FK to reliability.incidents)
    # so this would need a real incident row to even reach a
    # not-null/FK violation; it never gets that far -- permission is
    # checked before any constraint, so this fails on the GRANT check
    # alone regardless of column values.
    await _expect_permission_denied(
        agent_runtime_conn,
        "INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, new_status) "
        "VALUES ('00000000-0000-0000-0000-000000000000', 'created', 'alertmanager', 'open')",
    )


def test_live_service_settings_use_the_same_role_this_file_connects_as():
    """Phase 7 correction round (finding #6): this file always connects
    AS the hardcoded 'agent_runtime' role -- this test proves the
    REAL, RUNNING service (via the exact same CheckpointDbSettings.from_env()
    main.py's lifespan calls) is configured to use that SAME role/schema,
    so the privilege-denial tests above are never a proof about a role
    the live service doesn't actually use. Requires the real env vars
    this CI step/local run already provides; skips (not fails) if they
    aren't set, consistent with every other test in this module."""
    password = os.environ.get("AGENT_RUNTIME_DB_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (password and database):
        _unavailable("no real AGENT_RUNTIME_DB_PASSWORD/POSTGRES_DB configured")
    settings = CheckpointDbSettings.from_env()
    assert settings.user == "agent_runtime"
    assert settings.schema == "agent_runtime"


async def test_agent_runtime_role_search_path_is_its_own_schema(agent_runtime_conn):
    async with agent_runtime_conn.cursor() as cur:
        await cur.execute("SHOW search_path")
        row = await cur.fetchone()
    assert row[0] == "agent_runtime"


async def test_agent_runtime_role_can_use_its_own_schema(agent_runtime_conn):
    """The CAN half of the boundary: real CREATE/INSERT/SELECT/DROP
    inside the role's own schema, using an unqualified table name (the
    same way LangGraph's own setup() creates its checkpoint tables) --
    proves the role is not simply denied everything, only
    reliability.*."""
    try:
        async with agent_runtime_conn.cursor() as cur:
            await cur.execute("CREATE TABLE IF NOT EXISTS privilege_boundary_probe (x INTEGER)")
            await cur.execute("INSERT INTO privilege_boundary_probe (x) VALUES (1)")
            await cur.execute("SELECT x FROM privilege_boundary_probe")
            row = await cur.fetchone()
            assert row[0] == 1
            await cur.execute(
                "SELECT table_schema FROM information_schema.tables WHERE table_name = 'privilege_boundary_probe'"
            )
            schema_row = await cur.fetchone()
            assert schema_row[0] == "agent_runtime"
    finally:
        async with agent_runtime_conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS privilege_boundary_probe")
