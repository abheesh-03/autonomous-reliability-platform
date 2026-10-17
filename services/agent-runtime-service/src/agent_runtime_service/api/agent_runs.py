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
from langgraph.types import Command

from agent_runtime_service.clients.control_plane import (
    ControlPlaneOutputError,
    ControlPlaneUnavailableError,
    RemediationProposalCreateAmbiguousError,
    RemediationProposalNotFoundError,
)
from agent_runtime_service.clients.investigator import InvestigatorUnavailableError
from agent_runtime_service.clients.tool_gateway import (
    ToolGatewayAmbiguousExecutionError,
    ToolGatewayUnavailableError,
)
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


def _agent_run_from_values(
    run_id: uuid.UUID, thread_id: str, values: dict, next_nodes: tuple, waiting_for_approval: bool
) -> AgentRun:
    incident_snapshot = values.get("incident_snapshot")
    investigation_report = values.get("investigation_report")
    # Phase 8 correction round (finding #4): "waiting_for_approval" is a
    # VIEW-layer status derived from the checkpoint's own REAL pending
    # LangGraph interrupt (StateSnapshot.interrupts, passed in by the
    # caller as `waiting_for_approval`) -- never merely from which node
    # name `next` happens to point at, and never written into the
    # durable AgentGraphState.status field itself (see
    # graph/nodes.py::await_human_approval's own docstring).
    status = "waiting_for_approval" if waiting_for_approval else values.get("status", "running")
    return AgentRun(
        run_id=run_id,
        thread_id=thread_id,
        incident_id=values["incident_id"],
        status=status,
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
        remediation_proposal_id=values.get("remediation_proposal_id"),
        remediation_action_type=values.get("remediation_action_type"),
        remediation_target=values.get("remediation_target"),
        remediation_status=values.get("remediation_status"),
        execution_result=values.get("execution_result"),
        recovery_verification=values.get("recovery_verification"),
    )


async def _load_agent_run(graph, run_id: uuid.UUID, thread_id: str) -> AgentRun:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="agent run not found")
    return _agent_run_from_values(
        run_id, thread_id, snapshot.values, snapshot.next, waiting_for_approval=bool(snapshot.interrupts)
    )


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
    control_plane_client = request.app.state.control_plane_client
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

    # Phase 8 §HUMAN DECISION SOURCE OF TRUTH. This endpoint takes NO
    # request body at all for a decision -- a caller can never bypass
    # approval by POSTing {"approved": true} here; there is no field
    # for it. A real, pending LangGraph interrupt (never merely
    # `next == ("await_human_approval",)` -- see
    # _load_agent_run/_agent_run_from_values's own correction-round
    # fix) means the trusted decision must come from control-plane,
    # independently fetched RIGHT NOW, never from anything the caller
    # supplied.
    resume_value = None
    if snapshot.interrupts:
        proposal_id = snapshot.values.get("remediation_proposal_id")
        if not proposal_id:  # pragma: no cover -- defensive; propose_remediation always sets this before interrupting
            raise HTTPException(status_code=500, detail="agent run is waiting for approval but has no proposal id")

        try:
            proposal = await control_plane_client.get_remediation_proposal(proposal_id)
        except RemediationProposalNotFoundError as exc:
            raise HTTPException(status_code=500, detail="the remediation proposal this run is waiting on no longer exists") from exc
        except ControlPlaneOutputError as exc:
            raise HTTPException(status_code=502, detail="control-plane returned an unexpected response") from exc
        except ControlPlaneUnavailableError as exc:
            logger.warning("control-plane unavailable while checking approval for agent run %s", run_id, exc_info=exc)
            raise HTTPException(
                status_code=503,
                detail="control-plane is temporarily unavailable; this agent run remains resumable",
            ) from exc

        if proposal.status == "pending_approval":
            # Never resumes the interrupt -- the run stays exactly
            # where it is, waiting for the SAME proposal.
            raise HTTPException(
                status_code=409,
                detail=f"approval_pending: remediation proposal {proposal_id} has not been decided yet",
            )
        if proposal.status == "approved":
            resume_value = Command(resume={"decision": "approved", "proposal_id": str(proposal.id)})
        elif proposal.status == "rejected":
            resume_value = Command(resume={"decision": "rejected", "proposal_id": str(proposal.id)})
        else:
            # executing/succeeded/failed while the interrupt is STILL
            # pending is an inconsistent state that should not be
            # reachable (resuming an approved/rejected decision always
            # clears the interrupt) -- fail safely rather than guess.
            raise HTTPException(
                status_code=409,
                detail=f"remediation proposal {proposal_id} is in an unexpected status {proposal.status!r} "
                "while this run is still waiting for approval",
            )

    # Phase 7 correction round (finding #3), extended in Phase 8 to
    # ToolGatewayUnavailableError and (correction round, finding #1)
    # ToolGatewayAmbiguousExecutionError: ControlPlaneUnavailableError/
    # InvestigatorUnavailableError/ToolGatewayUnavailableError/
    # ToolGatewayAmbiguousExecutionError are deliberately left UNCAUGHT
    # by graph/nodes.py -- they propagate here. The last successfully
    # committed checkpoint remains the resume point, so this run
    # remains fully resumable; this is the ONLY place any of the four
    # is translated, and only into a safe, generic, fixed message --
    # never the raw exception text, and never a persisted "failed"/
    # terminal graph state.
    try:
        await graph.ainvoke(resume_value, config=config, durability="sync")
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
    except ToolGatewayUnavailableError as exc:
        logger.warning("tool-gateway unavailable while resuming agent run %s", run_id, exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail="tool-gateway is temporarily unavailable; this agent run remains resumable",
        ) from exc
    except ToolGatewayAmbiguousExecutionError as exc:
        logger.warning("tool-gateway execution outcome ambiguous while resuming agent run %s", run_id, exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail="tool-gateway's execution outcome could not yet be confirmed; this agent run remains resumable",
        ) from exc
    except RemediationProposalCreateAmbiguousError as exc:
        logger.warning("remediation-proposal creation outcome ambiguous while resuming agent run %s", run_id, exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "control-plane's remediation-proposal creation outcome could not yet be confirmed; "
                "this agent run remains resumable"
            ),
        ) from exc

    return await _load_agent_run(graph, run_id, thread_id)
