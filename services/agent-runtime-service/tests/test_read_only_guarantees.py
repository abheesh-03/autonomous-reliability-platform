"""Phase 7 §READ-ONLY SECURITY BOUNDARY: checked structurally against
this service's own source tree, not just by convention -- the same
philosophy investigator_service/tests/test_read_only_guarantees.py and
retrieval_service/tests/test_read_only_guarantees.py already establish.

agent-runtime-service DOES hold PostgreSQL credentials (Phase 7's own
dedicated, least-privileged `agent_runtime` role) -- unlike
investigator-service, which holds none. What it must NEVER hold is the
shared, broad POSTGRES_USER/POSTGRES_PASSWORD credential the rest of
this platform's application code uses, and it must never reference
control-plane's PRE-Phase-8 write-capable tokens/endpoints at all.

Phase 8 narrows (never widens) this boundary further: this service
now intentionally holds exactly TWO additional, narrow credentials --
CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN (create a remediation
proposal only) and TOOL_GATEWAY_EXECUTION_TOKEN (ask tool-gateway to
execute an already-approved action only) -- see
docs/architecture/phase-8-human-approval-remediation.md's credential
boundary table. It must still NEVER hold
CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN (the human/operator-only
decision credential),
CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN (tool-gateway's own
execution-bookkeeping credential), or either payment-service credential
(PAYMENT_FAULT_INJECTION_TOKEN/PAYMENT_REMEDIATION_TOKEN) -- and it
must never call the decision endpoint or either internal execution-
bookkeeping endpoint itself, since calling those is what those tokens
exist to gate.
"""

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "agent_runtime_service"

FORBIDDEN_TOKENS = (
    "CONTROL_PLANE_WEBHOOK_TOKEN",
    "CONTROL_PLANE_LIFECYCLE_TOKEN",
    # Phase 8: the human-approver-only and tool-gateway-executor-only
    # credentials -- this service must NEVER hold either. (It DOES
    # intentionally hold CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN and
    # TOOL_GATEWAY_EXECUTION_TOKEN, so neither of those two appears
    # here.)
    "CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN",
    "CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN",
    # Phase 8: neither payment-service credential -- this service never
    # talks to payment-service directly at all (only tool-gateway does).
    "PAYMENT_FAULT_INJECTION_TOKEN",
    "PAYMENT_REMEDIATION_TOKEN",
    # The shared, broad application credential -- this service must
    # use ONLY its own dedicated AGENT_RUNTIME_DB_USER/
    # AGENT_RUNTIME_DB_PASSWORD (see config.py), never these.
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

FORBIDDEN_SUBSTRINGS = (
    "/api/v1/incidents/{incident_id}/status",
    "/internal/v1/alertmanager/webhook",
    # Phase 8: the human-approver-only and tool-gateway-executor-only
    # endpoints -- only a human/operator (the decision endpoint) or
    # tool-gateway itself (the two execution-bookkeeping endpoints) may
    # ever call these; this service creates a proposal and reads it
    # back, nothing more.
    "/decision",
    "/execution/start",
    "/execution/result",
)

FORBIDDEN_IMPORTS = {
    "docker",
    "subprocess",
    "kubernetes",
    "boto3",
    "botocore",
}


def _all_source_files() -> list[pathlib.Path]:
    return list(SRC_ROOT.rglob("*.py"))


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _non_docstring_string_constants(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docstring_ids = _docstring_constant_ids(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids
    ]


def test_no_write_capable_control_plane_token_or_broad_db_credential_referenced():
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for token in FORBIDDEN_TOKENS:
            assert token not in constants, f"{path} uses forbidden env var {token!r} as a real (non-docstring) string literal"


def test_no_write_capable_control_plane_endpoint_is_ever_referenced():
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert not any(forbidden in c for c in constants), (
                f"{path} uses forbidden endpoint path {forbidden!r} in a real (non-docstring) string literal"
            )


def test_control_plane_client_module_calls_only_get_and_the_one_proposal_post():
    """Phase 7: this module called only GET. Phase 8 adds exactly ONE
    legitimate write call -- POST, for creating a remediation proposal
    only (authenticated with CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN,
    see config.py/main.py). PUT/PATCH/DELETE remain, and must remain,
    completely absent -- this service has no use for any of them."""
    tree = ast.parse((SRC_ROOT / "clients" / "control_plane.py").read_text())
    never_allowed_write_verbs = {"put", "patch", "delete"}
    found = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in never_allowed_write_verbs
    }
    assert not found, f"control_plane.py calls write HTTP verb(s) it must never use: {found}"

    post_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "post"]
    assert len(post_calls) == 1, f"expected exactly one client.post(...) call site, found {len(post_calls)}"


def test_tool_gateway_client_module_calls_only_get_capability_and_the_one_execute_post():
    """Phase 8: tool_gateway.py may call GET (the capability/
    precondition read) and exactly ONE POST (execute) -- never
    PUT/PATCH/DELETE, and never more than one POST call site, which
    would be the first sign of a second, broader execution surface
    creeping in."""
    tree = ast.parse((SRC_ROOT / "clients" / "tool_gateway.py").read_text())
    never_allowed_write_verbs = {"put", "patch", "delete"}
    found = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in never_allowed_write_verbs
    }
    assert not found, f"tool_gateway.py calls write HTTP verb(s) it must never use: {found}"

    post_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "post"]
    assert len(post_calls) == 1, f"expected exactly one client.post(...) call site, found {len(post_calls)}"


def test_investigator_client_module_calls_only_the_one_investigate_post():
    """investigator-service's own POST /api/v1/investigations is
    itself read-only/computational (Phase 5 §8) -- this client must
    never call any OTHER HTTP verb or any other path."""
    tree = ast.parse((SRC_ROOT / "clients" / "investigator.py").read_text())
    other_write_verbs = {"put", "patch", "delete"}
    found = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in other_write_verbs}
    assert not found, f"investigator.py calls forbidden HTTP verb(s): {found}"


def test_no_module_imports_docker_subprocess_kubernetes_or_cloud_sdks():
    for path in _all_source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            overlap = names & FORBIDDEN_IMPORTS
            assert not overlap, f"{path} imports forbidden module {overlap}"
        assert "os.system" not in path.read_text()


def test_no_module_imports_asyncpg_or_sqlalchemy():
    """This service's ONLY database access is via psycopg (langgraph-
    checkpoint-postgres's own dependency), to its own dedicated
    `agent_runtime` schema -- never asyncpg/SQLAlchemy, the drivers
    control-plane/retrieval-service use for the broad application
    role."""
    forbidden = {"asyncpg", "sqlalchemy"}
    for path in _all_source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            overlap = names & forbidden
            assert not overlap, f"{path} imports forbidden database driver {overlap}"


def test_no_module_references_reliability_schema_tables_in_real_code():
    """Defense in depth, structural: this service's own Python source
    should never NAME reliability.incidents/incident_events/
    retrieval_chunks in a real (non-docstring) string literal -- it
    has no business reading or writing any of them (that boundary is
    enforced for real at the database privilege level, see
    test_db_privilege_boundary.py; this just confirms the application
    CODE never even tries). Docstrings are allowed to name them when
    explaining that this service deliberately never touches them."""
    forbidden = ("reliability.incidents", "reliability.incident_events", "reliability.retrieval_chunks")
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for name in forbidden:
            assert not any(name in c for c in constants), f"{path} references {name!r} in real code"
