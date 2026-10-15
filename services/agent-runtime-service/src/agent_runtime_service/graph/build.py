"""Builds the Phase 7 graph topology (Phase 7 §INITIAL PHASE 7 GRAPH):

    START -> load_incident -> run_investigation -> evaluate_investigation -> finalize -> END

with two short-circuit edges so an expected, classified failure at
`load_incident` or `run_investigation` routes straight to `finalize`
instead of continuing down a pipeline that has nothing left to
evaluate -- every run (success or expected failure) still reaches one
real terminal checkpoint. No `interrupt()`, no human-approval/
remediation nodes -- those are explicit Phase 8 scope (Phase 7 §NO
HUMAN APPROVAL YET).
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_runtime_service.clients.control_plane import ControlPlaneClient
from agent_runtime_service.clients.investigator import InvestigatorClient
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.graph.nodes import (
    AgentGraphState,
    build_nodes,
    route_after_load_incident,
    route_after_run_investigation,
)


def build_graph(
    control_plane_client: ControlPlaneClient,
    investigator_client: InvestigatorClient,
    bounds: RuntimeBounds,
) -> StateGraph:
    """Returns the UNCOMPILED graph -- callers `.compile(checkpointer=...)`
    it themselves (the real service compiles once with the real
    AsyncPostgresSaver at startup; tests compile with an
    InMemorySaver or a real one, per Phase 7 §LANGGRAPH)."""
    load_incident, run_investigation, evaluate_investigation, finalize = build_nodes(
        control_plane_client, investigator_client, bounds
    )

    graph = StateGraph(AgentGraphState)
    graph.add_node("load_incident", load_incident)
    graph.add_node("run_investigation", run_investigation)
    graph.add_node("evaluate_investigation", evaluate_investigation)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "load_incident")
    graph.add_conditional_edges(
        "load_incident", route_after_load_incident, {"run_investigation": "run_investigation", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "run_investigation",
        route_after_run_investigation,
        {"evaluate_investigation": "evaluate_investigation", "finalize": "finalize"},
    )
    graph.add_edge("evaluate_investigation", "finalize")
    graph.add_edge("finalize", END)

    return graph


def compile_graph(
    control_plane_client: ControlPlaneClient,
    investigator_client: InvestigatorClient,
    bounds: RuntimeBounds,
    checkpointer,
) -> CompiledStateGraph:
    return build_graph(control_plane_client, investigator_client, bounds).compile(checkpointer=checkpointer)
