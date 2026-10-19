"""Investigation-quality scoring -- Gate C requirement C.

Reuses agent-runtime-service's REAL, production, deterministic
orchestration-level classifier directly:
`agent_runtime_service.graph.nodes.classify_investigation`. This is
the exact function Phase 7's `evaluate_investigation` graph node calls
in production -- never a reimplementation of its
well_supported/partial/inconclusive rules.

Also reuses investigator-service's own canonical `InvestigationReport`
model to validate a case's input report is REAL-shaped (not a
hand-waved dict any citation/validation code never actually produces)
before classification -- a case whose input cannot even be parsed as
a real report is NOT_EVALUATED, never scored against a shape it does
not have.

A rubric check beyond the bare classification label (Gate C explicitly
permits this ONLY when "a curated ground-truth rubric establishes"
the expectation -- this module never free-text-judges prose):
"forbidden_high_confidence_without_evidence" re-verifies, from the
report's OWN already-validated structure, that no surviving hypothesis
is confidence="high" with empty supporting_evidence_ids. Production
validation (investigator_service.llm.validation) already guarantees
this for any report that passed through it -- this check exists to
catch a case author (or a future report producer) that bypasses that
validation, not to claim this module itself detects hallucination in
free text. This module explicitly does NOT attempt open-ended
hallucination detection on prose; see evals/README.md.

A case's `input`: {"investigation_report": {...}} (a real, canonical
InvestigationReport-shaped dict).

A case's `expected_outcome`:
  - "expected_classification": "well_supported" | "partial" | "inconclusive"
  - "require_missing_evidence_present": bool (optional)
  - "forbidden_high_confidence_without_evidence": bool (optional, default true)
"""

from agent_runtime_service.graph.nodes import classify_investigation
from investigator_service.domain.investigation import InvestigationReport

from evals.scoring.models import Case, CaseResult, Result


async def score_investigation_quality_case(case: Case) -> CaseResult:
    try:
        report_model = InvestigationReport.model_validate(case.input["investigation_report"])
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"case input is not a real-shaped InvestigationReport: {exc}",
        )

    report = report_model.model_dump(mode="json")
    classification = classify_investigation(report)

    failures: list[str] = []
    expected = case.expected_outcome

    expected_classification = expected.get("expected_classification")
    if expected_classification is not None and classification != expected_classification:
        failures.append(f"expected classification {expected_classification!r}, got {classification!r}")

    if expected.get("require_missing_evidence_present") and not report_model.missing_evidence:
        failures.append("expected missing_evidence to be non-empty (uncertainty should have been surfaced), got none")

    if expected.get("forbidden_high_confidence_without_evidence", True):
        for hyp in report_model.hypotheses:
            if hyp.confidence == "high" and not hyp.supporting_evidence_ids:
                failures.append(
                    f"hypothesis {hyp.statement[:60]!r} is confidence='high' with NO supporting evidence -- "
                    "this must never survive real citation validation"
                )

    if failures:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.FAIL,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail="; ".join(failures),
        )
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        evaluation_mode=case.evaluation_mode,
        result=Result.PASS,
        is_hard_safety_invariant=case.is_hard_safety_invariant,
        detail=f"classification={classification!r} matched expectations",
    )
