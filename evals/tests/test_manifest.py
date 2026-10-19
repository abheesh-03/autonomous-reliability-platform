import json
import pathlib

import pytest

from evals.runner.loader import load_cases
from evals.runner.manifest import (
    ManifestError,
    load_manifest,
    validate_manifest_against_cases,
    validate_manifest_internal_consistency,
)

_REAL_CASES_DIR = pathlib.Path(__file__).resolve().parents[1] / "cases" / "v1"
_REAL_MANIFEST_PATH = pathlib.Path(__file__).resolve().parents[1] / "datasets" / "v1" / "manifest.json"


def test_the_real_committed_manifest_is_internally_consistent():
    manifest = load_manifest(_REAL_MANIFEST_PATH)
    validate_manifest_internal_consistency(manifest)  # must not raise


def test_the_real_committed_manifest_matches_the_real_case_files():
    manifest = load_manifest(_REAL_MANIFEST_PATH)
    cases = load_cases(_REAL_CASES_DIR, dataset_version="v1")
    validate_manifest_against_cases(manifest, cases, "v1")  # must not raise


def test_manifest_missing_file_raises():
    with pytest.raises(ManifestError):
        load_manifest(pathlib.Path("/definitely/does/not/exist.json"))


def test_incorrect_category_count_is_rejected():
    """Reproduces Issue 3 exactly: categories sum to 16 while
    total_cases declares 15."""
    corrupted = {
        "dataset_version": "v1",
        "total_cases": 15,
        "categories": {
            "investigation_quality": 4,
            "remediation_safety": 6,  # the real bug -- should be 5
            "retrieval": 2,
            "citation": 3,
            "adversarial_prompt_injection": 1,
        },
    }
    with pytest.raises(ManifestError):
        validate_manifest_internal_consistency(corrupted)


def test_manifest_total_cases_not_matching_real_case_count_is_rejected():
    manifest = {
        "dataset_version": "v1",
        "total_cases": 999,
        "categories": {"citation": 999},
    }
    cases = load_cases(_REAL_CASES_DIR, dataset_version="v1")
    with pytest.raises(ManifestError):
        validate_manifest_against_cases(manifest, cases, "v1")


def test_manifest_dataset_version_mismatch_is_rejected():
    manifest = dict(load_manifest(_REAL_MANIFEST_PATH))
    manifest["dataset_version"] = "v2"
    cases = load_cases(_REAL_CASES_DIR, dataset_version="v1")
    with pytest.raises(ManifestError):
        validate_manifest_against_cases(manifest, cases, "v1")


def test_a_missing_required_case_id_is_never_silently_ignored(tmp_path: pathlib.Path):
    """Reproduces the 'removed required case' scenario: the manifest's
    own case_ids list still names a case that no longer exists on
    disk. total_cases/categories are deliberately left at their real,
    correct values here -- this isolates the case_ids check itself
    from the (separately tested) total_cases/categories checks, which
    would otherwise fire first and mask this one."""
    real_manifest = load_manifest(_REAL_MANIFEST_PATH)
    manifest_claiming_an_extra_case = dict(real_manifest)
    manifest_claiming_an_extra_case["case_ids"] = [*real_manifest["case_ids"], "THIS-CASE-DOES-NOT-EXIST"]
    cases = load_cases(_REAL_CASES_DIR, dataset_version="v1")
    with pytest.raises(ManifestError, match="missing from disk"):
        validate_manifest_against_cases(manifest_claiming_an_extra_case, cases, "v1")


def test_an_undeclared_case_on_disk_is_never_silently_ignored(tmp_path: pathlib.Path):
    """The inverse: a real case file exists on disk that the manifest
    never declared in its own case_ids. total_cases/categories are
    deliberately left at their real, correct values, isolating this
    check from the others."""
    real_manifest = load_manifest(_REAL_MANIFEST_PATH)
    manifest_missing_one_declaration = dict(real_manifest)
    manifest_missing_one_declaration["case_ids"] = [cid for cid in real_manifest["case_ids"] if cid != "RET-007"]
    cases = load_cases(_REAL_CASES_DIR, dataset_version="v1")
    with pytest.raises(ManifestError, match="not declared in the manifest"):
        validate_manifest_against_cases(manifest_missing_one_declaration, cases, "v1")
