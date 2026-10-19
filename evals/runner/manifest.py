"""Validates evals/datasets/<version>/manifest.json against the
ACTUAL, currently-loaded case files (Issue 3/final correction pass).
A manifest that is internally inconsistent (its own category counts
don't sum to its own declared total_cases -- the exact authoring bug
this module's own tests reproduce), or that drifts from what is
really on disk (a case removed, a case added without updating the
manifest, a category count that no longer matches), is a hard failure
for the DEFAULT, unfiltered full-dataset run -- never silently
ignored. Subset runs (an explicit --case-id/--category filter) skip
the full-completeness check (there is no requirement that a
deliberately-filtered run cover the whole dataset), but still go
through `validate_manifest_internal_consistency`, which costs nothing
and depends on no case files at all.
"""

import json
import pathlib
from collections import Counter

from evals.scoring.models import Case


class ManifestError(Exception):
    pass


def load_manifest(path: pathlib.Path) -> dict:
    if not path.exists():
        raise ManifestError(f"required dataset manifest not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest at {path} is not valid JSON: {exc}") from exc


def validate_manifest_internal_consistency(manifest: dict) -> None:
    """Self-consistency only -- independent of any real case file.
    Catches exactly Issue 3's own bug: categories summing to 16 while
    total_cases declared 15."""
    categories = manifest.get("categories", {})
    declared_total = manifest.get("total_cases")
    category_sum = sum(categories.values())
    if declared_total != category_sum:
        raise ManifestError(
            f"manifest is internally inconsistent: total_cases={declared_total!r} but its own "
            f"categories {categories!r} sum to {category_sum}"
        )


def validate_manifest_against_cases(manifest: dict, cases: list[Case], dataset_version: str) -> None:
    """Full-dataset completeness check -- call ONLY for an unfiltered
    (full) run. Never silently ignores a case the manifest expects
    that is no longer on disk, a case on disk the manifest never
    declared, or a category/total count drift."""
    validate_manifest_internal_consistency(manifest)

    manifest_version = manifest.get("dataset_version")
    if manifest_version != dataset_version:
        raise ManifestError(
            f"manifest dataset_version={manifest_version!r} does not match the dataset_version being "
            f"evaluated ({dataset_version!r})"
        )

    actual_total = len(cases)
    declared_total = manifest.get("total_cases")
    if declared_total != actual_total:
        raise ManifestError(
            f"manifest declares total_cases={declared_total!r}, but {actual_total} real case file(s) were loaded"
        )

    actual_categories = dict(Counter(c.category for c in cases))
    declared_categories = manifest.get("categories", {})
    if actual_categories != declared_categories:
        raise ManifestError(
            f"manifest category counts {declared_categories!r} do not match the real, loaded case files' own "
            f"category counts {actual_categories!r}"
        )

    declared_case_ids = manifest.get("case_ids")
    if declared_case_ids is not None:
        actual_ids = {c.case_id for c in cases}
        declared_ids = set(declared_case_ids)
        missing_from_disk = declared_ids - actual_ids
        undeclared_on_disk = actual_ids - declared_ids
        if missing_from_disk or undeclared_on_disk:
            raise ManifestError(
                "manifest case_ids do not match the real, loaded case files -- "
                f"declared but missing from disk: {sorted(missing_from_disk)}; "
                f"present on disk but not declared in the manifest: {sorted(undeclared_on_disk)}"
            )
