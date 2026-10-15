"""Real PostgreSQL + REAL AsyncConnectionPool recovery proof (Phase 7,
post-commit fix for GitHub Actions run #33).

CI #33's own failure: Phase 3E's existing acceptance behavior
(`docker compose restart postgres`, proving audit durability --
unrelated to Phase 7, never reopened or modified here) killed
agent-runtime-service's then-single, process-lifetime checkpoint
connection. `/health/live` correctly never depends on PostgreSQL, so
the process stayed "alive"; but `/health/ready` failed forever
afterward (`psycopg.errors.AdminShutdown: terminating connection due
to administrator command`), recoverable only by restarting
agent-runtime-service itself -- not an acceptable resilience story for
a "durable" runtime.

This test proves the FIX: CheckpointStore now owns a small
`psycopg_pool.AsyncConnectionPool` (see checkpointer.py's own
docstring for why this is real, upstream-supported
`AsyncPostgresSaver` usage, confirmed against its installed source,
not a hack). It proves the SAME CheckpointStore object -- never
recreated, never a new Python process -- recovers readiness after a
real connection-killing event, with pre-existing checkpoint data still
readable and a new checkpoint still writable afterward.

Connection-killing mechanism: `pg_terminate_backend` against the real
`agent_runtime` role's own live backend PID(s), from a separate real
admin connection (the existing `POSTGRES_USER` superuser -- never the
least-privileged `agent_runtime` role itself, which has no privilege
to terminate any backend). This is a real PostgreSQL "backend
restart" in PostgreSQL's own terminology -- one of the two mechanisms
this fix's own requirements explicitly name (the other, a full
`docker compose restart postgres`, is deliberately avoided here so
this test never disrupts other tests/services sharing the same CI
PostgreSQL instance) -- and empirically reproduces the EXACT
`AdminShutdown` error CI #33 hit, on the very next use of that
connection.

Real-database-gated exactly like test_db_privilege_boundary.py /
test_checkpoint_durability.py: gracefully SKIPPED when no real
database/role is reachable, FAILS outright (never skips) when
AGENT_RUNTIME_REQUIRE_REAL_DB=true.
"""

import asyncio
import os
import uuid

import psycopg
import pytest
from langgraph.checkpoint.base.id import uuid6

from agent_runtime_service.checkpointer import CheckpointStore
from agent_runtime_service.config import CheckpointDbSettings

# LangGraph's own checkpoint ids are NOT plain random UUID4s -- they
# are lexically time-sortable (uuid6-style) so that "the latest
# checkpoint for this thread" can be resolved with a simple
# `ORDER BY checkpoint_id DESC` (confirmed directly against the real
# installed langgraph-checkpoint source). A plain `uuid.uuid4()` has no
# such ordering guarantee, so this test uses the SAME id scheme
# LangGraph itself uses -- not just for this test to pass, but because
# it is the realistic, correct way to construct a checkpoint id at all.


def _require_real_db() -> bool:
    return os.environ.get("AGENT_RUNTIME_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


def _admin_conn_kwargs() -> dict:
    return {
        "user": os.environ.get("POSTGRES_USER", ""),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "host": os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
        "port": os.environ.get("AGENT_RUNTIME_DB_PORT", os.environ.get("POSTGRES_PORT", "5432")),
        "dbname": os.environ.get("POSTGRES_DB", ""),
    }


async def _kill_agent_runtime_backends() -> int:
    """Connects as the real superuser and terminates every live backend
    currently connected as the dedicated `agent_runtime` role. Returns
    the number of backends killed."""
    admin = _admin_conn_kwargs()
    conn = await psycopg.AsyncConnection.connect(
        f"postgresql://{admin['user']}:{admin['password']}@{admin['host']}:{admin['port']}/{admin['dbname']}",
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT pid FROM pg_stat_activity WHERE usename = 'agent_runtime'")
            pids = [row[0] async for row in cur]
            for pid in pids:
                await cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
        return len(pids)
    finally:
        await conn.close()


@pytest.fixture
async def checkpoint_store():
    password = os.environ.get("AGENT_RUNTIME_DB_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "")
    admin_user = os.environ.get("POSTGRES_USER", "")
    admin_password = os.environ.get("POSTGRES_PASSWORD", "")
    if not (password and database and admin_user and admin_password):
        _unavailable(
            "no real AGENT_RUNTIME_DB_PASSWORD/POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB configured -- "
            "skipping the real checkpoint-pool recovery test"
        )
    settings = CheckpointDbSettings(
        host=os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
        port=int(os.environ.get("AGENT_RUNTIME_DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))),
        user="agent_runtime",
        password=password,
        database=database,
        schema="agent_runtime",
        # Deliberately tiny for this test -- min_size=1 guarantees a
        # real backend exists to kill immediately after open(); a
        # bigger pool would just mean killing more PIDs for the same
        # proof.
        pool_min_size=1,
        pool_max_size=2,
        pool_open_timeout_seconds=10.0,
    )
    store = CheckpointStore(settings)
    try:
        await store.open()
    except Exception as exc:  # noqa: BLE001 -- connection failure means "skip" or "fail", decided by _unavailable
        _unavailable(f"could not open a real checkpoint pool: {exc}")
        return  # pragma: no cover -- _unavailable always raises

    yield store
    await store.close()


async def test_checkpoint_store_pool_recovers_after_real_backend_termination(checkpoint_store):
    # 1/2/3: real pool is open; real checkpoint state is accessible.
    assert await checkpoint_store.ping() is True

    identity = await checkpoint_store.identity()
    assert identity == {
        "current_user": "agent_runtime",
        "current_schema": "agent_runtime",
        "search_path": "agent_runtime",
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_before = {
        "v": 1,
        "ts": "2026-01-01T00:00:00+00:00",
        "id": str(uuid6()),
        "channel_values": {"probe": "before-kill"},
        "channel_versions": {},
        "versions_seen": {},
    }
    await checkpoint_store.saver.aput(
        config, checkpoint_before, {"source": "update", "step": 1, "writes": {}, "parents": {}}, {}
    )
    tup_before = await checkpoint_store.saver.aget_tuple(config)
    assert tup_before is not None
    assert tup_before.checkpoint["channel_values"]["probe"] == "before-kill"

    # 4: confirm readiness genuinely works before the kill.
    assert await checkpoint_store.ping() is True

    # 5/6: cause the underlying connection(s) to become invalid via a
    # REAL PostgreSQL backend termination -- the exact mechanism this
    # fix's own requirements name, reproducing CI #33's AdminShutdown.
    killed = await _kill_agent_runtime_backends()
    assert killed >= 1, "expected at least one live agent_runtime backend to terminate -- is the pool actually open?"

    # 7: nothing was "stopped" (only a backend was killed), so there is
    # nothing separate to "restore" here -- the pool itself must detect
    # and replace the now-dead connection on its own.

    # 8/9: never recreate CheckpointStore; never touch the Python
    # process/runtime. `checkpoint_store` is the exact same object,
    # with the exact same pool, for the rest of this test.

    # 10: bounded retry. Empirically confirmed before this test was
    # written: the FIRST checkout after the kill surfaces the stale
    # connection's own failure once; psycopg_pool discards it and the
    # very next checkout succeeds with a fresh, healthy connection.
    # ping() already treats a failure as "not ready" rather than
    # raising, so this loop is bounded polling for that recovery.
    recovered = False
    for _attempt in range(10):
        if await checkpoint_store.ping():
            recovered = True
            break
        await asyncio.sleep(1)
    assert recovered, "the SAME CheckpointStore/pool never recovered readiness after its backend was terminated"

    recovered_identity = await checkpoint_store.identity()
    assert recovered_identity == identity, "the recovered connection must still be the dedicated agent_runtime identity"

    # 11: pre-existing checkpoint data is still readable, via the SAME
    # CheckpointStore/saver, after recovery.
    tup_after_recovery = await checkpoint_store.saver.aget_tuple(config)
    assert tup_after_recovery is not None
    assert tup_after_recovery.checkpoint["channel_values"]["probe"] == "before-kill"

    # 12: a NEW checkpoint can be written afterward, via the SAME
    # CheckpointStore/saver.
    checkpoint_after = {
        "v": 1,
        "ts": "2026-01-01T00:05:00+00:00",
        "id": str(uuid6()),
        "channel_values": {"probe": "after-recovery"},
        "channel_versions": {},
        "versions_seen": {},
    }
    await checkpoint_store.saver.aput(
        config, checkpoint_after, {"source": "update", "step": 2, "writes": {}, "parents": {}}, {}
    )
    tup_final = await checkpoint_store.saver.aget_tuple(config)
    assert tup_final is not None
    assert tup_final.checkpoint["channel_values"]["probe"] == "after-recovery"
