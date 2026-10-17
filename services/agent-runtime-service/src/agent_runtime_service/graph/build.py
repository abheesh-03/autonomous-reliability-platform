"""Builds the Phase 7 + Phase 8 graph topology:

    START -> load_incident -> run_investigation -> evaluate_investigation
      -> propose_remediation
          --(no policy match / terminal error)--> finalize
          --(proposal created)--> await_human_approval
              --(rejected)--> finalize
              --(REAL, trusted 'approved' decision)--> execute_remediation
                  --(terminal error)--> finalize
                  --(otherwise)--> verify_recovery -> finalize
      -> END

Phase 7's original four nodes (load_incident/run_investigation/
evaluate_investigation/finalize) are UNCHANGED in behavior; this
module only adds Phase 8's four new nodes and rewires
evaluate_investigation's own outgoing edge (which used to go straight
to finalize) through them. Every short-circuit edge from Phase 7 is
preserved exactly: an expected, classified failure at load_incident or
run_investigation still routes straight to finalize, same as before
this phase existed.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_runtime_service.clients.control_plane import ControlPlaneClient
from agent_runtime_service.clients.investigator import InvestigatorClient
from agent_runtime_service.clients.tool_gateway import ToolGatewayClient
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.graph.nodes import (
    AgentGraphState,
    build_nodes,
    route_after_await_human_approval,
    route_after_execute_remediation,
    route_after_load_incident,
    route_after_propose_remediation,
    route_after_run_investigation,
)


def build_graph(
    control_plane_client: ControlPlaneClient,
    investigator_client: InvestigatorClient,
    bounds: RuntimeBounds,
    tool_gateway_client: ToolGatewayClient | None = None,
) -> StateGraph:
    """Returns the UNCOMPILED graph -- callers `.compile(checkpointer=...)`
    it themselves (the real service compiles once with the real
    AsyncPostgresSaver at startup; tests compile with an
    InMemorySaver or a real one, per Phase 7 §LANGGRAPH)."""
    (
        load_incident,
        run_investigation,
        evaluate_investigation,
        propose_remediation,
        await_human_approval,
        execute_remediation,
        verify_recovery,
        finalize,
    ) = build_nodes(control_plane_client, investigator_client, bounds, tool_gateway_client)

    graph = StateGraph(AgentGraphState)
    graph.add_node("load_incident", load_incident)
    graph.add_node("run_investigation", run_investigation)
    graph.add_node("evaluate_investigation", evaluate_investigation)
    graph.add_node("propose_remediation", propose_remediation)
    graph.add_node("await_human_approval", await_human_approval)
    graph.add_node("execute_remediation", execute_remediation)
    graph.add_node("verify_recovery", verify_recovery)
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
    graph.add_edge("evaluate_investigation", "propose_remediation")
    graph.add_conditional_edges(
        "propose_remediation",
        route_after_propose_remediation,
        {"await_human_approval": "await_human_approval", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "await_human_approval",
        route_after_await_human_approval,
        {"execute_remediation": "execute_remediation", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "execute_remediation",
        route_after_execute_remediation,
        {"verify_recovery": "verify_recovery", "finalize": "finalize"},
    )
    graph.add_edge("verify_recovery", "finalize")
    graph.add_edge("finalize", END)

    return graph


def compile_graph(
    control_plane_client: ControlPlaneClient,
    investigator_client: InvestigatorClient,
    bounds: RuntimeBounds,
    checkpointer,
    tool_gateway_client: ToolGatewayClient | None = None,
) -> CompiledStateGraph:
    return build_graph(control_plane_client, investigator_client, bounds, tool_gateway_client).compile(
        checkpointer=checkpointer
    )
