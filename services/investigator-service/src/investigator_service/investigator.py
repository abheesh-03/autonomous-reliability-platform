"""The single orchestration class: incident_id in, a validated
InvestigationReport out. This is the ONLY place evidence collection,
retrieval, prompt construction, the provider call, and output
validation are wired together — deliberately not a generic agent loop
(Phase 5 §12): exactly one pass, no tool use, no iteration, no
retries that call the provider again with a different strategy.

Phase 6: a read-only retrieval step is inserted between evidence
collection and prompt construction. The retrieval QUERY is built here,
in application code, from bounded/redacted current-incident fields
(title, description, source, severity) — the LLM never generates a
retrieval query or a database query of any kind (Phase 6 §11). If
retrieval-service is unavailable or returns no matches, the
investigation still proceeds using Phase 5 evidence alone (Phase 6
§16) — this is never allowed to fail the whole investigation.
"""

import logging
from datetime import datetime

from investigator_service.clients.retrieval import RetrievalClient, RetrievalUnavailableError
from investigator_service.config import EvidenceBounds, RagBounds
from investigator_service.domain.investigation import InvestigationReport, MissingEvidence, ProviderMetadata
from investigator_service.domain.retrieval import RetrievalContext, RetrievedContextItem
from investigator_service.evidence_collector import EvidenceCollector
from investigator_service.llm.prompt import build_prompts
from investigator_service.llm.provider import LLMProvider
from investigator_service.llm.validation import parse_and_validate
from investigator_service.redaction import redact

logger = logging.getLogger("investigator_service.investigator")

_RETRIEVAL_QUERY_MAX_LENGTH = 2000


class ProviderNotConfiguredError(Exception):
    """No LLM provider is configured (Phase 5 §2/§6). Evidence
    collection may have already succeeded by the time this is raised —
    the caller (api/investigations.py) decides what, if anything, of
    that evidence to surface alongside this explicit, safe
    "unavailable" signal."""


def _build_retrieval_query(incident) -> str:
    """Deterministic, bounded, redacted — built from current-incident
    fields only, never from unbounded raw logs (Phase 6 §11)."""
    title = redact(incident.title)
    description = redact(incident.description) if incident.description else ""
    text = f"{title}. {description} (source={incident.source}, severity={incident.severity})"
    return text.strip()[:_RETRIEVAL_QUERY_MAX_LENGTH]


def _item_from_raw(raw: dict) -> RetrievedContextItem | None:
    try:
        return RetrievedContextItem(
            context_id="",  # assigned by the caller once ranked; placeholder here
            source_type=raw["source_type"],
            source_key=raw["source_key"],
            title=raw["title"],
            excerpt=raw["excerpt"],
            similarity=float(raw["similarity"]),
            metadata=raw.get("metadata") or {},
            embedding_space=raw["embedding_space"],
        )
    except (KeyError, TypeError, ValueError):
        return None


class Investigator:
    def __init__(
        self,
        collector: EvidenceCollector,
        provider: LLMProvider | None,
        bounds: EvidenceBounds,
        retrieval_client: RetrievalClient | None = None,
        rag_bounds: RagBounds | None = None,
    ) -> None:
        self._collector = collector
        self._provider = provider
        self._bounds = bounds
        self._retrieval_client = retrieval_client
        self._rag_bounds = rag_bounds

    async def _retrieve_context(self, incident) -> RetrievalContext:
        if self._retrieval_client is None or self._rag_bounds is None:
            return RetrievalContext(outcome="unavailable", detail="retrieval-service is not configured")

        query = _build_retrieval_query(incident)
        try:
            raw = await self._retrieval_client.search(
                query,
                exclude_incident_id=incident.id,
                knowledge_limit=self._rag_bounds.max_knowledge_contexts,
                historical_incident_limit=self._rag_bounds.max_historical_contexts,
                organization_id=str(incident.organization_id),
            )
        except RetrievalUnavailableError as exc:
            logger.warning("retrieval-service unavailable: %s", exc)
            return RetrievalContext(outcome="unavailable", detail="retrieval-service was unreachable")

        knowledge = [item for raw_item in raw.get("knowledge", []) if (item := _item_from_raw(raw_item))]
        historical = [
            item for raw_item in raw.get("historical_incidents", []) if (item := _item_from_raw(raw_item))
        ]

        if not knowledge and not historical:
            return RetrievalContext(outcome="no_data", detail="retrieval-service returned no matching context")
        return RetrievalContext(knowledge=knowledge, historical_incidents=historical, outcome="ok")

    async def investigate(self, incident_id: str):
        """Returns InvestigationReport. Raises (uncaught, for the API
        layer to translate): IncidentNotFoundError, ControlPlaneUnavailableError,
        ProviderNotConfiguredError, PromptTooLargeError, ProviderError, ProviderOutputError."""
        evidence = await self._collector.collect(incident_id)

        if self._provider is None:
            raise ProviderNotConfiguredError()

        retrieval_context = await self._retrieve_context(evidence.incident)

        system_prompt, user_prompt, shown_ids, omitted_ids, shown_context_ids, omitted_context_ids = build_prompts(
            evidence, self._bounds, retrieval_context, self._rag_bounds
        )
        raw_text = await self._provider.investigate(system_prompt, user_prompt)

        # IMPORTANT (Phase 5 correction round #1, extended Phase 6):
        # validated against the ids actually shown to the model, not
        # every id the larger EvidencePackage/RetrievalContext happens
        # to contain.
        llm_output, notes = parse_and_validate(raw_text, frozenset(shown_ids), frozenset(shown_context_ids))

        # System-synthesized missing-evidence entries -- never
        # generated by the model, so they survive regardless of what
        # it says, and are never confused with its own (also honest,
        # but separately validated) missing_evidence claims.
        missing_evidence = list(llm_output.missing_evidence)
        for outcome in evidence.source_outcomes:
            if outcome.status == "partial":
                missing_evidence.append(
                    MissingEvidence(description=f"{outcome.source}: {outcome.detail}")
                )
        if omitted_ids:
            notes.append(
                f"{len(omitted_ids)} collected evidence item(s) were not shown to the model due to "
                f"the context-size bound: {', '.join(omitted_ids)}"
            )
            missing_evidence.append(
                MissingEvidence(
                    description=(
                        f"{len(omitted_ids)} collected evidence item(s) were omitted from the model's "
                        "context due to the configured size bound and could not factor into its analysis"
                    )
                )
            )
        if omitted_context_ids:
            notes.append(
                f"{len(omitted_context_ids)} retrieved context item(s) were not shown to the model due to "
                f"the context-size bound: {', '.join(omitted_context_ids)}"
            )

        # Assign the final K<n>/H<n> ids to the retrieval_context we
        # report back, matching EXACTLY what build_prompts decided to
        # show (shown_context_ids) -- this is the same set
        # parse_and_validate above was given, so the report's own
        # retrieval_context and the ids any surviving hypothesis cites
        # are always consistent with each other.
        reported_context = _attach_context_ids(retrieval_context, shown_context_ids)

        return InvestigationReport(
            incident_id=evidence.incident.id,
            investigated_at=datetime.now(evidence.incident.first_seen_at.tzinfo),
            incident_status_at_investigation=evidence.incident.status,
            summary=llm_output.summary,
            observations=llm_output.observations,
            hypotheses=llm_output.hypotheses,
            missing_evidence=missing_evidence,
            suggested_checks=llm_output.suggested_checks,
            evidence=evidence.items,
            source_outcomes=evidence.source_outcomes,
            retrieval_context=reported_context,
            provider=ProviderMetadata(
                configured=True, provider=self._provider.name, model=getattr(self._provider, "model", None)
            ),
            validation_notes=notes,
        )


def _attach_context_ids(retrieval_context: RetrievalContext, shown_context_ids: list[str]) -> RetrievalContext:
    """Rebuilds the knowledge/historical_incidents lists so each
    item's `context_id` matches the K<n>/H<n> id build_prompts
    actually assigned and showed to the model -- items that were
    omitted by the prompt's own character budget are dropped from the
    REPORTED context too, so the report never shows something as
    context that the model never actually saw."""
    shown_set = set(shown_context_ids)
    k_ids = [f"K{i + 1}" for i in range(len(retrieval_context.knowledge))]
    h_ids = [f"H{i + 1}" for i in range(len(retrieval_context.historical_incidents))]

    knowledge = [
        item.model_copy(update={"context_id": cid})
        for cid, item in zip(k_ids, retrieval_context.knowledge, strict=True)
        if cid in shown_set
    ]
    historical = [
        item.model_copy(update={"context_id": cid})
        for cid, item in zip(h_ids, retrieval_context.historical_incidents, strict=True)
        if cid in shown_set
    ]
    return retrieval_context.model_copy(update={"knowledge": knowledge, "historical_incidents": historical})
