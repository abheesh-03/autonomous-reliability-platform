"""Correction-round Issue 2 + the final evidence-trust-boundary
correction: fabricated or merely-plausible-looking `CapabilityEvidence`
must never advance verified coverage. Reproduces the independent
reviewer's exact fabricated-reference case (REJECTED) and the final
correction's own concern -- that pytest COLLECTION succeeding, or
registry `implemented=True` metadata, is NOT sufficient independent
proof of execution or scenario-specific validation, and so both now
resolve to UNVERIFIABLE rather than VERIFIED unless a Phase 11B-style
`independent_verifier` callback is explicitly supplied and confirms
the claim."""

import pathlib

import pytest

from catalog.coverage.tracker import compute_coverage
from catalog.coverage.verification import VerificationOutcome, verify_evidence
from catalog.importer.build import build_catalog
from catalog.registry import detector_families as detector_families_module
from catalog.registry.detector_families import DetectorFamily
from catalog.schemas.coverage import CapabilityEvidence, CoverageDimension, EvidenceKind

_MANIFEST = build_catalog()
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_exact_reported_fabricated_evidence_is_rejected_not_counted():
    """The literal reproduction from the correction-round report:
    scenario_id=D01-F01, dimension=detection_validated,
    evidence_kind=test_reference,
    evidence_reference='nonexistent-file-does-not-exist.py::test_fake',
    recorded_by='invented' -- must NOT advance detection_validated."""
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.DETECTION_VALIDATED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference="nonexistent-file-does-not-exist.py::test_fake",
            recorded_by="invented",
        )
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["detection_validated"] == 0
    assert report.verified_evidence_count == 0
    assert len(report.rejected_evidence) == 1


def test_fabricated_test_reference_rejected_directly_by_verifier():
    evidence = CapabilityEvidence(
        scenario_id="D01-F01",
        dimension=CoverageDimension.INVESTIGATION_VALIDATED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="nonexistent-file-does-not-exist.py::test_fake",
        recorded_by="invented",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED


def test_existing_but_unexecuted_pytest_test_is_unverifiable_not_verified():
    """Item 10, negative control 1: a real, collectible test node
    that was never actually run (Phase 11A has no execution harness)
    must be UNVERIFIABLE, never VERIFIED -- collection proves
    existence, not execution."""
    evidence = CapabilityEvidence(
        scenario_id="D01-F16",
        dimension=CoverageDimension.TAXONOMY_REVIEWED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_are_flagged",
        recorded_by="phase-11a-correction-round",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.UNVERIFIABLE
    assert "collection alone is never treated as proof of execution" in result.reason


def test_existing_test_unrelated_to_the_claimed_scenario_is_unverifiable():
    """Item 10, negative control 2: a real, collectible test that has
    nothing to do with the claimed scenario_id must also be
    UNVERIFIABLE -- Phase 11A has no scenario-linkage check at all
    (collection cannot distinguish a relevant test from an unrelated
    one), so neither can ever be promoted to VERIFIED."""
    evidence = CapabilityEvidence(
        scenario_id="D01-F01",  # unrelated to what the referenced test actually checks
        dimension=CoverageDimension.TAXONOMY_REVIEWED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="catalog/tests/test_registry.py::test_registry_has_at_least_the_starting_families",
        recorded_by="tester",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.UNVERIFIABLE


def test_bare_file_path_without_specific_test_name_is_rejected():
    """'A test file existing does not automatically prove that test
    validates a specific scenario' -- a reference with no '::test_name'
    is too vague to ever verify, even if the file itself is real."""
    evidence = CapabilityEvidence(
        scenario_id="D01-F16",
        dimension=CoverageDimension.TAXONOMY_REVIEWED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="catalog/tests/test_taxonomy_audit.py",
        recorded_by="tester",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED


def test_nonexistent_test_name_in_a_real_file_is_rejected():
    evidence = CapabilityEvidence(
        scenario_id="D01-F16",
        dimension=CoverageDimension.TAXONOMY_REVIEWED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="catalog/tests/test_taxonomy_audit.py::test_this_test_does_not_exist",
        recorded_by="invented",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED


def test_unregistered_detector_family_reference_is_rejected():
    evidence = CapabilityEvidence(
        scenario_id="D03-F05",
        dimension=CoverageDimension.DETECTOR_IMPLEMENTED,
        evidence_kind=EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE,
        evidence_reference="catalog/registry/detector_families.py::totally_made_up_family",
        recorded_by="invented",
        detector_family_id="totally_made_up_family",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED
    assert "not a registered detector family" in result.reason


def test_registered_but_unimplemented_detector_family_cannot_count_as_detection_validated():
    """A registry description must not count as implemented
    detection: `availability_failures` is a real, registered family
    that remains implemented=False."""
    evidence = CapabilityEvidence(
        scenario_id="D03-F05",
        dimension=CoverageDimension.DETECTION_VALIDATED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="catalog/tests/test_taxonomy_audit.py::test_known_misclassified_scenarios_are_flagged",
        recorded_by="tester",
        detector_family_id="availability_failures",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED
    assert "implemented=True" in result.reason or "not implemented yet" in result.reason


def test_fabricated_evidence_cannot_increase_detector_implemented():
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.DETECTOR_IMPLEMENTED,
            evidence_kind=EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE,
            evidence_reference="totally-fabricated-module.py::FakeDetector",
            recorded_by="invented",
            detector_family_id="availability_failures",  # real family, but not implemented
        ),
        CapabilityEvidence(
            scenario_id="D01-F02",
            dimension=CoverageDimension.DETECTOR_IMPLEMENTED,
            evidence_kind=EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE,
            evidence_reference="also-fabricated.py::AnotherFakeDetector",
            recorded_by="invented",
            detector_family_id="unregistered_fake_family",
        ),
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["detector_implemented"] == 0
    assert report.verified_evidence_count == 0
    assert len(report.rejected_evidence) == 2


def test_fabricated_evidence_cannot_increase_detection_validated():
    evidence = [
        CapabilityEvidence(
            scenario_id=f"D0{i}-F01",
            dimension=CoverageDimension.DETECTION_VALIDATED,
            evidence_kind=EvidenceKind.TEST_REFERENCE,
            evidence_reference=f"nonexistent_{i}.py::test_fake_{i}",
            recorded_by="invented",
        )
        for i in range(1, 6)
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["detection_validated"] == 0
    assert report.verified_evidence_count == 0
    assert len(report.rejected_evidence) == 5


@pytest.mark.parametrize(
    "evidence_kind",
    [
        EvidenceKind.ACCEPTANCE_RESULT,
        EvidenceKind.REVIEWED_POLICY_IDENTIFIER,
        EvidenceKind.RECOVERY_VERIFICATION_ARTIFACT,
    ],
)
def test_evidence_kinds_with_no_trustworthy_verifier_are_always_unverifiable_never_verified(evidence_kind):
    dimension_by_kind = {
        EvidenceKind.ACCEPTANCE_RESULT: CoverageDimension.INVESTIGATION_VALIDATED,
        EvidenceKind.REVIEWED_POLICY_IDENTIFIER: CoverageDimension.REMEDIATION_SUPPORTED,
        EvidenceKind.RECOVERY_VERIFICATION_ARTIFACT: CoverageDimension.RECOVERY_VERIFICATION_VALIDATED,
    }
    evidence = CapabilityEvidence(
        scenario_id="D01-F01",
        dimension=dimension_by_kind[evidence_kind],
        evidence_kind=evidence_kind,
        evidence_reference="some/plausible/looking/reference",
        recorded_by="tester",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.UNVERIFIABLE


def test_unverifiable_evidence_is_reported_but_never_counted_toward_coverage():
    evidence = [
        CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.REMEDIATION_SUPPORTED,
            evidence_kind=EvidenceKind.REVIEWED_POLICY_IDENTIFIER,
            evidence_reference="policy-review-ticket-1234",
            recorded_by="a-human-reviewer",
        )
    ]
    report = compute_coverage(_MANIFEST, evidence)
    assert report.dimension_counts["remediation_supported"] == 0
    assert report.unverifiable_evidence_count == 1
    assert report.verified_evidence_count == 0
    assert report.rejected_evidence == []  # unverifiable is not the same as rejected


def test_dimension_kind_mismatch_is_rejected():
    """A RECOVERY_VERIFICATION_ARTIFACT cannot plausibly back a
    taxonomy_reviewed claim -- rejected before any resolution check."""
    evidence = CapabilityEvidence(
        scenario_id="D01-F01",
        dimension=CoverageDimension.TAXONOMY_REVIEWED,
        evidence_kind=EvidenceKind.RECOVERY_VERIFICATION_ARTIFACT,
        evidence_reference="some-artifact",
        recorded_by="tester",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.REJECTED
    assert "cannot back dimension" in result.reason


def test_registered_implemented_family_alone_is_unverifiable_without_independent_proof():
    """Item 10, negative control 3: a registered detector family with
    implemented=True, but with NO independent implementation proof
    supplied, must be UNVERIFIABLE, never VERIFIED -- registry
    metadata is self-reported, not an independent audit. No real
    family in the Phase 11A registry is implemented yet, so this
    constructs a local, test-only DetectorFamily and monkeypatches the
    registry lookup it goes through -- it never marks a REAL family as
    implemented and never touches the actual registry module's data."""
    fake_implemented_family = DetectorFamily(
        detector_family_id="test_only_implemented_family",
        display_name="Test-only implemented family",
        intended_failure_signals=["x"],
        required_telemetry_sources=["y"],
        detection_prerequisites=["z"],
        expected_observation_schema="schema",
        supported_incident_categories=["cat"],
        gaps_and_limitations=["none -- test fixture"],
        planned_verification_approach="n/a -- test fixture",
        implemented=True,
    )

    import catalog.coverage.verification as verification_module

    original = verification_module.get_detector_family
    try:
        verification_module.get_detector_family = (
            lambda family_id: fake_implemented_family if family_id == "test_only_implemented_family" else original(family_id)
        )
        evidence = CapabilityEvidence(
            scenario_id="D01-F01",
            dimension=CoverageDimension.DETECTOR_IMPLEMENTED,
            evidence_kind=EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE,
            evidence_reference="some/real/module.py::RealDetector",
            recorded_by="tester",
            detector_family_id="test_only_implemented_family",
        )

        # Without an independent_verifier: implemented=True metadata
        # ALONE is not enough -- UNVERIFIABLE, matching item 3 exactly.
        result_without_verifier = verify_evidence(evidence, _REPO_ROOT, independent_verifier=None)
        assert result_without_verifier.outcome == VerificationOutcome.UNVERIFIABLE
        assert "self-reported registry metadata" in result_without_verifier.reason

        # With an independent_verifier that confirms the claim: this
        # is the ONLY path to VERIFIED -- proves the Phase 11B
        # extension point (item 6) genuinely works, not a permanent
        # blanket rejection.
        result_with_verifier = verify_evidence(evidence, _REPO_ROOT, independent_verifier=lambda e: True)
        assert result_with_verifier.outcome == VerificationOutcome.VERIFIED

        # And the hook is a real conditional, not a bypass: a verifier
        # that returns False still does not verify the claim.
        result_with_refusing_verifier = verify_evidence(evidence, _REPO_ROOT, independent_verifier=lambda e: False)
        assert result_with_refusing_verifier.outcome == VerificationOutcome.UNVERIFIABLE
    finally:
        verification_module.get_detector_family = original

    # Confirm the real registry was never actually mutated.
    assert detector_families_module.get_detector_family("test_only_implemented_family") is None
