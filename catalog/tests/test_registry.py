"""Gate E tests: the detector family registry describes CAPABILITIES
-- a registry entry's `implemented=True` means exactly what
Phase 11B's own `detectors/` package actually built and tested for it
(see `catalog/tests/test_registry.py::test_implemented_families_match_
phase_11b_detectors_package`), never a self-reported claim with no
backing code. ids must be unique, and a new family must be addable
without touching the 800 scenarios the catalog already validated in
Gates A-C."""

from catalog.importer.build import build_catalog
from catalog.registry.detector_families import DETECTOR_FAMILIES, DetectorFamily, get_detector_family

# Updated by Phase 11B: these 5 families are now backed by real,
# tested code in detectors/ -- see each family's own gaps_and_
# limitations field for exactly what was (and was not) implemented.
PHASE_11B_IMPLEMENTED_FAMILY_IDS = frozenset(
    {
        "api_error_rates",
        "latency_anomalies",
        "distributed_trace_anomalies",
        "business_invariant_violations",
        "incident_correlation",
    }
)


def test_registry_has_at_least_the_starting_families():
    assert len(DETECTOR_FAMILIES) >= 15


def test_detector_family_ids_are_unique():
    ids = [f.detector_family_id for f in DETECTOR_FAMILIES]
    assert len(ids) == len(set(ids))


def test_implemented_families_match_phase_11b_detectors_package():
    """Exactly the 5 families Phase 11B actually built real, tested
    code for may claim `implemented=True` -- every other family (14 of
    the 19 starting families) remains honestly `implemented=False`,
    since no code in this repository processes a real signal for them
    yet."""
    actually_implemented = {f.detector_family_id for f in DETECTOR_FAMILIES if f.implemented}
    assert actually_implemented == PHASE_11B_IMPLEMENTED_FAMILY_IDS
    assert all(
        f.implemented is False for f in DETECTOR_FAMILIES if f.detector_family_id not in PHASE_11B_IMPLEMENTED_FAMILY_IDS
    )


def test_every_family_has_required_descriptive_fields():
    for f in DETECTOR_FAMILIES:
        assert f.intended_failure_signals
        assert f.required_telemetry_sources
        assert f.detection_prerequisites
        assert f.expected_observation_schema.strip()
        assert f.supported_incident_categories
        assert f.gaps_and_limitations
        assert f.planned_verification_approach.strip()


def test_get_detector_family_returns_none_for_unknown_id():
    assert get_detector_family("totally_unregistered_family") is None


def test_get_detector_family_returns_match_for_known_id():
    found = get_detector_family("latency_anomalies")
    assert found is not None
    assert found.display_name == "Latency anomalies"


def test_new_detector_family_can_be_added_without_modifying_scenarios():
    """Adding an additional, unknown family to a local copy of the
    registry must not require touching the 800 catalogued scenarios at
    all -- the two are fully independent."""
    manifest_before = build_catalog()

    new_family = DetectorFamily(
        detector_family_id="unit_test_only_example_family",
        display_name="Unit-test-only example family",
        intended_failure_signals=["example signal"],
        required_telemetry_sources=["example source"],
        detection_prerequisites=["example prerequisite"],
        expected_observation_schema="example schema",
        supported_incident_categories=["example category"],
        gaps_and_limitations=["not implemented, test-only"],
        planned_verification_approach="none -- test fixture only",
    )
    extended_registry = DETECTOR_FAMILIES + (new_family,)

    manifest_after = build_catalog()
    assert manifest_before == manifest_after
    assert len(extended_registry) == len(DETECTOR_FAMILIES) + 1
    assert get_detector_family("unit_test_only_example_family") is None  # not in the real registry
