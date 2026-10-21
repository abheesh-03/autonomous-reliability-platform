"""Gate D framework tests: plugin extensibility, and ONE synthetic,
test-only example invariant exercising a known-safe payment-service
response shape (NOT a claim about real ledger/stock correctness --
see `detectors/invariants/framework.py`'s own docstring for why no
real payment/inventory checker was implemented)."""

from datetime import UTC, datetime, timedelta

import pytest

from detectors.invariants.framework import InvariantRegistry
from detectors.invariants.lifecycle_checker import INVARIANT_DEFINITION as LIFECYCLE_DEFINITION
from detectors.schemas.invariant import (
    InvariantCheckReport,
    InvariantCheckResult,
    InvariantDefinition,
    InvariantViolation,
)

WINDOW_START = datetime(2026, 6, 1, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)

# A SYNTHETIC-only example: the real AuthorizePaymentResponse contract
# (services/payment_service/src/payment_service/models/payment.py)
# always returns status: Literal["AUTHORIZED"] -- this checks that
# contract SHAPE against a fixed, known-safe fixture set, never a real
# ledger/balance/duplicate-settlement claim (payment-service persists
# nothing queryable after the fact, so no real source exists for that).
SYNTHETIC_DEFINITION = InvariantDefinition(
    invariant_id="synthetic_payment_authorization_contract_shape",
    description="test-only: every AuthorizePaymentResponse fixture reports status='AUTHORIZED'",
    required_sources=["synthetic fixture only -- no real payment-service history exists to query"],
    scope="synthetic fixture",
    expected_condition="response.status == 'AUTHORIZED'",
    completeness_prerequisites=["fixture set is fixed and complete by construction"],
    evidence_required=["fixture record"],
    severity_hint="low -- demonstration only",
    verification_method="direct field comparison",
)


async def _synthetic_checker(window_start: datetime, window_end: datetime) -> InvariantCheckReport:
    fixtures = [{"status": "AUTHORIZED"}, {"status": "AUTHORIZED"}]
    violations = [
        InvariantViolation(subject_id=str(i), explanation=f"status was {f['status']!r}, not 'AUTHORIZED'", evidence_reference="synthetic fixture")
        for i, f in enumerate(fixtures)
        if f["status"] != "AUTHORIZED"
    ]
    result = InvariantCheckResult.VIOLATED if violations else InvariantCheckResult.SATISFIED
    return InvariantCheckReport(
        invariant_id=SYNTHETIC_DEFINITION.invariant_id,
        checked_observation_window_start=window_start.isoformat(),
        checked_observation_window_end=window_end.isoformat(),
        result=result,
        subjects_checked=len(fixtures),
        violations=violations,
        explanation="synthetic fixture demonstration only",
        evidence_provenance=["synthetic fixture"],
    )


async def test_registry_can_register_and_run_multiple_checkers_without_engine_changes():
    registry = InvariantRegistry()
    registry.register(SYNTHETIC_DEFINITION, _synthetic_checker)
    reports = await registry.run_all(WINDOW_START, WINDOW_END)
    assert len(reports) == 1
    assert reports[0].result == InvariantCheckResult.SATISFIED


async def test_registry_rejects_duplicate_invariant_ids():
    registry = InvariantRegistry()
    registry.register(SYNTHETIC_DEFINITION, _synthetic_checker)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(SYNTHETIC_DEFINITION, _synthetic_checker)


async def test_real_lifecycle_invariant_can_coexist_with_a_synthetic_one():
    """Proves a real, evidence-backed checker and a synthetic
    demonstration checker can both be registered in the same engine
    without any rewrite."""
    registry = InvariantRegistry()
    registry.register(SYNTHETIC_DEFINITION, _synthetic_checker)

    async def _lifecycle_stub(window_start: datetime, window_end: datetime) -> InvariantCheckReport:
        return InvariantCheckReport(
            invariant_id=LIFECYCLE_DEFINITION.invariant_id,
            checked_observation_window_start=window_start.isoformat(),
            checked_observation_window_end=window_end.isoformat(),
            result=InvariantCheckResult.INSUFFICIENT_EVIDENCE,
            subjects_checked=0,
            violations=[],
            explanation="stub for this test only",
            evidence_provenance=[],
        )

    registry.register(LIFECYCLE_DEFINITION, _lifecycle_stub)
    reports = await registry.run_all(WINDOW_START, WINDOW_END)
    assert {r.invariant_id for r in reports} == {
        SYNTHETIC_DEFINITION.invariant_id,
        LIFECYCLE_DEFINITION.invariant_id,
    }
