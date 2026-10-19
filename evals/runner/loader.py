"""Loads and validates versioned case files from evals/cases/<version>/*.json."""

import json
import pathlib

from evals.scoring.models import Case


class CaseLoadError(Exception):
    pass


def load_cases(cases_dir: pathlib.Path, dataset_version: str | None = None) -> list[Case]:
    """Loads every *.json file in `cases_dir`, sorted by filename for
    reproducible ordering. A malformed case file is a hard load error
    (never silently skipped -- a dataset that cannot be fully parsed
    is not a dataset this harness can honestly claim to have run)."""
    if not cases_dir.is_dir():
        raise CaseLoadError(f"cases directory not found: {cases_dir}")

    cases: list[Case] = []
    seen_ids: set[str] = set()
    for path in sorted(cases_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CaseLoadError(f"{path}: not valid JSON: {exc}") from exc
        try:
            case = Case.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise CaseLoadError(f"{path}: does not match the Case schema: {exc}") from exc

        if case.case_id in seen_ids:
            raise CaseLoadError(f"{path}: duplicate case_id {case.case_id!r}")
        seen_ids.add(case.case_id)

        if dataset_version is not None and case.dataset_version != dataset_version:
            raise CaseLoadError(
                f"{path}: case_id {case.case_id!r} has dataset_version={case.dataset_version!r}, "
                f"expected {dataset_version!r}"
            )
        cases.append(case)

    if not cases:
        raise CaseLoadError(f"no case files found in {cases_dir}")
    return cases
