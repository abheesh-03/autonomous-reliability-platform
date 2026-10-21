"""Gate F tests: coverage must report zero for any dimension with no
evidence (never invent partial credit), must reject evidence for
unknown scenarios or the catalogued dimension, and catalogued must
always equal the real scenario count with no external evidence
required. See `catalog/tests/test_coverage_verification.py` for the
correction-round Issue 2 fabricated-evidence negative controls."""

import pytest

from catalog.coverage.tracker import CoverageError, compute_coverage
from catalog.importer.build import build_catalog
from catalog.schemas.coverage import CapabilityEvidence, CoverageDimension, EvidenceKind

_MANIFEST = build_catalog()


def test_catalogued_count_equals_all_800_with_zero_evidence():
    report = compute_coverage(_MANIFEST, evidence=[])
    assert report.dimension_counts["catalogued"] == 800
    assert report.total_scenarios == 800


def test_with_no_evidence_every_other_dimension_is_zero():
    report = compute_coverage(_MANIFEST, evidence=[])
    for dim in CoverageDimension:
        if dim == CoverageDimension.CATALOGUED:
            continue
        assert report.dimension_counts[dim.value] == 0


def test_no_evidence_produces_unresolved_gap_entries_for_every_non_catalogued_dimension():
    report = compute_coverage(_MANIFEST, evidence=[])
    assert len(report.unresolved_gaps) == len(CoverageDimension) - 1
    assert all("no scenario has recorded evidence" in g for g in report.unresolved_gaps)
    assert all("detection failed" not in g for g in report.unresolved_gaps)


def test_a_single_real_but_unverified_evidence_record_does_not_advance_coverage():
    """Final correction round: a real, collectible TEST_REFERENCE is
    UNVERIFIABLE, not VERIFIED, with no independent_verifier supplied
    -- collection alone never counts toward coverage."""
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F16",
            dimension=CoverageDimension.TAXONOMY_REVIEWED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_are_flagged",
            recorded_by="phase-11a-gate-f-test",
        )
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["taxonomy_reviewed"] == 0
    assert report.dimension_counts["detector_implemented"] == 0
    assert report.unverifiable_evidence_count == 1
    assert report.verified_evidence_count == 0


def test_duplicate_unverified_evidence_for_same_scenario_dimension_does_not_double_count():
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F16",
            dimension=CoverageDimension.TAXONOMY_REVIEWED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_are_flagged",
            recorded_by="tester",
        ),
        CapabilityEvidence(
            scenario_id="D01-F16",
            dimension=CoverageDimension.TAXONOMY_REVIEWED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_flagged_on_failure_class_field",
            recorded_by="tester",
        ),
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["taxonomy_reviewed"] == 0
    assert report.verified_evidence_count == 0
    assert report.unverifiable_evidence_count == 2


def test_evidence_can_reach_verified_only_through_the_independent_verifier_hook():
    """Proves VERIFIED is still reachable (Phase 11B's extension point
    works), but ONLY via an explicit, independent, scenario-linked
    verifier callback -- never from collection/registry metadata
    alone."""
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F16",
            dimension=CoverageDimension.TAXONOMY_REVIEWED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_are_flagged",
            recorded_by="tester",
        )
    ]
    report = compute_coverage(_MANIFEST, evidence, independent_verifier=lambda e: True)
    assert report.dimension_counts["taxonomy_reviewed"] == 1
    assert report.verified_evidence_count == 1
    assert report.unverifiable_evidence_count == 0


def test_evidence_for_unknown_scenario_id_is_rejected():
    evidence = [
        CapabilityEvidence(
            scenario_id="D99-F99",
            dimension=CoverageDimension.INSTRUMENTED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="ref",
            recorded_by="tester",
        )
    ]
    with pytest.raises(CoverageError, match="unknown scenario_id"):
        compute_coverage(_MANIFEST, evidence)


def test_evidence_for_catalogued_dimension_is_rejected():
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.CATALOGUED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="ref",
            recorded_by="tester",
        )
    ]
    with pytest.raises(CoverageError, match="catalogued"):
        compute_coverage(_MANIFEST, evidence)


def test_coverage_by_domain_reflects_catalogued_baseline():
    report = compute_coverage(_MANIFEST, evidence=[])
    assert len(report.coverage_by_domain) == 40
    assert all(bucket["catalogued"] == 20 for bucket in report.coverage_by_domain.values())


def test_coverage_by_detector_family_excludes_unimplemented_family_reference():
    """`availability_failures` remains implemented=False (it is not
    one of the families Phase 11B/11C implemented real code for --
    see catalog/tests/test_registry.py) -- a DETECTOR_IMPLEMENTATION_
    REFERENCE pointing at it must be REJECTED (a registry description
    is not an implementation), so coverage_by_detector_family must
    stay empty."""
    evidence = [
        CapabilityEvidence(
            scenario_id="D03-F05",
            dimension=CoverageDimension.DETECTOR_IMPLEMENTED,
            evidence_kind=EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE,
            evidence_reference="catalog/registry/detector_families.py::availability_failures",
            recorded_by="tester",
            detector_family_id="availability_failures",
        )
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.coverage_by_detector_family == {}
    assert report.dimension_counts["detector_implemented"] == 0
    assert len(report.rejected_evidence) == 1
    assert "not yet implemented" in report.rejected_evidence[0] or "implemented=True" in report.rejected_evidence[0]


def test_capability_evidence_schema_rejects_unknown_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.INSTRUMENTED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="ref",
            recorded_by="tester",
            auto_approved=True,
        )
