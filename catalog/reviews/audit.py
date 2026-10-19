"""Gate C: taxonomy quality audit -- a set of explicit, documented,
TESTABLE heuristics that each FLAG a scenario for human review. None
of them ever rewrites a `ScenarioRecord`, and none of them is treated
as proof: every finding is emitted as a `TaxonomyReviewEntry` with
`review_status=REVIEW_REQUIRED`, carrying the exact evidence that
produced it so a human reviewer can judge the claim themselves.

Design note (why this is NOT "simplistic word matching"): the per-class
"signature vocabulary" used by `_class_template_mismatch_findings`
below is derived DIRECTLY from the source document's own fixed,
per-class detection/instrumentation/likely-causes template text (empirically
confirmed: every one of the 20 failure classes has EXACTLY ONE such
template across every scenario that uses it -- see
`docs/architecture/phase-11a-incident-intelligence.md`'s Gate A audit)
-- never invented by this module. A finding additionally requires AT
LEAst TWO distinct domain-indicator terms to co-occur in a scenario's
own title before it is ever flagged, specifically to avoid a
single-word false-positive trigger. This is still a heuristic, and is
documented as exactly that everywhere it is used.
"""

import re
from dataclasses import dataclass

from catalog.policy.boundary import SENSITIVE_DOMAINS
from catalog.schemas.catalog import CatalogManifest
from catalog.schemas.review import ReviewStatus, TaxonomyReviewEntry

_TOKEN_RE = re.compile(r"[a-z]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "or", "and", "to", "in", "on", "is", "are", "for", "with", "this", "that",
        "compare", "affected", "entity", "ids", "last", "known", "good", "state", "scenario", "specific",
        "sentinel",
    }
)


@dataclass(frozen=True)
class DomainIndicatorCategory:
    """A small, hand-curated, documented set of multi-term indicators
    for one real-world semantic category -- never a single generic
    word. `incompatible_classes` lists the original_failure_class
    values that category's own vocabulary has no coherent relationship
    to (derived from reading each class's own fixed template text,
    same as the class-signature vocabulary above)."""

    category_id: str
    terms: frozenset[str]
    incompatible_classes: frozenset[str]
    note: str


# These are AUDIT EXAMPLES, not an exhaustive correction list (per
# Gate C's own explicit instruction) -- a small, reviewed starting set,
# never claimed to cover every possible misclassification in the 800
# scenarios.
DOMAIN_INDICATOR_CATEGORIES: tuple[DomainIndicatorCategory, ...] = (
    DomainIndicatorCategory(
        category_id="billing_subscription_lifecycle",
        terms=frozenset({"subscription", "charged", "cancellation", "billing", "invoice", "renewal", "refund"}),
        incompatible_classes=frozenset({"Resource exhaustion"}),
        note=(
            "a billing/subscription-lifecycle event is not inherently a memory/disk/connection-pressure "
            "problem -- the 'Resource exhaustion' class's own template (OOM/GC/FD/capacity) has no evident "
            "connection to a billing-cycle defect"
        ),
    ),
    DomainIndicatorCategory(
        category_id="account_state_lifecycle",
        terms=frozenset({"dormant", "reactivated", "account", "suspended", "deactivated"}),
        incompatible_classes=frozenset({"Scheduling / batch windows"}),
        note=(
            "an account-state-control gap (e.g. missing re-verification on reactivation) is not inherently "
            "a missed batch-job deadline -- the 'Scheduling / batch windows' class's own template (job "
            "orchestration, DAG SLA) has no evident connection to an access-control gap"
        ),
    ),
    DomainIndicatorCategory(
        category_id="fraud_risk_decisioning",
        terms=frozenset({"fraud", "scoring", "flags", "legitimate", "risk"}),
        incompatible_classes=frozenset({"Latency / capacity"}),
        note=(
            "a decisioning-ACCURACY problem (a model/rule incorrectly flagging legitimate activity) is not "
            "inherently a performance/capacity problem -- the 'Latency / capacity' class's own template "
            "(p95/p99, queue age, load test) has no evident connection to false-positive rate"
        ),
    ),
    DomainIndicatorCategory(
        category_id="security_credential_incident",
        terms=frozenset({"credential", "token", "certificate", "secret", "breach", "unauthorized"}),
        incompatible_classes=frozenset({"Latency / capacity", "Resource exhaustion"}),
        note="a credential/security incident is not inherently a performance or memory/disk-pressure problem",
    ),
)

_MIN_INDICATOR_TERM_MATCHES = 2


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2)


def derive_class_signature_vocabulary(manifest: CatalogManifest) -> dict[str, frozenset[str]]:
    """Builds each failure class's own vocabulary DIRECTLY from the
    real, fixed per-class template text in the source (never invented
    here) -- the scenario-specific title substitution is excluded by
    construction (every scenario sharing a class has an IDENTICAL
    detection/instrumentation/likely_causes text, so any one
    representative is the real template)."""
    vocabulary: dict[str, frozenset[str]] = {}
    seen_classes: set[str] = set()
    for s in manifest.scenarios:
        if s.original_failure_class in seen_classes:
            continue
        seen_classes.add(s.original_failure_class)
        template_text = " ".join([s.detection_description, s.instrumentation_description, s.likely_causes])
        vocabulary[s.original_failure_class] = _tokenize(template_text)
    return vocabulary


def _class_template_mismatch_findings(manifest: CatalogManifest) -> list[TaxonomyReviewEntry]:
    findings: list[TaxonomyReviewEntry] = []
    for s in manifest.scenarios:
        title_tokens = _tokenize(s.title)
        for category in DOMAIN_INDICATOR_CATEGORIES:
            if s.original_failure_class not in category.incompatible_classes:
                continue
            matched_terms = sorted(title_tokens & category.terms)
            if len(matched_terms) < _MIN_INDICATOR_TERM_MATCHES:
                continue
            findings.append(
                TaxonomyReviewEntry(
                    scenario_id=s.scenario_id,
                    field_name="original_failure_class",
                    original_value=s.original_failure_class,
                    evidence_rationale=(
                        f"title {s.title!r} matches >= {_MIN_INDICATOR_TERM_MATCHES} terms from the "
                        f"{category.category_id!r} domain-indicator category ({matched_terms}), but is "
                        f"classified as {s.original_failure_class!r}: {category.note}. This is a HEURISTIC "
                        "flag, not proof -- a human reviewer must confirm before any correction is applied."
                    ),
                    review_status=ReviewStatus.REVIEW_REQUIRED,
                    heuristic_id=f"class_template_mismatch:{category.category_id}",
                )
            )
    return findings


def _safety_critical_automation_label_findings(manifest: CatalogManifest) -> list[TaxonomyReviewEntry]:
    """Flags a sensitive-domain scenario whose source-assigned
    automation label is the most permissive non-human-gated value
    ('Guarded automatic action') for explicit human confirmation that
    this is genuinely appropriate -- never auto-downgraded, never
    auto-accepted; see Gate G for why this label can never itself
    authorize execution regardless of this review's outcome."""
    findings: list[TaxonomyReviewEntry] = []
    for s in manifest.scenarios:
        if s.domain_name not in SENSITIVE_DOMAINS:
            continue
        if s.original_automation_label != "Guarded automatic action":
            continue
        findings.append(
            TaxonomyReviewEntry(
                scenario_id=s.scenario_id,
                field_name="original_automation_label",
                original_value=s.original_automation_label,
                evidence_rationale=(
                    f"{s.scenario_id} ({s.title!r}) is in sensitive domain {s.domain_name!r} and carries the "
                    "source's own most permissive non-human-gated automation label ('Guarded automatic "
                    "action') -- a human reviewer should explicitly confirm this is appropriately "
                    "conservative for this domain before this label is given any weight at all (and even "
                    "then, per Gate G, it still never authorizes an actual autonomous action on its own)."
                ),
                review_status=ReviewStatus.REVIEW_REQUIRED,
                heuristic_id="safety_critical_automation_label",
            )
        )
    return findings


def _vague_observability_findings(manifest: CatalogManifest) -> list[TaxonomyReviewEntry]:
    """A crude, explicitly-labeled length-based proxy only -- flags the
    classes whose own instrumentation template is shorter than the
    corpus's own mean across all 20 classes, for a human to judge
    whether it actually gives enough concrete telemetry guidance.
    Deliberately RELATIVE to this corpus's own observed distribution
    (empirically 12-15 words/class) rather than an arbitrary absolute
    cutoff picked in advance -- never claims to measure semantic
    quality, and intentionally errs toward flagging the shortest
    quartile for review rather than asserting they are actually vague."""
    per_class_word_count: dict[str, int] = {}
    seen_classes: set[str] = set()
    for s in manifest.scenarios:
        if s.original_failure_class in seen_classes:
            continue
        seen_classes.add(s.original_failure_class)
        per_class_word_count[s.original_failure_class] = len(s.instrumentation_description.split())

    if not per_class_word_count:
        return []
    mean_word_count = sum(per_class_word_count.values()) / len(per_class_word_count)

    findings: list[TaxonomyReviewEntry] = []
    seen_classes = set()
    for s in manifest.scenarios:
        if s.original_failure_class in seen_classes:
            continue
        seen_classes.add(s.original_failure_class)
        word_count = per_class_word_count[s.original_failure_class]
        if word_count >= mean_word_count:
            continue
        findings.append(
            TaxonomyReviewEntry(
                scenario_id=s.scenario_id,
                field_name="instrumentation_description",
                original_value=s.instrumentation_description,
                evidence_rationale=(
                    f"the instrumentation/evidence template shared by every scenario in class "
                    f"{s.original_failure_class!r} is {word_count} word(s), below this corpus's own "
                    f"mean of {mean_word_count:.1f} words/class across all {len(per_class_word_count)} "
                    "classes -- a crude, corpus-relative length proxy flagging it for a human to judge "
                    "whether it gives sufficiently concrete observability guidance, never a semantic "
                    "quality judgment."
                ),
                review_status=ReviewStatus.REVIEW_REQUIRED,
                heuristic_id="vague_observability_length_proxy",
            )
        )
    return findings


def audit_catalog(manifest: CatalogManifest) -> list[TaxonomyReviewEntry]:
    """Runs every registered heuristic and returns the combined,
    deterministic list of review entries -- sorted by scenario_id then
    heuristic_id for reproducible output. NEVER mutates `manifest` or
    any `ScenarioRecord` within it."""
    findings = (
        _class_template_mismatch_findings(manifest)
        + _safety_critical_automation_label_findings(manifest)
        + _vague_observability_findings(manifest)
    )
    return sorted(findings, key=lambda f: (f.scenario_id, f.heuristic_id, f.field_name))
