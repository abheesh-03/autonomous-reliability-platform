"""FastAPI application factory for agent-runtime-service (Phase 7).

Startup (the `lifespan` context manager below) opens the ONE durable
checkpoint connection (checkpointer.CheckpointStore, backed by the
dedicated, least-privileged `agent_runtime` PostgreSQL role -- never
POSTGRES_USER/POSTGRES_PASSWORD) and compiles the graph exactly once;
route handlers never construct either themselves.

This service is given NO control-plane write-capable Bearer token
(CONTROL_PLANE_WEBHOOK_TOKEN / CONTROL_PLANE_LIFECYCLE_TOKEN), no
Docker socket, and no shell/subprocess execution -- see
docs/architecture/phase-7-durable-agent-runtime.md's security section
and tests/test_read_only_guarantees.py's structural proof. As of
Phase 8, it holds exactly two narrow, additional credentials
(CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN -- create a proposal only --
and TOOL_GATEWAY_EXECUTION_TOKEN -- ask tool-gateway to execute an
already-approved action only) -- it still never receives
CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN, never
CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN, and never any
payment-service credential; see
docs/architecture/phase-8-human-approval-remediation.md.
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
from agent_runtime_service.clients.tool_gateway import ToolGatewayClient
from agent_runtime_service.config import (
    CheckpointDbSettings,
    ControlPlaneSettings,
    InternalReadTokenSettings,
    InvestigatorSettings,
    OrganizationContextSettings,
    RemediationSettings,
    RuntimeBounds,
    ServiceAssertionSettings,
    ToolGatewaySettings,
)
from agent_runtime_service.graph.build import compile_graph

logger = logging.getLogger("agent_runtime_service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_settings = CheckpointDbSettings.from_env()
    control_plane_settings = ControlPlaneSettings.from_env()
    investigator_settings = InvestigatorSettings.from_env()
    bounds = RuntimeBounds.from_env()
    remediation_settings = RemediationSettings.from_env()
    tool_gateway_settings = ToolGatewaySettings.from_env()

    internal_read_token_settings = InternalReadTokenSettings.from_env()
    # Phase 14 correction round, Blocker 1: constructed BEFORE the two
    # clients below so each can relay a derived assertion for the
    # current request's verified actor (authz.current_actor()) rather
    # than relying solely on the now-insufficient bare internal tokens.
    service_assertion_settings = ServiceAssertionSettings.from_env()
    control_plane_client = ControlPlaneClient(
        control_plane_settings.base_url,
        control_plane_settings.connect_timeout_seconds,
        control_plane_settings.request_timeout_seconds,
        remediation_proposal_token=remediation_settings.proposal_token,
        internal_read_token=internal_read_token_settings.control_plane_token,
        service_assertion_settings=service_assertion_settings,
    )
    investigator_client = InvestigatorClient(
        investigator_settings.base_url,
        investigator_settings.connect_timeout_seconds,
        investigator_settings.request_timeout_seconds,
        internal_caller_token=internal_read_token_settings.investigator_token,
        service_assertion_settings=service_assertion_settings,
    )
    tool_gateway_client = ToolGatewayClient(
        tool_gateway_settings.base_url,
        tool_gateway_settings.execution_token,
        tool_gateway_settings.connect_timeout_seconds,
        tool_gateway_settings.request_timeout_seconds,
        service_assertion_settings=service_assertion_settings,
    )

    checkpoint_store = CheckpointStore(db_settings)
    saver = await checkpoint_store.open()
    graph = compile_graph(control_plane_client, investigator_client, bounds, saver, tool_gateway_client)

    app.state.checkpoint_store = checkpoint_store
    app.state.graph = graph
    app.state.runtime_bounds = bounds
    # Phase 8: api/agent_runs.py::resume_agent_run needs this SAME
    # client to independently fetch a proposal's trusted decision
    # before ever resuming a real pending interrupt (Phase 8 §HUMAN
    # DECISION SOURCE OF TRUTH) -- never a second, separately
    # constructed client.
    app.state.control_plane_client = control_plane_client
    # Phase 14: see config.py's own docstrings -- non-blocking at
    # startup, same philosophy as every setting above.
    app.state.organization_context_settings = OrganizationContextSettings.from_env()
    app.state.service_assertion_settings = service_assertion_settings

    try:
        yield
    finally:
        await checkpoint_store.close()


app = FastAPI(
    title="Autonomous Reliability Platform — Agent Runtime",
    description=(
        "Phase 7 established a durable LangGraph agent runtime: given an existing incident UUID, "
        "orchestrates a small, explicit, checkpointed graph (load_incident -> run_investigation -> "
        "evaluate_investigation -> finalize) over control-plane's existing read-only GET API and "
        "investigator-service's existing read-only/computational investigation API. Phase 8 extends "
        "that SAME graph (load_incident -> run_investigation -> evaluate_investigation -> "
        "propose_remediation -> [await_human_approval -> execute_remediation -> verify_recovery] -> "
        "finalize) with a deterministic-policy remediation proposal, a REAL LangGraph human-approval "
        "interrupt, and tool-gateway-mediated execution of exactly one allowlisted, idempotent action. "
        "Every run remains a durable, resumable execution with inspectable checkpoint history. This "
        "service itself still has no direct infrastructure/application mutation capability of its own: "
        "no incident-lifecycle write token, no payment-service credential of any kind, no Docker "
        "socket, and no shell/Kubernetes/AWS access -- it can only create a remediation PROPOSAL and "
        "ask tool-gateway to execute an action control-plane has already independently recorded as "
        "human-approved."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(agent_runs_router)
