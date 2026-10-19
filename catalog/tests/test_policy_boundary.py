"""Gate G tests: no automation-label text, including the source's own
most permissive label, may ever be treated as execution authorization.
These are structural/API assertions, not integration tests against the
real Phase 8/9 remediation system (which this package never touches)."""

from catalog.importer.build import build_catalog
from catalog.policy.boundary import (
    AutomationLabelTrust,
    FORBIDDEN_ACTION_CATEGORIES,
    assert_label_never_authorizes_execution,
    automation_label_trust_level,
    is_forbidden_action_category,
    is_sensitive_domain,
)

_MANIFEST = build_catalog()


def test_every_distinct_automation_label_in_the_real_catalog_is_untrusted():
    labels = {s.original_automation_label for s in _MANIFEST.scenarios}
    assert labels  # sanity: the real catalog does have automation labels
    for label in labels:
        assert automation_label_trust_level(label) == AutomationLabelTrust.UNTRUSTED_DOCUMENTATION


def test_guarded_automatic_action_label_specifically_is_still_untrusted():
    """The named edge case: a source entry labeled 'Guarded automatic
    action' must not be treated any differently from any other label."""
    assert automation_label_trust_level("Guarded automatic action") == AutomationLabelTrust.UNTRUSTED_DOCUMENTATION


def test_assert_label_never_authorizes_execution_never_raises_for_any_real_label():
    labels = {s.original_automation_label for s in _MANIFEST.scenarios}
    for label in labels:
        assert_label_never_authorizes_execution(label)  # must not raise


def test_forbidden_action_categories_include_the_gate_g_named_examples():
    required = {
        "payment_movement",
        "refund_issuance",
        "database_destructive_write",
        "credential_change",
        "access_change",
        "arbitrary_code_execution",
        "infrastructure_mutation",
        "physical_actuator_control",
        "medical_decision_automation",
    }
    assert required.issubset(set(FORBIDDEN_ACTION_CATEGORIES))


def test_is_forbidden_action_category_rejects_known_categories_and_allows_unknown_strings():
    assert is_forbidden_action_category("payment_movement") is True
    assert is_forbidden_action_category("send_a_read_only_diagnostic_query") is False


def test_sensitive_domains_cover_all_six_named_sensitive_sectors():
    banking = any(is_sensitive_domain(d) for d in ("FinTech", "Banking", "Investment Banking", "InsurTech"))
    healthcare = any(is_sensitive_domain(d) for d in ("HealthTech", "MedTech", "Biotech"))
    security = is_sensitive_domain("Cybersecurity")
    aviation = is_sensitive_domain("Aerospace & Defense")
    energy = any(is_sensitive_domain(d) for d in ("EnergyTech", "Industrial Tech", "Robotics"))
    government = any(is_sensitive_domain(d) for d in ("GovTech", "RegTech"))
    assert all([banking, healthcare, security, aviation, energy, government])


def test_sensitive_domain_names_actually_exist_in_the_real_catalog():
    """Guards against the sensitive-domain list silently drifting out
    of sync with the real source's own domain names."""
    real_domain_names = {s.domain_name for s in _MANIFEST.scenarios}
    from catalog.policy.boundary import SENSITIVE_DOMAINS

    matched = SENSITIVE_DOMAINS & real_domain_names
    assert matched, "none of the configured sensitive domain names matched any real catalog domain name"
