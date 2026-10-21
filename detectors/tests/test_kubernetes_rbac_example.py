"""Gate 6 (Phase 12A): structural proof that the EXAMPLE RBAC manifest
(detectors/kubernetes/rbac/observer-role.example.yaml) stays
least-privilege, namespace-scoped, and read-only -- this manifest is
never applied by any script in this repo, but it must still never
regress into granting more than it claims to."""

import pathlib

import yaml

_RBAC_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "kubernetes" / "rbac" / "observer-role.example.yaml"
)

_ALLOWED_VERBS = {"get", "list", "watch"}
_ALLOWED_RESOURCES = {"pods", "events", "deployments", "replicasets"}
_FORBIDDEN_VERBS = {"create", "update", "patch", "delete", "deletecollection", "impersonate", "bind", "escalate", "*"}


def _load_docs() -> list[dict]:
    return [d for d in yaml.safe_load_all(_RBAC_PATH.read_text()) if d]


def test_rbac_example_file_exists_and_is_not_referenced_by_any_make_target_or_script():
    assert _RBAC_PATH.is_file()
    repo_root = _RBAC_PATH.resolve().parents[3]
    for path in (repo_root / "Makefile",):
        assert "observer-role.example.yaml" not in path.read_text()
    for script in (repo_root / "scripts").glob("*.sh"):
        assert "observer-role.example.yaml" not in script.read_text()


def test_rbac_example_uses_only_namespace_scoped_kinds_never_cluster_wide():
    docs = _load_docs()
    kinds = {d["kind"] for d in docs}
    assert kinds == {"ServiceAccount", "Role", "RoleBinding"}
    assert "ClusterRole" not in kinds
    assert "ClusterRoleBinding" not in kinds
    for d in docs:
        assert d["metadata"]["namespace"] == "reliability-sandbox"


def test_rbac_example_role_grants_only_get_list_watch_on_the_four_known_resources():
    docs = _load_docs()
    role = next(d for d in docs if d["kind"] == "Role")
    for rule in role["rules"]:
        verbs = set(rule["verbs"])
        resources = set(rule["resources"])
        assert verbs <= _ALLOWED_VERBS, f"unexpected verb(s) {verbs - _ALLOWED_VERBS}"
        assert resources <= _ALLOWED_RESOURCES, f"unexpected resource(s) {resources - _ALLOWED_RESOURCES}"
        assert not (verbs & _FORBIDDEN_VERBS)


def test_rbac_example_never_references_secrets_or_pod_subresources():
    """Checks the parsed YAML rules themselves (never the prose
    comments, which deliberately name these as explicitly absent)."""
    docs = _load_docs()
    role = next(d for d in docs if d["kind"] == "Role")
    forbidden = {"secrets", "configmaps", "pods/exec", "pods/attach", "pods/portforward", "pods/log", "serviceaccounts/token"}
    for rule in role["rules"]:
        assert not (set(rule["resources"]) & forbidden)
