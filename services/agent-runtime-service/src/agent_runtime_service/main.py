"""FastAPI application factory for agent-runtime-service (Phase 7).

Startup (the `lifespan` context manager below) opens the ONE durable
checkpoint connection (checkpointer.CheckpointStore, backed by the
dedicated, least-privileged `agent_runtime` PostgreSQL role -- never
POSTGRES_USER/POSTGRES_PASSWORD) and compiles the graph exactly once;
route handlers never construct either themselves.

This service is given NO control-plane write-capable Bearer token
(CONTROL_PLANE_WEBHOOK_TOKEN / CONTROL_PLANE_LIFECYCLE_TOKEN), no
Docker socket, no shell/subprocess execution, and no remediation
capability of any kind -- see
docs/architecture/phase-7-durable-agent-runtime.md's security section
and tests/test_read_only_guarantees.py's structural proof.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_runtime_service.api.agent_runs import router as agent_runs_router
from agent_runtime_service.api.health import router as health_router
from agent_runtime_service.checkpointer import CheckpointStore
from agent_runtime_service.clients.control_plane import ControlPlaneClient
from agent_runtime_service.clients.investigator import InvestigatorClient
from agent_runtime_service.config import (
    CheckpointDbSettings,
    ControlPlaneSettings,
    InvestigatorSettings,
    RuntimeBounds,
)
from agent_runtime_service.graph.build import compile_graph

logger = logging.getLogger("agent_runtime_service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_settings = CheckpointDbSettings.from_env()
    control_plane_settings = ControlPlaneSettings.from_env()
    investigator_settings = InvestigatorSettings.from_env()
    bounds = RuntimeBounds.from_env()

    control_plane_client = ControlPlaneClient(
        control_plane_settings.base_url,
        control_plane_settings.connect_timeout_seconds,
        control_plane_settings.request_timeout_seconds,
    )
    investigator_client = InvestigatorClient(
        investigator_settings.base_url,
        investigator_settings.connect_timeout_seconds,
        investigator_settings.request_timeout_seconds,
    )

    checkpoint_store = CheckpointStore(db_settings)
    saver = await checkpoint_store.open()
    graph = compile_graph(control_plane_client, investigator_client, bounds, saver)

    app.state.checkpoint_store = checkpoint_store
    app.state.graph = graph
    app.state.runtime_bounds = bounds

    try:
        yield
    finally:
        await checkpoint_store.close()


app = FastAPI(
    title="Autonomous Reliability Platform — Agent Runtime",
    description=(
        "Phase 7: a durable LangGraph agent runtime. Given an existing incident UUID, orchestrates a "
        "small, explicit, checkpointed graph (load_incident -> run_investigation -> "
        "evaluate_investigation -> finalize) over control-plane's existing read-only GET API and "
        "investigator-service's existing read-only/computational investigation API. Every run is a "
        "durable, resumable execution with inspectable checkpoint history -- never a mutation of any "
        "incident, never remediation, never shell/Docker/Kubernetes/AWS access."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(agent_runs_router)
