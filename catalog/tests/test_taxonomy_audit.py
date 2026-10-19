"""Gate C tests: the taxonomy quality audit must flag the known
problem scenarios (verified, verbatim, against the real source in this
session), must NOT flag a clearly coherent scenario, and must NEVER
mutate the underlying `ScenarioRecord` data -- it only ever produces
`TaxonomyReviewEntry` records awaiting human review."""

import copy

from catalog.importer.build import build_catalog
from catalog.reviews.audit import audit_catalog, derive_class_signature_vocabulary
from catalog.schemas.review import ReviewStatus, TaxonomyReviewEntry

_MANIFEST = build_catalog()
_FINDINGS = audit_catalog(_MANIFEST)
_FLAGGED_IDS = {f.scenario_id for f in _FINDINGS}


def test_known_misclassified_scenarios_are_flagged():
    """D01-F16, D02-F10, D04-F06 are the named Gate C audit examples
    -- a subscription/billing scenario classified as 'Resource
    exhaustion', an account-reactivation scenario classified as
    'Scheduling / batch windows', and a fraud-scoring-accuracy scenario
    classified as 'Latency / capacity'. All three must be flagged."""
    for scenario_id in ("D01-F16", "D02-F10", "D04-F06"):
        assert scenario_id in _FLAGGED_IDS, f"{scenario_id} was not flagged by any heuristic"


def test_known_misclassified_scenarios_flagged_on_failure_class_field():
    by_id = {f.scenario_id: f for f in _FINDINGS if f.heuristic_id.startswith("class_template_mismatch:")}
    assert by_id["D01-F16"].field_name == "original_failure_class"
    assert by_id["D01-F16"].original_value == "Resource exhaustion"
    assert by_id["D02-F10"].original_value == "Scheduling / batch windows"
    assert by_id["D04-F06"].original_value == "Latency / capacity"


def test_coherent_scenario_is_not_flagged_by_class_template_mismatch():
    """D01-F01 is a normal, coherently-classified scenario and must
    not be flagged by the class/title mismatch heuristic."""
    coherent_findings = [
        f for f in _FINDINGS if f.scenario_id == "D01-F01" and f.heuristic_id.startswith("class_template_mismatch:")
    ]
    assert coherent_findings == []


def test_every_finding_defaults_to_review_required():
    assert all(f.review_status == ReviewStatus.REVIEW_REQUIRED for f in _FINDINGS)


def test_every_finding_carries_a_heuristic_id_and_rationale():
    assert all(f.heuristic_id for f in _FINDINGS)
    assert all(f.evidence_rationale.strip() for f in _FINDINGS)


def test_no_finding_ever_sets_suggested_correction_automatically():
    """The heuristic engine itself must never invent a 'correct' value
    -- only a human reviewer may ever populate `suggested_correction`."""
    assert all(f.suggested_correction is None for f in _FINDINGS)


def test_audit_never_mutates_the_manifest():
    before = copy.deepcopy(_MANIFEST)
    audit_catalog(_MANIFEST)
    assert _MANIFEST == before


def test_audit_is_deterministic():
    findings_a = audit_catalog(_MANIFEST)
    findings_b = audit_catalog(_MANIFEST)
    assert findings_a == findings_b


def test_class_signature_vocabulary_covers_all_20_classes():
    vocab = derive_class_signature_vocabulary(_MANIFEST)
    assert len(vocab) == 20
    assert all(isinstance(v, frozenset) and v for v in vocab.values())


def test_safety_critical_automation_label_only_flags_sensitive_domains_with_guarded_label():
    safety_findings = [f for f in _FINDINGS if f.heuristic_id == "safety_critical_automation_label"]
    assert safety_findings  # must produce at least one real finding on the real catalog
    by_id = {s.scenario_id: s for s in _MANIFEST.scenarios}
    for f in safety_findings:
        scenario = by_id[f.scenario_id]
        assert scenario.original_automation_label == "Guarded automatic action"


def test_vague_observability_proxy_is_relative_not_an_arbitrary_absolute_cutoff():
    """Confirms the heuristic actually discriminates on this corpus
    (neither 0 nor all 20 classes flagged) -- an inert or
    everything-flagged heuristic would not be a meaningful test."""
    vague_findings = [f for f in _FINDINGS if f.heuristic_id == "vague_observability_length_proxy"]
    flagged_classes = {
        s.original_failure_class
        for s in _MANIFEST.scenarios
        if s.scenario_id in {f.scenario_id for f in vague_findings}
    }
    assert 0 < len(flagged_classes) < 20


def test_review_entry_schema_rejects_unknown_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TaxonomyReviewEntry(
            scenario_id="D01-F01",
            field_name="original_failure_class",
            original_value="x",
            evidence_rationale="y",
            heuristic_id="z",
            unexpected_field="not allowed",
        )
