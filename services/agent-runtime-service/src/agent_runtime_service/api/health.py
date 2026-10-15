"""Liveness and readiness (Phase 7 §HEALTH ENDPOINTS).

/health/live: the process is alive. Never depends on the checkpoint
database, control-plane, or investigator-service being reachable --
restarting this container would not fix any of those being down, so
conflating this with their health would only cause an unnecessary
restart loop.

/health/ready: honestly reflects whether the durable checkpointer
itself is usable (a real round-trip against this service's OWN
schema) -- NOT whether control-plane/investigator-service currently
happen to be healthy. A POST /api/v1/agent-runs request against a
down investigator-service still fails explicitly and informatively at
that specific node (see graph/nodes.py) -- that is a per-request
outcome, not a reason to report this whole process "not ready".

Phase 7 correction round (finding #6): also reports this process's
OWN live connection identity (current_user/current_schema/search_path)
-- safe metadata only, never a password or connection string -- so an
external acceptance gate can independently prove the RUNNING service
is genuinely connected as the dedicated `agent_runtime` role/schema,
not merely that config.py's own startup validation would have refused
a misconfiguration (see checkpointer.CheckpointStore.identity).
"""

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "UP"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict:
    checkpoint_store = request.app.state.checkpoint_store
    checkpoint_ok = await checkpoint_store.ping()
    identity = await checkpoint_store.identity() if checkpoint_ok else None

    body = {
        "status": "ready" if checkpoint_ok else "not ready",
        "checkpoint_store": {"reachable": checkpoint_ok, "identity": identity},
    }
    if not checkpoint_ok:
        response.status_code = 503
    return body
