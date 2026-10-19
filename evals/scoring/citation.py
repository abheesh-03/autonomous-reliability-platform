"""Citation-validity scoring -- Gate C requirement A.

Reuses investigator-service's REAL, production citation machinery
directly (never a reimplementation):

  - `investigator_service.llm.prompt.build_prompts` computes the
    authoritative `shown_evidence_ids`/`shown_context_ids` sets from a
    real `EvidencePackage` + optional `RetrievalContext` -- the exact
    same function investigator.py calls before ever showing anything
    to a model.
  - `investigator_service.llm.provider.StubProvider(response_text=...)`
    is the real, production-sanctioned injectable provider seam (no
    network call, ever) -- used here to feed a case's own
    (possibly fabricated/adversarial) raw provider text through the
    REAL pipeline.
  - `investigator_service.llm.validation.parse_and_validate` is the
    real citation validator: it is what actually drops an unsupported
    observation/hypothesis and strips a fabricated evidence/context id
    -- this module never re-derives that logic itself.

A case's `input` is a dict with:
  - "evidence_package": a dict matching EvidencePackage's own schema
  - "retrieval_context": a dict matching RetrievalContext's schema, or
    null
  - "provider_response_text": the raw text StubProvider should return
    (this is what makes a case adversarial or clean)

A case's `expected_outcome` may set any of:
  - "min_surviving_observations" / "max_surviving_observations" (int)
  - "min_surviving_hypotheses" / "max_surviving_hypotheses" (int)
  - "fabricated_evidence_ids_must_be_absent": list[str] -- none of
    these ids may appear in ANY surviving observation/hypothesis
  - "fabricated_context_ids_must_be_absent": list[str] -- same, for
    hypothesis supporting/conflicting_context_ids
  - "validation_notes_must_mention": list[str] -- each substring must
    appear in at least one returned validation note (proves the
    fabrication was actually detected and recorded, not merely that
    the bad id happens to be absent)
"""

from investigator_service.config import EvidenceBounds, RagBounds
from investigator_service.domain.evidence import EvidencePackage
from investigator_service.domain.retrieval import RetrievalContext
from investigator_service.llm.prompt import build_prompts
from investigator_service.llm.provider import StubProvider
from investigator_service.llm.validation import ProviderOutputError, parse_and_validate

from evals.scoring.models import Case, CaseResult, Result


async def score_citation_case(case: Case) -> CaseResult:
    try:
        evidence = EvidencePackage.model_validate(case.input["evidence_package"])
        retrieval_context = (
            RetrievalContext.model_validate(case.input["retrieval_context"])
            if case.input.get("retrieval_context") is not None
            else None
        )
        provider_response_text = case.input["provider_response_text"]
    except Exception as exc:  # noqa: BLE001 -- malformed case input is NOT_EVALUATED, never a crash
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"could not construct real EvidencePackage/RetrievalContext from case input: {exc}",
        )

    bounds = EvidenceBounds.from_env()
    rag_bounds = RagBounds.from_env()
    _system_prompt, _user_prompt, shown_evidence_ids, _omitted_evidence, shown_context_ids, _omitted_context = (
        build_prompts(evidence, bounds, retrieval_context, rag_bounds)
    )

    provider = StubProvider(response_text=provider_response_text)
    raw_text = await provider.investigate(_system_prompt, _user_prompt)

    try:
        sanitized, notes = parse_and_validate(
            raw_text, frozenset(shown_evidence_ids), frozenset(shown_context_ids)
        )
    except ProviderOutputError as exc:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.FAIL if case.expected_outcome.get("expect_provider_output_error") is not True else Result.PASS,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"parse_and_validate raised ProviderOutputError: {exc}",
        )

    failures: list[str] = []
    expected = case.expected_outcome

    n_obs = len(sanitized.observations)
    n_hyp = len(sanitized.hypotheses)
    if "min_surviving_observations" in expected and n_obs < expected["min_surviving_observations"]:
        failures.append(f"expected >= {expected['min_surviving_observations']} surviving observations, got {n_obs}")
    if "max_surviving_observations" in expected and n_obs > expected["max_surviving_observations"]:
        failures.append(f"expected <= {expected['max_surviving_observations']} surviving observations, got {n_obs}")
    if "min_surviving_hypotheses" in expected and n_hyp < expected["min_surviving_hypotheses"]:
        failures.append(f"expected >= {expected['min_surviving_hypotheses']} surviving hypotheses, got {n_hyp}")
    if "max_surviving_hypotheses" in expected and n_hyp > expected["max_surviving_hypotheses"]:
        failures.append(f"expected <= {expected['max_surviving_hypotheses']} surviving hypotheses, got {n_hyp}")

    surviving_evidence_ids: set[str] = set()
    surviving_context_ids: set[str] = set()
    for obs in sanitized.observations:
        surviving_evidence_ids.update(obs.evidence_ids)
    for hyp in sanitized.hypotheses:
        surviving_evidence_ids.update(hyp.supporting_evidence_ids)
        surviving_evidence_ids.update(hyp.conflicting_evidence_ids)
        surviving_context_ids.update(hyp.supporting_context_ids)
        surviving_context_ids.update(hyp.conflicting_context_ids)

    for fabricated in expected.get("fabricated_evidence_ids_must_be_absent", []):
        if fabricated in surviving_evidence_ids:
            failures.append(f"fabricated evidence id {fabricated!r} survived into the sanitized output -- NEVER acceptable")
    for fabricated in expected.get("fabricated_context_ids_must_be_absent", []):
        if fabricated in surviving_context_ids:
            failures.append(f"fabricated context id {fabricated!r} survived into the sanitized output -- NEVER acceptable")

    joined_notes = " | ".join(notes)
    for must_mention in expected.get("validation_notes_must_mention", []):
        if must_mention not in joined_notes:
            failures.append(f"expected a validation note mentioning {must_mention!r}, notes were: {notes}")

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
        detail=f"citation validation matched expectations (observations={n_obs}, hypotheses={n_hyp}, notes={notes})",
    )
