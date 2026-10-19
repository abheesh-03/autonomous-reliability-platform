"""Dispatch from a Case's `evaluation_mode` to its scoring function.
Each scorer is an `async def (case: Case) -> CaseResult` -- see the
sibling module docstrings for exactly which production code each one
reuses."""

from collections.abc import Awaitable, Callable

from evals.scoring.adversarial_deterministic import score_adversarial_deterministic_case
from evals.scoring.citation import score_citation_case
from evals.scoring.investigation_quality import score_investigation_quality_case
from evals.scoring.models import Case, CaseResult
from evals.scoring.remediation_safety import score_remediation_safety_case
from evals.scoring.retrieval import score_retrieval_case

SCORERS: dict[str, Callable[[Case], Awaitable[CaseResult]]] = {
    "citation": score_citation_case,
    "retrieval": score_retrieval_case,
    "investigation_quality": score_investigation_quality_case,
    "remediation_safety": score_remediation_safety_case,
    "adversarial_deterministic": score_adversarial_deterministic_case,
}


async def score_case(case: Case) -> CaseResult:
    scorer = SCORERS.get(case.evaluation_mode)
    if scorer is None:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result="NOT_EVALUATED",
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"no scorer registered for evaluation_mode={case.evaluation_mode!r}",
        )
    return await scorer(case)
