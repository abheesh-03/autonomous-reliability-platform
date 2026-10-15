"""The agent-run lifecycle API (Phase 7 §API):

  POST /api/v1/agent-runs             -- create a durable run (seed only, no execution)
  GET  /api/v1/agent-runs/{run_id}    -- safe, normalized state view
  GET  /api/v1/agent-runs/{run_id}/history -- safe checkpoint metadata
  POST /api/v1/agent-runs/{run_id}/resume  -- execute/continue a run

Every run gets its own UUID `run_id`, used directly as the LangGraph
`thread_id` (Phase 7 §AGENT RUN IDENTITY) -- never `incident_id`, so
the same incident can be investigated multiple times as independent,
separately-addressable durable runs.

Phase 7 correction round (finding #2 -- CORE INVARIANT: "the caller
must possess a durable run id before any fallible external graph work
begins"): `create_agent_run` used to execute the ENTIRE graph
synchronously before returning, so a crash during that very first
execution left a perfectly valid, resumable LangGraph checkpoint that
the caller had no way to ever learn the run_id for. Fixed by splitting
creation from execution:

  - `POST /agent-runs` seeds a durable INITIAL checkpoint via
    `graph.aupdate_state(config, initial_state, as_node=START)` --
    LangGraph's own real API for writing state "as if it came from"
    a given node, which correctly leaves `next` pointing at
    `load_incident` WITHOUT executing it (verified directly against
    the installed LangGraph version before this was adopted). No
    control-plane/investigator-service call happens in this handler at
    all. The response already has a real, durable `run_id`,
    `status="running"`, `current_node="start"`, `resumable=True`.
  - `POST /agent-runs/{run_id}/resume` is what actually executes the
    graph -- via `ainvoke(None, config, durability="sync")`, LangGraph's
    real "continue this thread" semantics. This is the SAME call for
    "run for the very first time" and "recover after a crash": from
    LangGraph's own point of view these are identical -- continue a
    thread whose checkpoint has a non-empty `next` -- so there is no
    hand-rolled duplicate workflow/state machine here, only this one
    real LangGraph operation serving both cases.

"Resumable" is defined precisely as: the real checkpoint's own `next`
tuple is non-empty -- i.e. the graph has not yet reached a terminal
node, whether because it hasn't started yet (just seeded), genuinely
stopped mid-execution (a process crash or an uncaught, transient
dependency failure -- Phase 7 correction round finding #3), or is
between resume attempts. A run that reached `finalize` (whether
`status="completed"` or `status="failed"`) always has an EMPTY `next`
and is therefore never resumable -- confirmed empirically against a
real checkpoint store before this was adopted (see
docs/architecture/phase-7-durable-agent-runtime.md): calling
`ainvoke(None, ...)` again on a completed thread is itself a safe
no-op, but this endpoint returns an explicit 409 rather than relying
on that silently, so a caller gets a precise, documented status
instead of an ambiguous 200.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from langgraph.graph import START

from agent_runtime_service.clients.control_plane import ControlPlaneUnavailableError
from agent_runtime_service.clients.investigator import InvestigatorUnavailableError
from agent_runtime_service.domain.agent_run import (
    AgentRun,
    AgentRunHistory,
    AgentRunHistoryEntry,
    AgentRunRequest,
)
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport

logger = logging.getLogger("agent_runtime_service.api.agent_runs")

router = APIRouter(prefix="/api/v1")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _agent_run_from_values(run_id: uuid.UUID, thread_id: str, values: dict, next_nodes: tuple) -> AgentRun:
    incident_snapshot = values.get("incident_snapshot")
    investigation_report = values.get("investigation_report")
    return AgentRun(
        run_id=run_id,
        thread_id=thread_id,
        incident_id=values["incident_id"],
        status=values.get("status", "running"),
        started_at=values["started_at"],
        updated_at=values.get("updated_at", values["started_at"]),
        completed_at=values.get("completed_at"),
        current_node=values.get("current_node", "start"),
        completed_nodes=values.get("completed_nodes", []),
        incident_snapshot=IncidentSnapshot.model_validate(incident_snapshot) if incident_snapshot else None,
        investigation_report=(
            InvestigationReport.model_validate(investigation_report) if investigation_report else None
        ),
        result_quality=values.get("result_quality"),
        validation_notes=values.get("validation_notes", []),
        error_code=values.get("error_code"),
        error_detail=values.get("error_detail"),
        resumable=bool(next_nodes),
    )


async def _load_agent_run(graph, run_id: uuid.UUID, thread_id: str) -> AgentRun:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="agent run not found")
    return _agent_run_from_values(run_id, thread_id, snapshot.values, snapshot.next)


@router.post("/agent-runs", response_model=AgentRun, status_code=201)
async def create_agent_run(body: AgentRunRequest, request: Request) -> AgentRun:
    graph = request.app.state.graph

    # The server generates BOTH the run_id and the LangGraph thread_id
    # from it (Phase 7 §AGENT RUN IDENTITY) -- the caller never
    # supplies either. incident_id lives INSIDE graph state, never as
    # the thread_id, so the same incident can have many independent
    # runs.
    run_id = uuid.uuid4()
    thread_id = str(run_id)
    now = _now_iso()

    initial_state = {
        "run_id": thread_id,
        "incident_id": str(body.incident_id),
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }
    config = {"configurable": {"thread_id": thread_id}}

    # Seeds a durable checkpoint "as if from START" -- NO node executes,
    # NO external call happens (see the module docstring, finding #2).
    # `next` correctly already points at `load_incident` afterward.
    await graph.aupdate_state(config, initial_state, as_node=START)

    return await _load_agent_run(graph, run_id, thread_id)


@router.get("/agent-runs/{run_id}", response_model=AgentRun)
async def get_agent_run(run_id: uuid.UUID, request: Request) -> AgentRun:
    graph = request.app.state.graph
    return await _load_agent_run(graph, run_id, str(run_id))


@router.get("/agent-runs/{run_id}/history", response_model=AgentRunHistory)
async def get_agent_run_history(run_id: uuid.UUID, request: Request) -> AgentRunHistory:
    graph = request.app.state.graph
    bounds = request.app.state.runtime_bounds
    thread_id = str(run_id)
    config = {"configurable": {"thread_id": thread_id}}

    current = await graph.aget_state(config)
    if not current.values:
        raise HTTPException(status_code=404, detail="agent run not found")

    snapshots = []
    async for snap in graph.aget_state_history(config, limit=bounds.max_history_items):
        snapshots.append(snap)
    snapshots.reverse()  # aget_state_history yields newest-first; chronological is clearer for a caller

    entries = [
        AgentRunHistoryEntry(
            step=snap.metadata.get("step", i) if snap.metadata else i,
            checkpoint_id=snap.config["configurable"]["checkpoint_id"],
            node=snap.values.get("current_node", "start") if snap.values else "start",
            status_at_step=snap.values.get("status", "running") if snap.values else "running",
            created_at=snap.created_at,
            next_nodes=list(snap.next),
        )
        for i, snap in enumerate(snapshots)
    ]
    return AgentRunHistory(run_id=run_id, thread_id=thread_id, entries=entries)


@router.post("/agent-runs/{run_id}/resume", response_model=AgentRun)
async def resume_agent_run(run_id: uuid.UUID, request: Request) -> AgentRun:
    graph = request.app.state.graph
    thread_id = str(run_id)
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="agent run not found")
    if not snapshot.next:
        # Empty `next` means this thread already reached `finalize` --
        # completed OR failed, both terminal. Never re-executes
        # investigate/evaluate for an already-finished run.
        raise HTTPException(
            status_code=409,
            detail=(
                f"agent run is already in a terminal state (status={snapshot.values.get('status')!r}) "
                "and cannot be resumed"
            ),
        )

    # Phase 7 correction round (finding #3): ControlPlaneUnavailableError/
    # InvestigatorUnavailableError are deliberately left UNCAUGHT by
    # graph/nodes.py -- they propagate here. The last successfully
    # committed checkpoint remains the resume point (`next` still points
    # at the same pending node), so this run remains fully resumable;
    # this is the ONLY place either exception is translated, and only
    # into a safe, generic, fixed message -- never the raw exception
    # text, and never a persisted "failed"/terminal graph state (that
    # would make a transient outage permanently unrecoverable, exactly
    # what this correction fixes).
    try:
        await graph.ainvoke(None, config=config, durability="sync")
    except ControlPlaneUnavailableError as exc:
        logger.warning("control-plane unavailable while resuming agent run %s", run_id, exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail="control-plane is temporarily unavailable; this agent run remains resumable",
        ) from exc
    except InvestigatorUnavailableError as exc:
        logger.warning("investigator-service unavailable while resuming agent run %s", run_id, exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail="investigator-service is temporarily unavailable; this agent run remains resumable",
        ) from exc

    return await _load_agent_run(graph, run_id, thread_id)
