"""REAL PostgreSQL + REAL LangGraph checkpoint durability proof (Phase
7 §CHECKPOINT DURABILITY PROOF). Not mocked: a real `AsyncPostgresSaver`
against the real running Postgres, using THIS service's own real
`build_graph`/`AgentGraphState`/node wiring (never a throwaway toy
graph) -- only the two external HTTP clients are fake doubles (the
same seam-based convention every test in this platform already uses;
LangGraph/PostgreSQL themselves are never mocked here).

Scope, precisely (correction round follow-up, finding #5C -- an
earlier version of this docstring overclaimed what this specific test
proves): this is a single Python test process/interpreter. "Instance
A" and "instance B" are two separate `CheckpointStore`/`AsyncPostgresSaver`
connections, two separate compiled graphs, and two separate sets of
fake client objects, created one after the other and connected via
`del` in between -- never a second OS process, never a second
container. What this proves is that LangGraph's own real PostgreSQL
checkpoint state (not Python object identity, not an in-memory cache)
is the sole source of instance B's knowledge of the thread's prior
progress. The REAL separate-process/container restart proof --
actually stopping and restarting the `agent-runtime-service` container
while a run is incomplete -- is `scripts/verify-agent-runtime.sh`
(section 9), not this test.

Proves, in order (Phase 7's own enumerated steps):
  1. runtime instance A (a real AsyncPostgresSaver connection + a real
     compiled graph) is created.
  2. a unique run/thread UUID is used.
  3. the graph executes far enough to create real checkpoints
     (load_incident succeeds and durably commits).
  4. a controlled failure is injected in run_investigation -- a raw,
     UNCLASSIFIED exception (`RuntimeError`) the node does NOT catch.
     This is deliberately NOT `InvestigatorUnavailableError`: that
     specific exception type is itself now one of the TWO
     TRANSIENT/RETRYABLE failure modes graph/nodes.py leaves
     deliberately uncaught (Phase 7 correction round, finding #3) --
     it is translated into a safe `503` only at the API layer
     (api/agent_runs.py), never into a persisted "failed" terminal
     state, and uses this exact same durable-checkpoint-resume
     mechanism (see tests/test_graph.py's own dedicated tests for that
     specific exception type). A raw, UNCLASSIFIED `RuntimeError` is
     used here instead because it simulates a genuine, unexpected
     process/node crash -- a condition with no narrower classification
     at all -- which is the scenario this specific test is named for.
  5. runtime instance A is destroyed (its connection closed, its
     Python objects go out of scope entirely).
  6. a completely NEW runtime instance B is created -- a brand new
     AsyncPostgresSaver connection, a brand new compiled graph, brand
     new fake client objects -- using the SAME PostgreSQL database and
     the SAME thread_id, within this SAME test process.
  7. instance B resumes that same thread.
  8. prior successful progress (load_incident's own result) is
     recovered from the durable checkpoint, NOT re-executed -- proven
     by asserting the fake control-plane client was called exactly
     ONCE in total, only by instance A, never again by instance B.
  9. the graph reaches a real completed state.
  10. completed_nodes/incident_snapshot are only ever present because
      they were read back from Postgres by instance B (instance A's
      own in-memory Python objects/closures cannot possibly be what
      instance B is reading, since they are different objects in a
      different call to build_graph with different fake client
      instances entirely, even though both exist in the same
      interpreter).
"""

import uuid

import pytest

from agent_runtime_service.checkpointer import CheckpointStore
from agent_runtime_service.config import CheckpointDbSettings, RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json


def _require_real_db() -> bool:
    import os

    return os.environ.get("AGENT_RUNTIME_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


class FakeControlPlaneClient:
    """Succeeds every time -- this test's failure is injected in
    run_investigation, not here, so this node's own real durability
    (completing once, never re-executing) is exactly what's proven."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_incident(self, incident_id):
        self.calls += 1
        return IncidentSnapshot.model_validate(incident_json(incident_id=uuid.UUID(incident_id)))


class CrashingThenSucceedingInvestigatorClient:
    """Instance A's own client: raises an UNCLASSIFIED exception on
    its first call -- simulating a real process crash mid-node, not a
    classified "service unavailable" business outcome."""

    def __init__(self) -> None:
        self.calls = 0

    async def investigate(self, incident_id):
        self.calls += 1
        raise RuntimeError("simulated crash in run_investigation (test-only failure injection)")


class SucceedingInvestigatorClient:
    """Instance B's own, entirely separate client object -- used only
    after the simulated crash, standing in for 'whatever was broken is
    now fixed' on resume."""

    def __init__(self) -> None:
        self.calls = 0

    async def investigate(self, incident_id):
        self.calls += 1
        return InvestigationReport.model_validate(investigation_report_json(incident_id=uuid.UUID(incident_id)))


@pytest.fixture
async def db_settings():
    import os

    password = os.environ.get("POSTGRES_PASSWORD", "")
    user = os.environ.get("POSTGRES_USER", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (password and user and database):
        _unavailable(
            "no real POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB configured -- skipping the real "
            "PostgreSQL checkpoint durability test"
        )
    # Deliberately uses the REAL checkpoint role/schema
    # (AGENT_RUNTIME_DB_USER/PASSWORD) when available -- falling back
    # to a distinctly-named schema under the superuser role only keeps
    # this test runnable before scripts/init-agent-runtime-db.sh has
    # ever been run locally; CI's dedicated real-database step always
    # has the real role provisioned by that point (see
    # docs/architecture/phase-7-durable-agent-runtime.md).
    runtime_user = os.environ.get("AGENT_RUNTIME_DB_USER", "")
    runtime_password = os.environ.get("AGENT_RUNTIME_DB_PASSWORD", "")
    if runtime_user and runtime_password:
        settings = CheckpointDbSettings(
            host=os.environ.get("AGENT_RUNTIME_DB_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")),
            port=int(os.environ.get("AGENT_RUNTIME_DB_PORT", "5432")),
            user=runtime_user,
            password=runtime_password,
            database=database,
            schema="agent_runtime",
            pool_min_size=1,
            pool_max_size=4,
            pool_open_timeout_seconds=10.0,
        )
    else:
        _unavailable(
            "no real AGENT_RUNTIME_DB_USER/AGENT_RUNTIME_DB_PASSWORD configured -- skipping the real "
            "PostgreSQL checkpoint durability test (run scripts/init-agent-runtime-db.sh against the "
            "real stack first)"
        )
        return  # pragma: no cover

    try:
        probe = CheckpointStore(settings)
        await probe.open()
        await probe.close()
    except Exception as exc:  # noqa: BLE001
        _unavailable(f"real checkpoint database not reachable: {exc}")

    return settings


async def test_real_checkpoint_survives_process_destruction_and_resumes_correctly(db_settings):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    bounds = RuntimeBounds(
        max_history_items=50,
        max_error_detail_chars=300,
        max_incident_text_chars=2000,
        max_investigation_report_bytes=524_288,
    )

    # --- Instance A: runs, crashes mid run_investigation ---
    control_plane_a = FakeControlPlaneClient()
    investigator_a = CrashingThenSucceedingInvestigatorClient()
    store_a = CheckpointStore(db_settings)
    saver_a = await store_a.open()
    graph_a = compile_graph(control_plane_a, investigator_a, bounds, saver_a)

    initial_state = {
        "run_id": thread_id,
        "incident_id": str(SAMPLE_INCIDENT_ID),
        "status": "running",
        "started_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }

    with pytest.raises(RuntimeError, match="simulated crash"):
        await graph_a.ainvoke(initial_state, config=config, durability="sync")

    snap_after_crash = await graph_a.aget_state(config)
    assert snap_after_crash.next == ("run_investigation",)
    assert snap_after_crash.values["completed_nodes"] == ["load_incident"]
    assert snap_after_crash.values["incident_snapshot"] is not None
    assert control_plane_a.calls == 1
    assert investigator_a.calls == 1

    # --- Destroy instance A completely ---
    await store_a.close()
    del store_a, saver_a, graph_a, control_plane_a, investigator_a

    # --- Instance B: brand new connection, brand new graph, brand new
    # fake clients, SAME thread_id, SAME real PostgreSQL database ---
    control_plane_b = FakeControlPlaneClient()
    investigator_b = SucceedingInvestigatorClient()
    store_b = CheckpointStore(db_settings)
    saver_b = await store_b.open()
    graph_b = compile_graph(control_plane_b, investigator_b, bounds, saver_b)

    snap_before_resume = await graph_b.aget_state(config)
    # Instance B can only know this from durable Postgres state --
    # control_plane_b/investigator_b have never been called yet, and
    # these are entirely different Python objects (a different
    # CheckpointStore, saver, graph, and fake clients) than instance A
    # used, within this same test process -- see the module docstring
    # for exactly what this does and does not prove.
    assert snap_before_resume.next == ("run_investigation",)
    assert snap_before_resume.values["completed_nodes"] == ["load_incident"]

    result = await graph_b.ainvoke(None, config=config, durability="sync")

    assert result["status"] == "completed"
    assert result["completed_nodes"] == ["load_incident", "run_investigation", "evaluate_investigation", "finalize"]
    assert result["result_quality"] in ("well_supported", "inconclusive", "partial")

    # load_incident was NEVER re-executed by instance B -- its result
    # was recovered from the durable checkpoint, not recomputed.
    assert control_plane_b.calls == 0
    # run_investigation genuinely ran again on resume (at-least-once,
    # Phase 7's own documented, honest semantics) -- exactly once here.
    assert investigator_b.calls == 1

    final_snap = await graph_b.aget_state(config)
    assert final_snap.next == ()

    # --- Idempotency: resuming an already-completed thread is a safe
    # no-op, never re-executes anything ---
    result_again = await graph_b.ainvoke(None, config=config, durability="sync")
    assert result_again == result
    assert investigator_b.calls == 1  # unchanged

    await store_b.close()
