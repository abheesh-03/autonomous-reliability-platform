"""Phase 6 §10: "the retrieval service has a narrow responsibility --
its HTTP API is SEARCH-ONLY. The explicit indexer is the only code
allowed to write the retrieval table." Checked structurally, not just
by convention -- the same philosophy
investigator_service/tests/test_read_only_guarantees.py already
established for Phase 5.
"""

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "retrieval_service"

# search.py/api/search.py form the HTTP search path -- these modules
# must never reference ANY of db.py's write-capable function names.
HTTP_SEARCH_PATH_FILES = ("search.py", "api/search.py", "api/health.py", "main.py")
DB_WRITE_FUNCTION_NAMES = {"upsert_chunk", "delete_chunks_beyond", "delete_sources_not_in"}

FORBIDDEN_SUBSTRINGS = (
    "/api/v1/incidents/{incident_id}/status",
    "/internal/v1/alertmanager/webhook",
)


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


def _called_function_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def test_http_search_path_never_references_a_db_write_function():
    for rel_path in HTTP_SEARCH_PATH_FILES:
        path = SRC_ROOT / rel_path
        called = _called_function_names(path)
        overlap = called & DB_WRITE_FUNCTION_NAMES
        assert not overlap, f"{path} references write-capable db function(s): {overlap}"


def test_no_write_capable_control_plane_endpoint_is_ever_referenced():
    for path in _all_source_files():
        constants = _non_docstring_string_constants(path)
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert not any(forbidden in c for c in constants), (
                f"{path} uses forbidden endpoint path {forbidden!r} in a real (non-docstring) string literal"
            )


def test_control_plane_client_module_calls_only_http_get():
    """AST-level check: every httpx client call in
    clients/control_plane.py is `.get(...)` -- no `.post`/`.put`/
    `.patch`/`.delete` anywhere in that module."""
    tree = ast.parse((SRC_ROOT / "clients" / "control_plane.py").read_text())
    write_verbs = {"post", "put", "patch", "delete"}
    found_verbs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in write_verbs}
    assert not found_verbs, f"control_plane.py calls write HTTP verb(s): {found_verbs}"


def test_no_module_imports_docker_or_subprocess_or_shell_execution():
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


def test_api_search_module_has_no_insert_update_delete_sql_verbs_as_literals():
    """Defense in depth: even a literal SQL-shaped string in the HTTP
    search path would be suspicious -- the search path never
    constructs SQL at all (db.search_chunks is the only function it
    calls), but this guards against a future regression adding one."""
    path = SRC_ROOT / "search.py"
    constants = _non_docstring_string_constants(path)
    forbidden = ("INSERT INTO", "UPDATE ", "DELETE FROM")
    for c in constants:
        for kw in forbidden:
            assert kw not in c, f"{path} contains SQL write keyword {kw!r}"


def test_indexer_module_is_the_only_one_calling_db_write_functions():
    """The explicit indexer (Phase 6 §8) is the ONLY module allowed to
    call db.py's write-capable functions -- every other module in this
    service's source tree must have zero references to them."""
    indexer_path = SRC_ROOT / "indexer.py"
    for path in _all_source_files():
        if path in (indexer_path, SRC_ROOT / "db.py"):
            continue
        called = _called_function_names(path)
        overlap = called & DB_WRITE_FUNCTION_NAMES
        assert not overlap, f"{path} references write-capable db function(s): {overlap} outside the indexer"
