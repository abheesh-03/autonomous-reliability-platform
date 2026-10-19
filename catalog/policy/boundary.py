"""Gate G: explicit, testable assertions that the catalog's own
`original_automation_label` field (and, more broadly, nothing in this
`catalog/` package) can ever authorize an autonomous action.

This module does not implement or modify the real Phase 8/9
deterministic remediation/human-approval system -- it only asserts, in
one obvious place, the boundary that system already enforces, so a
future caller (Phase 11B or later) has a single, named thing to import
and check against rather than re-deriving this reasoning ad hoc.
"""

from enum import Enum

FORBIDDEN_ACTION_CATEGORIES: tuple[str, ...] = (
    "payment_movement",
    "refund_issuance",
    "database_destructive_write",
    "credential_change",
    "access_change",
    "arbitrary_code_execution",
    "infrastructure_mutation",
    "physical_actuator_control",
    "medical_decision_automation",
)

# Matches the sensitive-domain list used by `catalog/reviews/audit.py`'s
# safety-critical-automation-label heuristic -- defined once, here, and
# imported by that module rather than duplicated.
SENSITIVE_DOMAINS: frozenset[str] = frozenset(
    {
        "FinTech",
        "Banking",
        "Investment Banking",
        "InsurTech",
        "HealthTech",
        "MedTech",
        "Biotech",
        "Cybersecurity",
        "Aerospace & Defense",
        "EnergyTech",
        "Industrial Tech",
        "Robotics",
        "GovTech",
        "RegTech",
    }
)


class AutomationLabelTrust(str, Enum):
    """What the source catalog's own `original_automation_label` value
    is allowed to mean to any consumer of this package."""

    UNTRUSTED_DOCUMENTATION = "untrusted_documentation"


def automation_label_trust_level(_original_automation_label: str) -> AutomationLabelTrust:
    """Returns the ONLY trust level this package will ever assign to a
    source automation label, regardless of its text -- including the
    most permissive-sounding value, 'Guarded automatic action'. The
    argument is intentionally unused: no automation label string, no
    matter its wording, changes this answer. Callers must treat this as
    a constant, not as something that varies by label text."""
    return AutomationLabelTrust.UNTRUSTED_DOCUMENTATION


def assert_label_never_authorizes_execution(original_automation_label: str) -> None:
    """A structural assertion, not a runtime permission check: calling
    this never raises, by design, because the answer can never depend
    on the label's text -- it exists so a caller can make the
    assertion explicit and testable at the point where a label is
    read, rather than relying on convention."""
    assert automation_label_trust_level(original_automation_label) == AutomationLabelTrust.UNTRUSTED_DOCUMENTATION


def is_sensitive_domain(domain_name: str) -> bool:
    return domain_name in SENSITIVE_DOMAINS


def is_forbidden_action_category(action_category: str) -> bool:
    return action_category in FORBIDDEN_ACTION_CATEGORIES
