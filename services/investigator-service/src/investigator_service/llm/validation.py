"""Validates and sanitizes raw provider output against the evidence
IDs actually PRESENTED TO THE MODEL (Phase 5 §6, corrected):
"Validate every cited evidence ID against the evidence package
actually collected. Reject or safely handle malformed provider output
and fabricated evidence references."

IMPORTANT (Phase 5 correction round #1): callers must pass the set of
evidence ids that were actually shown to the model (llm/prompt.py's
`build_prompts` return value), NOT every id in the larger collected
EvidencePackage — a package can legitimately contain more evidence
than fits in the prompt (see prompt.py's bounded selection policy), and
an id the model was never shown is exactly as fabricated as one that
never existed at all.

Four distinct outcomes, handled differently:
  - The output isn't valid JSON, or doesn't match the required shape
    at all -> ProviderOutputError (the caller maps this to a clear
    error response; there is no partial/garbage report).
  - An OBSERVATION with no valid supporting id (none cited, or every
    cited id was fabricated) -> the entire observation is DROPPED,
    never retained with evidence_ids=[]. A factual claim with no real
    supporting evidence is not a weaker claim, it is an unsupported
    one, and is never surfaced to the caller.
  - A HYPOTHESIS with no valid SUPPORTING id (Phase 5 correction round
    #2: whether it cited none at all, or every id it cited was
    fabricated) -> the entire hypothesis is DROPPED too. Lowering its
    confidence is not enough — an unconfirmed hypothesis is still
    allowed to exist, but only when at least one real piece of
    evidence actually motivates it; a hypothesis with zero real
    support is indistinguishable from a bare guess dressed up as
    analysis, and is never surfaced. (conflicting_evidence_ids is
    still sanitized the same way but never gates retention by itself —
    only supporting evidence does.)
  - The free-text `summary` (Phase 5 correction round #3): the
    provider's own free-text summary is NEVER retained, full stop —
    not even when some observations/hypotheses survive validation.
    This module has no way to semantically verify arbitrary prose, so
    a summary that merely LOOKS consistent with the surviving claims
    could still silently repeat a specific fabricated detail (a
    number, a service name) that was rejected above. Instead, the
    returned summary is always deterministically BUILT from the
    already-validated, citation-backed observations and hypotheses
    (see `_build_summary`) — conservative by construction, since it
    can only ever say what the sanitized structured output itself
    says. If nothing survives, it is the same fixed, honest fallback
    as before.
Every removal/drop/replacement is recorded in the returned notes list
— never silent.
"""

import json
import logging

from pydantic import ValidationError

from investigator_service.domain.investigation import LLMInvestigationOutput

logger = logging.getLogger("investigator_service.llm.validation")

UNVERIFIED_SUMMARY_FALLBACK = (
    "No evidence-grounded observations or hypotheses survived citation validation for this "
    "incident. The original summary text could not be verified against real evidence and has "
    "been withheld rather than surfaced as an unsupported claim."
)


class ProviderOutputError(Exception):
    pass


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def parse_and_validate(raw_text: str, shown_evidence_ids: frozenset[str]) -> tuple[LLMInvestigationOutput, list[str]]:
    cleaned = _strip_markdown_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderOutputError(f"provider output was not valid JSON: {exc}") from exc

    try:
        output = LLMInvestigationOutput.model_validate(data)
    except ValidationError as exc:
        raise ProviderOutputError(f"provider output did not match the required schema: {exc}") from exc

    notes: list[str] = []

    sanitized_observations = []
    for obs in output.observations:
        kept, dropped = _filter_ids(obs.evidence_ids, shown_evidence_ids)
        if not kept:
            # Never retain an unsupported factual observation, even
            # with evidence_ids=[] -- Phase 5 correction round #1.
            if dropped:
                notes.append(
                    f"dropped observation {obs.statement[:60]!r}: every cited evidence id {dropped} "
                    "was fabricated (not actually shown to the model)"
                )
            else:
                notes.append(f"dropped observation {obs.statement[:60]!r}: cited no evidence at all")
            continue
        if dropped:
            notes.append(
                f"removed fabricated evidence id(s) {dropped} cited by observation {obs.statement[:60]!r}"
            )
        sanitized_observations.append(obs.model_copy(update={"evidence_ids": kept}))

    sanitized_hypotheses = []
    for hyp in output.hypotheses:
        kept_support, dropped_support = _filter_ids(hyp.supporting_evidence_ids, shown_evidence_ids)
        kept_conflict, dropped_conflict = _filter_ids(hyp.conflicting_evidence_ids, shown_evidence_ids)

        if not kept_support:
            # Phase 5 correction round #2: a hypothesis with NO real
            # supporting evidence must not survive at all, whether
            # that is because every citation it gave was fabricated OR
            # because it never cited any support in the first place.
            # Lowering confidence alone is not enough -- an
            # unconfirmed hypothesis is still allowed to exist, but
            # only when something real actually motivates it.
            if dropped_support:
                notes.append(
                    f"dropped hypothesis {hyp.statement[:60]!r}: every supporting evidence id "
                    f"{dropped_support} was fabricated (not actually shown to the model)"
                )
            else:
                notes.append(f"dropped hypothesis {hyp.statement[:60]!r}: cited no supporting evidence at all")
            continue

        if dropped_support or dropped_conflict:
            notes.append(
                f"removed fabricated evidence id(s) {dropped_support + dropped_conflict} cited by "
                f"hypothesis {hyp.statement[:60]!r}"
            )

        sanitized_hypotheses.append(
            hyp.model_copy(update={"supporting_evidence_ids": kept_support, "conflicting_evidence_ids": kept_conflict})
        )

    # Phase 5 correction round #3: NEVER retain the provider's own
    # free-text summary -- it is unchecked prose this module cannot
    # semantically verify, so it could repeat a specific claim removed
    # above even while *looking* consistent with what survived. The
    # final summary is always built structurally from the already-
    # validated observations/hypotheses instead (see _build_summary).
    if sanitized_observations or sanitized_hypotheses:
        notes.append(
            "replaced the provider's free-text summary with one built only from the validated, "
            "citation-backed observations/hypotheses below -- the provider's own summary is never "
            "retained as-is, since it cannot be semantically verified and could otherwise repeat a "
            "claim rejected above"
        )
    else:
        notes.append(
            "replaced the provider's free-text summary with the fixed fallback: no observation or "
            "hypothesis survived citation validation, so nothing validated remains to summarize"
        )
    summary = _build_summary(sanitized_observations, sanitized_hypotheses)

    sanitized = output.model_copy(
        update={"summary": summary, "observations": sanitized_observations, "hypotheses": sanitized_hypotheses}
    )
    return sanitized, notes


def _filter_ids(ids: list[str], valid: frozenset[str]) -> tuple[list[str], list[str]]:
    kept = [i for i in ids if i in valid]
    dropped = [i for i in ids if i not in valid]
    return kept, dropped


def _build_summary(observations: list, hypotheses: list) -> str:
    """Deterministically builds the final summary from already-
    validated, citation-backed observations/hypotheses ONLY (Phase 5
    correction round #3) -- never from the provider's own free-text
    summary, which this module has no way to semantically verify.
    Hypotheses are always labeled explicitly as unconfirmed; their
    confidence is carried through as the model's own self-assessment,
    never upgraded or treated as proof."""
    if not observations and not hypotheses:
        return UNVERIFIED_SUMMARY_FALLBACK

    parts: list[str] = []
    if observations:
        rendered = " ".join(f"{obs.statement} (evidence: {', '.join(obs.evidence_ids)})." for obs in observations)
        parts.append(f"Validated observations: {rendered}")
    if hypotheses:
        rendered = " ".join(
            f"{hyp.statement} (confidence: {hyp.confidence}; supporting evidence: "
            f"{', '.join(hyp.supporting_evidence_ids)})."
            for hyp in hypotheses
        )
        parts.append(
            "Unconfirmed hypotheses (not proven -- merely consistent with the cited evidence; "
            f"confidence is the model's own self-assessment, never upgraded): {rendered}"
        )
    return " ".join(parts)
