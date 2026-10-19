"""Minimal fake doubles for agent-runtime-service's control-plane/
investigator/tool-gateway client Protocols -- used ONLY to drive the
REAL `agent_runtime_service.graph.build.compile_graph` /
`agent_runtime_service.graph.nodes.build_nodes` offline, with
`langgraph.checkpoint.memory.InMemorySaver` (never a real PostgreSQL
connection, never a real HTTP call to any backend).

Deliberately mirror the shape (not the code) of
services/agent-runtime-service/tests/test_remediation_graph.py's own
FakeControlPlaneClient/FakeInvestigatorClient/FakeToolGatewayClient --
that file is this platform's own existing, proven seam for exercising
these exact node functions without a live stack; this package cannot
import a sibling service's `tests/` module directly (test packages are
not installed, by design), so the same minimal duck-typed shape is
reproduced here instead of inventing a different one.
"""
