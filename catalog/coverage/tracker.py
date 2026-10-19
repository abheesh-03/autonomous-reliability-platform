"""Gate F: coverage calculation. `catalogued` is the one dimension
derived purely from manifest membership (import itself is the
evidence). Every other dimension is counted ONLY from
`CapabilityEvidence` records that `catalog.coverage.verification`
independently VERIFIES -- a merely SUBMITTED evidence record that
fails verification (fabricated, nonexistent, or an unimplemented
detector family) contributes zero to any dimension's count, full stop.
This module never infers, interpolates, rounds up a coverage claim, or
lets a caller set a bypassing "verified=True" flag directly on a
`CapabilityEvidence` record.

Correction-round Issue 2: before `verification.py` existed,
`compute_coverage` counted every submitted `CapabilityEvidence` record
at face value -- a fabricated `evidence_reference` (e.g.
"nonexistent-file-does-not-exist.py::test_fake") advanced
`detection_validated` exactly as if it were real. Every evidence
record is now run through `verify_evidence` first; only a `VERIFIED`
outcome counts toward `dimension_counts`/`coverage_by_domain`/
`coverage_by_detector_family`. `REJECTED` and `UNVERIFIABLE` evidence
is preserved in the report (`rejected_evidence`,
`unverifiable_evidence_count`) so the honest distinction between what
was CLAIMED and what was independently VALIDATED is never lost, but
neither ever inflates a coverage number."""

import pathlib
from typing import Optional

from pydantic import BaseModel, ConfigDict

from catalog.coverage.verification import IndependentVerifier, VerificationOutcome, verify_evidence
from catalog.schemas.catalog import CatalogManifest
from catalog.schemas.coverage import CapabilityEvidence, CoverageDimension

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_scenarios: int
    dimension_counts: dict[str, int]
    coverage_by_domain: dict[str, dict[str, int]]
    coverage_by_detector_family: dict[str, dict[str, int]]
    unresolved_gaps: list[str]
    submitted_evidence_count: int
    verified_evidence_count: int
    unverifiable_evidence_count: int
    rejected_evidence: list[str]


class CoverageError(Exception):
    pass


def compute_coverage(
    manifest: CatalogManifest,
    evidence: list[CapabilityEvidence],
    repo_root: pathlib.Path = _REPO_ROOT,
    independent_verifier: Optional[IndependentVerifier] = None,
) -> CoverageReport:
    """`independent_verifier` is the Phase 11B extension point (see
    `catalog.coverage.verification`'s own docstring) -- Phase 11A's CLI
    never supplies one, so collection/registry-metadata signals alone
    can never advance verified coverage in this phase."""
    scenario_ids = {s.scenario_id for s in manifest.scenarios}
    scenario_domain = {s.scenario_id: s.domain_id for s in manifest.scenarios}

    for e in evidence:
        if e.scenario_id not in scenario_ids:
            raise CoverageError(
                f"evidence references unknown scenario_id {e.scenario_id!r} -- "
                "coverage can never be claimed for a scenario that is not actually in the catalog"
            )
        if e.dimension == CoverageDimension.CATALOGUED:
            raise CoverageError(
                "evidence must never be submitted for the 'catalogued' dimension -- "
                "it is derived solely from catalog membership, never from external evidence"
            )

    verification_results = [(e, verify_evidence(e, repo_root, independent_verifier)) for e in evidence]
    verified_evidence = [e for e, r in verification_results if r.outcome == VerificationOutcome.VERIFIED]
    unverifiable_evidence = [e for e, r in verification_results if r.outcome == VerificationOutcome.UNVERIFIABLE]
    rejected_evidence = [
        f"{e.scenario_id}/{e.dimension.value} ({e.evidence_kind.value}, ref={e.evidence_reference!r}): {r.reason}"
        for e, r in verification_results
        if r.outcome == VerificationOutcome.REJECTED
    ]

    # scenario_id -> dimension -> whether INDEPENDENTLY VERIFIED
    # evidence exists (never merely submitted evidence).
    scenarios_with_dimension: dict[CoverageDimension, set[str]] = {d: set() for d in CoverageDimension}
    scenarios_with_dimension[CoverageDimension.CATALOGUED] = set(scenario_ids)
    for e in verified_evidence:
        scenarios_with_dimension[e.dimension].add(e.scenario_id)

    dimension_counts = {d.value: len(scenarios_with_dimension[d]) for d in CoverageDimension}

    coverage_by_domain: dict[str, dict[str, int]] = {}
    for scenario_id, domain_id in scenario_domain.items():
        bucket = coverage_by_domain.setdefault(domain_id, {d.value: 0 for d in CoverageDimension})
        for d in CoverageDimension:
            if scenario_id in scenarios_with_dimension[d]:
                bucket[d.value] += 1

    family_ids = {e.detector_family_id for e in verified_evidence if e.detector_family_id is not None}
    coverage_by_detector_family: dict[str, dict[str, int]] = {}
    for family_id in sorted(family_ids):
        coverage_by_detector_family[family_id] = {
            d.value: len(
                {e.scenario_id for e in verified_evidence if e.detector_family_id == family_id and e.dimension == d}
            )
            for d in CoverageDimension
        }

    unresolved_gaps: list[str] = []
    for d in CoverageDimension:
        if d == CoverageDimension.CATALOGUED:
            continue
        count = dimension_counts[d.value]
        if count == 0:
            # Deliberately phrased as "no evidence recorded", never
            # "detection failed" -- absence of evidence is not itself
            # a failure claim (Gate F's own explicit requirement).
            unresolved_gaps.append(f"no scenario has recorded evidence for dimension {d.value!r} yet")

    return CoverageReport(
        total_scenarios=len(scenario_ids),
        dimension_counts=dimension_counts,
        coverage_by_domain=coverage_by_domain,
        coverage_by_detector_family=coverage_by_detector_family,
        unresolved_gaps=unresolved_gaps,
        submitted_evidence_count=len(evidence),
        verified_evidence_count=len(verified_evidence),
        unverifiable_evidence_count=len(unverifiable_evidence),
        rejected_evidence=rejected_evidence,
    )
