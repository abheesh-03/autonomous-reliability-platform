"""A fail-closed boundary between a SUBMITTED `CapabilityEvidence`
claim and an actually VERIFIED one.

Final correction round: `pytest --collect-only` succeeding, or a
detector registry entry carrying `implemented=True`, were both
PREVIOUSLY treated as sufficient to return `VERIFIED`. Neither is: a
collectible test node proves the node EXISTS, never that it was
actually EXECUTED, nor that its assertions are specifically about the
claimed `scenario_id`. Registry `implemented=True` is self-reported
metadata about a capability DESCRIPTION, never independent proof that
an implementation exists and was checked. Phase 11A has no execution
harness and no independent implementation auditor, so BOTH of these
signals now classify as `UNVERIFIABLE`, never `VERIFIED` -- see
`_resolve_test_reference` and `_resolve_detector_implementation_
reference` below.

Three outcomes, unchanged in meaning:

  - `VERIFIED` -- independently, trustworthily confirmed. In Phase 11A
    this requires an explicit `independent_verifier` callback to be
    supplied AND to return `True` for this exact evidence record (see
    below) -- with no callback supplied (the real CLI's default, and
    every real run in this phase), NOTHING reaches `VERIFIED` through
    collection or registry metadata alone, by design.
  - `UNVERIFIABLE` -- a real, resolvable, non-fabricated reference, but
    Phase 11A has no trustworthy way to confirm it actually
    demonstrates the claimed, scenario-specific capability. Not an
    error, not silently dropped, never counted toward coverage.
  - `REJECTED` -- failed an ACTUAL check: a fabricated/nonexistent
    reference, an unregistered detector family, a detector family the
    registry itself says is NOT implemented (an affirmatively false
    claim, not merely an unproven one), or a dimension/evidence-kind
    mismatch.

Phase 11B extension point: `independent_verifier` is a
`Callable[[CapabilityEvidence], bool]` a caller may supply to
`verify_evidence`/`compute_coverage` once a REAL, scenario-linked
execution or implementation auditor exists (e.g. a stored, signed test
run keyed to this exact `scenario_id`, or an independently reviewed
implementation audit record) -- Phase 11A supplies none (`None`
throughout this phase's CLI and tests), and `verify_evidence` never
invents one on its own. This is the ONLY supported way a `TEST_
REFERENCE` or `DETECTOR_IMPLEMENTATION_REFERENCE` can ever reach
`VERIFIED`.

This module still never executes an untrusted reference: the only
subprocess call it ever makes is `pytest --collect-only` (collection,
which imports a module but never invokes a test function body), and
only to confirm a specific node id exists -- it never runs a test, and
it never shells out to anything named by a catalog SOURCE entry (the
800 scenarios' own text is never passed to a subprocess anywhere in
this package)."""

import subprocess
import sys
from enum import Enum
from typing import Callable, Optional

from catalog.registry.detector_families import get_detector_family
from catalog.schemas.coverage import CapabilityEvidence, CoverageDimension, EvidenceKind

IndependentVerifier = Callable[[CapabilityEvidence], bool]


class VerificationOutcome(str, Enum):
    VERIFIED = "verified"
    UNVERIFIABLE = "unverifiable"
    REJECTED = "rejected"


# Which evidence kinds can even plausibly back a claim for each
# dimension -- a hard REJECTED (not merely unverifiable) if violated,
# since this is a structural mismatch, not a missing verifier.
_ALLOWED_KINDS_BY_DIMENSION: dict[CoverageDimension, frozenset[EvidenceKind]] = {
    CoverageDimension.TAXONOMY_REVIEWED: frozenset({EvidenceKind.TEST_REFERENCE, EvidenceKind.REVIEWED_POLICY_IDENTIFIER}),
    CoverageDimension.INSTRUMENTED: frozenset({EvidenceKind.INTEGRATION_FIXTURE, EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE}),
    CoverageDimension.DETECTOR_IMPLEMENTED: frozenset({EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE}),
    CoverageDimension.DETECTION_VALIDATED: frozenset({EvidenceKind.TEST_REFERENCE, EvidenceKind.ACCEPTANCE_RESULT}),
    CoverageDimension.INVESTIGATION_VALIDATED: frozenset({EvidenceKind.TEST_REFERENCE, EvidenceKind.ACCEPTANCE_RESULT}),
    CoverageDimension.REMEDIATION_SUPPORTED: frozenset({EvidenceKind.REVIEWED_POLICY_IDENTIFIER}),
    CoverageDimension.RECOVERY_VERIFICATION_VALIDATED: frozenset({EvidenceKind.RECOVERY_VERIFICATION_ARTIFACT}),
}

# Dimensions that claim a REAL detection capability -- a detector
# family the registry itself marks implemented=False is an
# affirmatively FALSE claim for these, so that combination is REJECTED
# outright, never merely UNVERIFIABLE.
_DIMENSIONS_REQUIRING_IMPLEMENTED_FAMILY = frozenset(
    {CoverageDimension.DETECTOR_IMPLEMENTED, CoverageDimension.DETECTION_VALIDATED}
)

# Evidence kinds Phase 11A has no trustworthy automated verifier for
# at all, regardless of dimension -- always UNVERIFIABLE.
_ALWAYS_UNVERIFIABLE_KINDS = frozenset(
    {
        EvidenceKind.ACCEPTANCE_RESULT,
        EvidenceKind.REVIEWED_POLICY_IDENTIFIER,
        EvidenceKind.RECOVERY_VERIFICATION_ARTIFACT,
        EvidenceKind.INTEGRATION_FIXTURE,
    }
)


class VerificationResult:
    __slots__ = ("outcome", "reason")

    def __init__(self, outcome: VerificationOutcome, reason: str) -> None:
        self.outcome = outcome
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience only
        return f"VerificationResult({self.outcome!r}, {self.reason!r})"


def _test_reference_collects(evidence_reference: str, repo_root) -> bool:
    """Confirms the node id is REAL (not fabricated) -- this is a
    COLLECTION check only (pytest imports the module to discover the
    test; it never invokes the test function body), and existence is
    all it proves. It is never, by itself, treated as proof of
    successful execution or of scenario-specific validation -- see
    `_resolve_test_reference`."""
    if "::" not in evidence_reference:
        return False  # a bare file path is never specific enough -- see module docstring
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", evidence_reference],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _resolve_test_reference(
    evidence: CapabilityEvidence, repo_root, independent_verifier: Optional[IndependentVerifier]
) -> VerificationResult:
    if not _test_reference_collects(evidence.evidence_reference, repo_root):
        return VerificationResult(
            VerificationOutcome.REJECTED,
            f"evidence_reference {evidence.evidence_reference!r} did not resolve via pytest collection "
            "(fabricated, nonexistent, or not a specific 'path::test_name' node id)",
        )

    if evidence.dimension in _DIMENSIONS_REQUIRING_IMPLEMENTED_FAMILY:
        family = get_detector_family(evidence.detector_family_id) if evidence.detector_family_id else None
        if family is None or not family.implemented:
            return VerificationResult(
                VerificationOutcome.REJECTED,
                f"evidence_reference resolved, but dimension {evidence.dimension.value!r} also requires a "
                "registered detector family with implemented=True -- a registry description is not an "
                "implementation, and no family in the Phase 11A starting registry is implemented yet",
            )

    if independent_verifier is not None and independent_verifier(evidence):
        return VerificationResult(
            VerificationOutcome.VERIFIED,
            "an independent, scenario-linked execution verifier confirmed this claim",
        )

    # Collection success alone is deliberately NOT sufficient: it
    # proves the node exists, never that it ran, passed, or that its
    # assertions are actually about this scenario_id.
    return VerificationResult(
        VerificationOutcome.UNVERIFIABLE,
        "evidence_reference resolves to a real, collectible test node, but Phase 11A has no independent "
        "verifier confirming it was actually EXECUTED or that it specifically validates this scenario_id -- "
        "collection alone is never treated as proof of execution or scenario-specific validation",
    )


def _resolve_detector_implementation_reference(
    evidence: CapabilityEvidence, independent_verifier: Optional[IndependentVerifier]
) -> VerificationResult:
    if evidence.dimension in _DIMENSIONS_REQUIRING_IMPLEMENTED_FAMILY:
        family = get_detector_family(evidence.detector_family_id) if evidence.detector_family_id else None
        if family is None or not family.implemented:
            return VerificationResult(
                VerificationOutcome.REJECTED,
                f"dimension {evidence.dimension.value!r} requires a registered detector family with "
                "implemented=True -- a registry description is not an implementation, and no family in "
                "the Phase 11A starting registry is implemented yet",
            )

    family = get_detector_family(evidence.detector_family_id) if evidence.detector_family_id else None
    if family is None or not family.implemented:
        return VerificationResult(
            VerificationOutcome.UNVERIFIABLE,
            "references a registered but not-yet-implemented detector family -- a registry description alone "
            "is not verifiable proof of instrumentation",
        )

    if independent_verifier is not None and independent_verifier(evidence):
        return VerificationResult(
            VerificationOutcome.VERIFIED,
            "an independent implementation auditor confirmed this claim",
        )

    # implemented=True is self-reported registry metadata, never
    # independent proof that an implementation exists and was audited.
    return VerificationResult(
        VerificationOutcome.UNVERIFIABLE,
        f"detector family {evidence.detector_family_id!r} is registered with implemented=True, but that is "
        "self-reported registry metadata, not independent implementation proof -- Phase 11A has no "
        "independent implementation auditor wired in yet",
    )


def verify_evidence(
    evidence: CapabilityEvidence,
    repo_root,
    independent_verifier: Optional[IndependentVerifier] = None,
) -> VerificationResult:
    """`independent_verifier` is the Phase 11B extension point (see
    module docstring) -- Phase 11A's own CLI and tests pass `None`
    except where a test explicitly exercises the hook itself."""
    allowed_kinds = _ALLOWED_KINDS_BY_DIMENSION[evidence.dimension]
    if evidence.evidence_kind not in allowed_kinds:
        return VerificationResult(
            VerificationOutcome.REJECTED,
            f"evidence_kind {evidence.evidence_kind.value!r} cannot back dimension {evidence.dimension.value!r} "
            f"(allowed: {sorted(k.value for k in allowed_kinds)})",
        )

    if evidence.detector_family_id is not None and get_detector_family(evidence.detector_family_id) is None:
        return VerificationResult(
            VerificationOutcome.REJECTED,
            f"detector_family_id {evidence.detector_family_id!r} is not a registered detector family",
        )

    if evidence.evidence_kind == EvidenceKind.TEST_REFERENCE:
        return _resolve_test_reference(evidence, repo_root, independent_verifier)

    if evidence.evidence_kind == EvidenceKind.DETECTOR_IMPLEMENTATION_REFERENCE:
        return _resolve_detector_implementation_reference(evidence, independent_verifier)

    if evidence.evidence_kind in _ALWAYS_UNVERIFIABLE_KINDS:
        return VerificationResult(
            VerificationOutcome.UNVERIFIABLE,
            f"no trustworthy automated verifier exists in Phase 11A for evidence_kind "
            f"{evidence.evidence_kind.value!r} yet",
        )

    raise AssertionError(f"unhandled evidence_kind {evidence.evidence_kind!r} -- every kind must be classified")
