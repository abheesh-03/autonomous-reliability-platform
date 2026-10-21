"""Gate K: demonstrates real, cross-package integration with Phase
11A's catalog coverage tracker -- and confirms its independent
evidence-verification boundary (`catalog.coverage.verification`)
holds even for genuinely real, tested Phase 11B capabilities.

Deliberately NOT a sweeping coverage claim: Phase 11B's detectors
(error-rate/latency deviation, dependency-graph analysis, lifecycle
invariants, correlation) are GENERAL-PURPOSE mechanisms that do not
target specific catalog scenario_ids -- forcing them onto an arbitrary
scenario would be an artificial, ill-fitting mapping, not honest
evidence. This test submits exactly ONE real `CapabilityEvidence`
record, pointing at an ACTUAL, PASSING test
(`detectors/tests/test_anomaly_detector.py::
test_sustained_latency_increase_is_anomaly_detected`), tagged to one
real catalog scenario whose own failure class plausibly overlaps with
latency detection (D01-F02, classified 'Availability / timeouts'), for
the `latency_anomalies` family (now `implemented=True`, backed by real
code -- see `catalog/registry/detector_families.py`).

The result MUST be UNVERIFIABLE, never VERIFIED -- per the Phase 11A
correction round, mere test-reference collection is never sufficient
proof of execution or scenario-specific validation, regardless of how
real and passing the underlying test is. This is the honest, correct
outcome: Phase 11B's real capabilities are tracked via the registry's
own evidence-backed `implemented` flags (see
`catalog/tests/test_registry.py::
test_implemented_families_match_phase_11b_detectors_package`) and via
`detectors/`'s OWN test suite -- NOT via a false per-scenario
`detector_implemented`/`detection_validated` promotion in the 800-
scenario catalog tracker, which must stay honestly at zero for any
claim lacking an independent, scenario-linked verifier (Phase 11B
supplies none)."""

import pathlib

from catalog.coverage.tracker import compute_coverage
from catalog.coverage.verification import VerificationOutcome, verify_evidence
from catalog.importer.build import build_catalog
from catalog.registry.detector_families import get_detector_family
from catalog.schemas.coverage import CapabilityEvidence, CoverageDimension, EvidenceKind

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_latency_anomalies_family_is_honestly_marked_implemented():
    family = get_detector_family("latency_anomalies")
    assert family is not None
    assert family.implemented is True


def test_real_evidence_for_a_genuinely_implemented_family_is_still_unverifiable_not_verified():
    manifest = build_catalog()
    evidence = CapabilityEvidence(
        scenario_id="D01-F02",  # "Payment authorization timeout after issuer approval" -- Availability / timeouts
        dimension=CoverageDimension.DETECTION_VALIDATED,
        evidence_kind=EvidenceKind.TEST_REFERENCE,
        evidence_reference="detectors/tests/test_anomaly_detector.py::test_sustained_latency_increase_is_anomaly_detected",
        recorded_by="phase-11b-gate-k-integration",
        detector_family_id="latency_anomalies",
    )
    result = verify_evidence(evidence, _REPO_ROOT)
    assert result.outcome == VerificationOutcome.UNVERIFIABLE

    report = compute_coverage(manifest, [evidence])
    assert report.dimension_counts["detection_validated"] == 0
    assert report.verified_evidence_count == 0
    assert report.unverifiable_evidence_count == 1
    assert report.rejected_evidence == []


def test_phase_11b_capability_is_tracked_separately_not_via_scenario_coverage_inflation():
    """The 800-scenario catalog's own coverage report must never
    reflect Phase 11B's real capabilities as scenario-level coverage --
    those are tracked via the registry's `implemented` flags and
    detectors/'s own test suite instead (see this module's own
    docstring)."""
    manifest = build_catalog()
    report = compute_coverage(manifest, evidence=[])
    assert report.dimension_counts["detector_implemented"] == 0
    assert report.dimension_counts["detection_validated"] == 0
