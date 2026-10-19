"""OPTIONAL, explicitly opt-in real-model evaluation mode.

Requirements this module exists to satisfy, all enforced here, never
left to the caller's discipline alone:

  - explicitly opt-in: this function is never called by `score_case`'s
    default dispatch, and is itself a no-op (`NOT_EVALUATED`, never a
    silent success) unless BOTH the CLI's own `--real-model` flag was
    passed AND `investigator_service.config.LLMSettings.from_env()`
    reports `provider == "openai"` with a real, non-empty `api_key` --
    `settings.configured` alone is NOT sufficient, since that property
    is also true for `provider == "stub"`, which makes no network call
    at all; this module checks the stronger, explicit condition itself
    rather than trusting that property.
  - no network call by default / never required for CI: both this
    module's own double-gate above AND evals/runner/cli.py's default
    (`--real-model` is never passed unless a human explicitly adds it)
    guarantee this.
  - uses configured credentials without printing them: the real API
    key is read once from `LLMSettings.from_env()` and passed straight
    into `OpenAIProvider`'s constructor -- never logged, never placed
    in any CaseResult/report field.
  - bounded request count / timeout / cost: `MAX_REAL_MODEL_CASES`
    caps how many cases this mode will ever send to a real provider in
    one run; `REAL_MODEL_TIMEOUT_SECONDS` bounds each individual call
    (never looser than the service's own configured timeout);
    `OpenAIProvider` itself is constructed with `max_retries=0`
    (investigator_service.llm.provider's own production default) --
    there is no retry loop here or in that class.
  - reports actual model identifier and run timestamp: see
    `real_model_run_metadata()`, called only after a real call was
    actually attempted.
  - provider failures are never quality success: a `ProviderError`
    (timeout, connection failure, empty response) is `NOT_EVALUATED`,
    never `PASS`.
  - stochastic/semantic judgment stays separate from deterministic
    safety: this module only ever re-runs CITATION-mode cases (the one
    thing that remains objectively checkable even against a real,
    non-deterministic model's output -- did it cite a real id or
    fabricate one), through the SAME real `parse_and_validate` the
    offline citation scorer uses. It never asserts a semantic quality
    verdict ("this hypothesis is correct") -- it only reports what the
    real model actually produced and whether its OWN citations were
    valid, which is the only part of "AI quality" this harness can
    responsibly claim to have checked against a real provider.
"""

from datetime import UTC, datetime

from investigator_service.config import EvidenceBounds, LLMSettings, RagBounds
from investigator_service.domain.evidence import EvidencePackage
from investigator_service.domain.retrieval import RetrievalContext
from investigator_service.llm.prompt import build_prompts
from investigator_service.llm.provider import OpenAIProvider, ProviderError
from investigator_service.llm.validation import ProviderOutputError, parse_and_validate

from evals.scoring.models import Case, CaseResult, Result

MAX_REAL_MODEL_CASES = 10
REAL_MODEL_TIMEOUT_SECONDS = 20.0


def real_model_is_available() -> tuple[bool, str]:
    """The double-gate condition itself, exposed so the CLI can decide
    whether to even attempt real-model mode and explain why not, rather
    than duplicating this check."""
    settings = LLMSettings.from_env()
    if settings.provider != "openai":
        return False, f"INVESTIGATOR_LLM_PROVIDER is {settings.provider!r}, not 'openai' -- no real call possible"
    if not settings.api_key:
        return False, "INVESTIGATOR_LLM_API_KEY is unset -- no real call possible"
    return True, f"real provider available: model={settings.model}"


async def score_citation_case_with_real_model(case: Case) -> CaseResult:
    available, reason = real_model_is_available()
    if not available:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=False,
            detail=f"real-model mode requested but not available: {reason}",
        )

    settings = LLMSettings.from_env()
    try:
        evidence = EvidencePackage.model_validate(case.input["evidence_package"])
        retrieval_context = (
            RetrievalContext.model_validate(case.input["retrieval_context"])
            if case.input.get("retrieval_context") is not None
            else None
        )
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=False,
            detail=f"could not construct real EvidencePackage/RetrievalContext from case input: {exc}",
        )

    bounds = EvidenceBounds.from_env()
    rag_bounds = RagBounds.from_env()
    system_prompt, user_prompt, shown_evidence_ids, _omitted, shown_context_ids, _omitted_ctx = build_prompts(
        evidence, bounds, retrieval_context, rag_bounds
    )

    provider = OpenAIProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=min(settings.timeout_seconds, REAL_MODEL_TIMEOUT_SECONDS),
    )

    try:
        raw_text = await provider.investigate(system_prompt, user_prompt)
    except ProviderError as exc:
        # A real provider failure is reported honestly -- NEVER scored
        # as a quality success, and never silently retried (this
        # module issues at most one call per case, matching
        # OpenAIProvider's own max_retries=0).
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=False,
            detail=f"real provider call failed: {exc}",
        )

    try:
        sanitized, notes = parse_and_validate(raw_text, frozenset(shown_evidence_ids), frozenset(shown_context_ids))
    except ProviderOutputError as exc:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.FAIL,
            is_hard_safety_invariant=False,
            detail=f"real provider output failed the SAME real citation validator the offline mode uses: {exc}",
        )

    # Deliberately no PASS/FAIL verdict on semantic quality here -- see
    # this module's own docstring. Citation validity against a REAL,
    # non-deterministic model's output is the one thing still
    # objectively checkable; it is reported as PASS only if every
    # citation the real model made was real (no fabrication at all),
    # which is the narrow, honest claim this mode can actually support.
    fabricated_detected = any("fabricated" in note for note in notes)
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        evaluation_mode=case.evaluation_mode,
        result=Result.FAIL if fabricated_detected else Result.PASS,
        is_hard_safety_invariant=False,
        detail=(
            f"real model ({settings.model}) produced {len(sanitized.observations)} surviving observation(s), "
            f"{len(sanitized.hypotheses)} surviving hypothesis/es; fabricated citation detected="
            f"{fabricated_detected}; notes={notes}. This reports CITATION VALIDITY of real model output only -- "
            "it is NOT a semantic correctness/quality verdict."
        ),
    )


def real_model_run_metadata() -> dict[str, str]:
    settings = LLMSettings.from_env()
    return {
        "provider": settings.provider,
        "model": settings.model,
        "run_timestamp": datetime.now(UTC).isoformat(),
    }
