"""Graph-level tests -- real `build_graph`/node wiring, real LangGraph
`StateGraph` semantics, but `InMemorySaver` (Phase 7 §LANGGRAPH:
"InMemorySaver may be used only in focused unit tests where
persistence is not under test" -- persistence itself is proven for
real in test_checkpoint_durability.py, not here). Fake
control-plane/investigator client doubles -- never a mocked httpx/
LangGraph internal.
"""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START

from agent_runtime_service.clients.control_plane import (
    ControlPlaneOutputError,
    ControlPlaneUnavailableError,
    IncidentNotFoundError,
)
from agent_runtime_service.clients.investigator import InvestigatorOutputError, InvestigatorUnavailableError
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.build import compile_graph
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json, investigation_report_json

BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)


class FakeControlPlaneClient:
    def __init__(self, *, raise_=None, incident_overrides=None):
        self._raise = raise_
        self._incident_overrides = incident_overrides or {}
        self.calls = 0

    async def get_incident(self, incident_id):
        self.calls += 1
        if self._raise:
            raise self._raise
        return IncidentSnapshot.model_validate(
            incident_json(incident_id=uuid.UUID(incident_id), **self._incident_overrides)
        )


class FakeInvestigatorClient:
    def __init__(self, *, raise_=None, report_overrides=None):
        self._raise = raise_
        self._report_overrides = report_overrides or {}
        self.calls = 0

    async def investigate(self, incident_id):
        self.calls += 1
        if self._raise:
            raise self._raise
        return InvestigationReport.model_validate(
            investigation_report_json(incident_id=uuid.UUID(str(incident_id)), **self._report_overrides)
        )


def _initial_state(incident_id=SAMPLE_INCIDENT_ID):
    return {
        "run_id": str(uuid.uuid4()),
        "incident_id": str(incident_id),
        "status": "running",
        "started_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }


async def _run(control_plane, investigator, thread_id=None):
    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, investigator, BOUNDS, InMemorySaver())
    result = await graph.ainvoke(_initial_state(), config=config, durability="sync")
    return graph, config, result


async def test_happy_path_reaches_completed_with_preserved_report():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "completed"
    assert result["completed_nodes"] == ["load_incident", "run_investigation", "evaluate_investigation", "finalize"]
    assert result["incident_snapshot"]["id"] == str(SAMPLE_INCIDENT_ID)
    # Final report preservation: the real investigation_report dict is
    # still exactly what the fake investigator returned.
    assert result["investigation_report"]["observations"][0]["statement"] == "502 observed"
    assert result["result_quality"] in ("well_supported", "inconclusive", "partial")
    assert result.get("error_code") is None


async def test_incident_not_found_routes_to_finalize_as_failed():
    control_plane = FakeControlPlaneClient(raise_=IncidentNotFoundError(str(SAMPLE_INCIDENT_ID)))
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "failed"
    assert result["error_code"] == "incident_not_found"
    assert result["completed_nodes"] == ["load_incident", "finalize"]
    # run_investigation never ran -- short-circuited.
    assert investigator.calls == 0


async def test_control_plane_output_invalid_routes_to_finalize_as_failed():
    control_plane = FakeControlPlaneClient(raise_=ControlPlaneOutputError("shape mismatch"))
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "failed"
    assert result["error_code"] == "control_plane_output_invalid"
    assert investigator.calls == 0


async def test_malformed_investigator_response_routes_to_finalize_as_failed():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient(raise_=InvestigatorOutputError("response did not match expected shape"))
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "failed"
    assert result["error_code"] == "investigator_output_invalid"


async def test_error_detail_is_bounded_and_preserves_the_clients_own_safe_message():
    """Clients (clients/control_plane.py, clients/investigator.py) are
    themselves responsible for never constructing an exception message
    containing a raw secret (proven directly in their own test
    modules) -- this node-level test instead proves `_safe_detail`'s
    OWN bounding responsibility: an overly long message is truncated to
    `bounds.max_error_detail_chars`, never persisted unbounded."""
    long_message = "investigator-service response did not match the expected response contract" + ("x" * 1000)
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient(raise_=InvestigatorOutputError(long_message))
    _graph, _config, result = await _run(control_plane, investigator)
    # Correction round follow-up (finding #1): a REAL hard bound --
    # never configured_max PLUS the truncation suffix's own length.
    assert len(result["error_detail"]) <= BOUNDS.max_error_detail_chars
    assert result["error_detail"] != long_message


# --- Phase 7 correction round (finding #3): TRANSIENT/RETRYABLE
# dependency failures are deliberately left UNCAUGHT by graph/nodes.py
# -- these tests prove that choice at the real graph/checkpoint level
# (not just that the exception type exists), complementing
# test_checkpoint_durability.py's real-PostgreSQL proof of the
# identical mechanism for an unclassified crash. -----------------------


async def test_control_plane_unavailable_propagates_and_leaves_thread_resumable_at_load_incident():
    control_plane = FakeControlPlaneClient(raise_=ControlPlaneUnavailableError("could not reach control-plane"))
    investigator = FakeInvestigatorClient()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, investigator, BOUNDS, InMemorySaver())

    # Seeded exactly like the real API's create_agent_run (finding #2) --
    # as if from START, no node executes yet.
    await graph.aupdate_state(config, _initial_state(), as_node=START)

    with pytest.raises(ControlPlaneUnavailableError):
        await graph.ainvoke(None, config=config, durability="sync")

    snap = await graph.aget_state(config)
    assert snap.next == ("load_incident",)
    assert investigator.calls == 0  # never reached run_investigation

    # Recovery: control-plane becomes reachable again -- the SAME
    # thread resumes and completes, never re-seeded, never a new run_id.
    control_plane._raise = None
    result = await graph.ainvoke(None, config=config, durability="sync")
    assert result["status"] == "completed"
    assert result["completed_nodes"].count("load_incident") == 1


async def test_investigator_unavailable_propagates_and_leaves_thread_resumable_at_run_investigation():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient(raise_=InvestigatorUnavailableError("investigator-service returned 503"))
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, investigator, BOUNDS, InMemorySaver())

    await graph.aupdate_state(config, _initial_state(), as_node=START)

    with pytest.raises(InvestigatorUnavailableError):
        await graph.ainvoke(None, config=config, durability="sync")

    snap = await graph.aget_state(config)
    assert snap.next == ("run_investigation",)
    # load_incident's own real result was already durably committed --
    # it must never be re-executed on resume.
    assert snap.values["completed_nodes"] == ["load_incident"]
    assert snap.values["incident_snapshot"] is not None
    assert control_plane.calls == 1

    investigator._raise = None
    result = await graph.ainvoke(None, config=config, durability="sync")
    assert result["status"] == "completed"
    assert control_plane.calls == 1  # load_incident never re-executed
    assert result["completed_nodes"].count("load_incident") == 1
    assert result["completed_nodes"].count("run_investigation") == 1


# --- Phase 7 correction round (finding #2): create_agent_run no longer
# executes the graph -- it seeds via aupdate_state(as_node=START). This
# proves that exact mechanism at the graph level directly. -------------


async def test_seeding_as_node_start_creates_no_execution_and_next_points_at_load_incident():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph(control_plane, investigator, BOUNDS, InMemorySaver())

    await graph.aupdate_state(config, _initial_state(), as_node=START)

    assert control_plane.calls == 0
    assert investigator.calls == 0
    snap = await graph.aget_state(config)
    assert snap.next == ("load_incident",)
    assert snap.values["status"] == "running"
    assert snap.values["current_node"] == "start"
    assert snap.values["completed_nodes"] == []


# --- Phase 7 correction round (finding #4): incident_snapshot's
# free-text fields must be bounded/redacted before entering durable
# graph state. ---------------------------------------------------------


async def test_load_incident_bounds_and_redacts_incident_snapshot_before_persisting():
    oversized_title = "x" * 5000
    secret_description = "auth failed: Bearer sk-TOPSECRET1234567890123456789"
    # Correction round follow-up (finding #2): source_fingerprint is
    # ALSO externally-derived free text with no length bound in
    # control-plane's own schema -- independent review reproduced
    # exactly this shape (a credential-prefixed, oversized fingerprint)
    # persisted completely untouched.
    oversized_secret_fingerprint = "Bearer TOPSECRET" + ("w" * 5000)
    control_plane = FakeControlPlaneClient(
        incident_overrides={
            "title": oversized_title,
            "description": secret_description,
            "source_fingerprint": oversized_secret_fingerprint,
        }
    )
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)

    snapshot = result["incident_snapshot"]
    # Correction round follow-up (finding #1): a REAL hard bound.
    assert len(snapshot["title"]) <= BOUNDS.max_incident_text_chars
    assert oversized_title not in snapshot["title"]
    assert "sk-TOPSECRET1234567890123456789" not in snapshot["description"]
    assert "Bearer [REDACTED]" in snapshot["description"]
    assert len(snapshot["source_fingerprint"]) <= BOUNDS.max_incident_text_chars
    assert "TOPSECRET" not in snapshot["source_fingerprint"]
    assert "w" * 5000 not in snapshot["source_fingerprint"]


# --- Phase 7 correction round (follow-up, finding #3): a hard ceiling
# on an InvestigationReport's own SERIALIZED SIZE before persistence. --


async def test_oversized_investigation_report_is_rejected_safely():
    """A structurally valid report (passes shape validation) whose
    serialized size exceeds the configured ceiling must be rejected as
    a TERMINAL failure -- never persisted, and never echoed raw into
    error_detail."""
    control_plane = FakeControlPlaneClient()
    # Shape-valid (summary is just `str`) but far larger than the real
    # BOUNDS.max_investigation_report_bytes configured for this test.
    huge_summary = "x" * (BOUNDS.max_investigation_report_bytes + 10_000)
    investigator = FakeInvestigatorClient(report_overrides={"summary": huge_summary})
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "failed"
    assert result["error_code"] == "investigator_output_too_large"
    assert result["completed_nodes"] == ["load_incident", "run_investigation", "finalize"]
    # Never persisted at all -- not even a truncated/partial copy.
    assert result.get("investigation_report") is None
    # The raw oversized content must never appear in error_detail --
    # only a safe, fixed-shape message with byte counts.
    assert "x" * 1000 not in result["error_detail"]
    assert "bytes" in result["error_detail"]
    assert len(result["error_detail"]) <= BOUNDS.max_error_detail_chars


async def test_normal_sized_investigation_report_is_unaffected_by_the_size_ceiling():
    """The real, measured report shape this platform actually produces
    (observations/evidence/RAG provenance) stays well under the
    default ceiling and is persisted normally -- the ceiling must never
    trip on a legitimate, real-sized report."""
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)

    assert result["status"] == "completed"
    assert result.get("error_code") is None
    assert result["investigation_report"] is not None


async def test_same_incident_can_have_multiple_independent_run_ids():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()

    _g1, _c1, result1 = await _run(control_plane, investigator)
    _g2, _c2, result2 = await _run(control_plane, investigator)

    assert result1["run_id"] != result2["run_id"]
    assert result1["incident_id"] == result2["incident_id"] == str(SAMPLE_INCIDENT_ID)
    # Both runs genuinely executed independently -- two real calls each.
    assert control_plane.calls == 2
    assert investigator.calls == 2


async def test_run_id_is_a_real_uuid4_and_distinct_each_time():
    ids = {str(uuid.uuid4()) for _ in range(5)}
    assert len(ids) == 5
    for value in ids:
        parsed = uuid.UUID(value)
        assert parsed.version == 4


async def test_graph_state_transitions_recorded_in_completed_nodes_order():
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()
    _graph, _config, result = await _run(control_plane, investigator)
    assert result["current_node"] == "finalize"
    assert result["completed_nodes"] == [
        "load_incident",
        "run_investigation",
        "evaluate_investigation",
        "finalize",
    ]


async def test_completed_run_resume_is_a_safe_no_op_at_the_graph_level():
    """Graph-level companion to the API-level 409 test -- proves
    LangGraph's own underlying no-op-on-empty-next semantics directly,
    the same behavior api/agent_runs.py's resume endpoint relies on."""
    control_plane = FakeControlPlaneClient()
    investigator = FakeInvestigatorClient()
    graph, config, result = await _run(control_plane, investigator)
    assert investigator.calls == 1

    snap = await graph.aget_state(config)
    assert snap.next == ()

    result_again = await graph.ainvoke(None, config=config, durability="sync")
    assert result_again == result
    assert investigator.calls == 1  # never re-executed
