"""Phase 5 §8/§9: "confirmed absence of write-capable calls" and "no
mutation of existing incident/audit state", checked structurally
against this service's own source tree — not just by convention.

These are static/source-level checks precisely because the strongest
possible guarantee here is that the CODE HAS NO PATH to do the
forbidden things, not merely that nothing currently exercises one.
"""

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "investigator_service"

FORBIDDEN_TOKENS = (
    "CONTROL_PLANE_WEBHOOK_TOKEN",
    "CONTROL_PLANE_LIFECYCLE_TOKEN",
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "POSTGRES_HOST",
)

FORBIDDEN_SUBSTRINGS = (
    "/internal/v1/alertmanager/webhook",
    "incidents/{incident_id}/status",
)


def _all_source_files() -> list[pathlib.Path]:
    return list(SRC_ROOT.rglob("*.py"))


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Identifies the AST nodes that are module/class/function
    DOCSTRINGS specifically (the first statement of their body, if it
    is a bare string expression) — these are documentation, allowed
    to mention a forbidden name/path when explaining what this service
    deliberately does NOT do. Every OTHER string literal in the file
    is still scanned below."""
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


def test_no_write_capable_control_plane_token_is_ever_referenced_in_real_code():
    """Docstrings are allowed to name these tokens when explaining
    that they are deliberately never read; this checks every OTHER
    string literal — i.e. anything that could actually be used as an
    os.environ key or similar — across the whole source tree."""
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for token in FORBIDDEN_TOKENS:
            assert token not in constants, f"{path} uses forbidden env var {token!r} as a real (non-docstring) string literal"


def test_no_write_capable_control_plane_endpoint_is_ever_referenced_in_real_code():
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert not any(forbidden in c for c in constants), (
                f"{path} uses forbidden endpoint path {forbidden!r} in a real (non-docstring) string literal"
            )


def test_control_plane_client_module_calls_only_http_get():
    """AST-level check (not just a string grep): every httpx client
    call in clients/control_plane.py is `.get(...)` — there is no
    `.post`/`.put`/`.patch`/`.delete` call anywhere in that module."""
    tree = ast.parse((SRC_ROOT / "clients" / "control_plane.py").read_text())
    write_verbs = {"post", "put", "patch", "delete"}
    found_verbs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in write_verbs:
            found_verbs.add(node.attr)
    assert not found_verbs, f"control_plane.py calls write HTTP verb(s): {found_verbs}"


def test_no_module_imports_a_database_driver():
    """This service holds no PostgreSQL credentials and needs no
    database driver at all (Phase 5 §8: "does not require PostgreSQL
    credentials or direct database access")."""
    forbidden_imports = {"asyncpg", "psycopg", "psycopg2", "sqlalchemy"}
    for path in _all_source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            overlap = names & forbidden_imports
            assert not overlap, f"{path} imports forbidden database driver {overlap}"


def test_no_module_imports_docker_or_subprocess_or_shell_execution():
    """No tool/shell/Docker access is ever given to this service or
    to the LLM it calls (Phase 5 §6/§8)."""
    forbidden_imports = {"docker", "subprocess"}
    for path in _all_source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            overlap = names & forbidden_imports
            assert not overlap, f"{path} imports forbidden module {overlap}"
        assert "os.system" not in path.read_text()
