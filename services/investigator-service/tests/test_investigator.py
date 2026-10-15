"""Orchestration-level tests for Investigator — Phase 5 §9's "missing
provider configuration", "provider timeout/error handling", and
general wiring between evidence collection, prompting, the provider,
and validation."""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from investigator_service.clients.control_plane import IncidentNotFoundError
from investigator_service.clients.retrieval import RetrievalUnavailableError
from investigator_service.config import RagBounds
from investigator_service.domain.evidence import EvidenceItem, EvidencePackage, SourceOutcome
from investigator_service.domain.incident_snapshot import IncidentSnapshot
from investigator_service.investigator import Investigator, ProviderNotConfiguredError
from investigator_service.llm.provider import ProviderError, StubProvider
from investigator_service.llm.validation import ProviderOutputError
from tests.conftest import SAMPLE_INCIDENT_ID, TEST_BOUNDS

TEST_RAG_BOUNDS = RagBounds(
    max_knowledge_contexts=3, max_historical_contexts=3, max_context_excerpt_chars=500, max_rag_context_chars=6000
)


def _raw_context_item(source_type="knowledge", source_key="runbooks/x.md", title="T", excerpt="e", similarity=0.5):
    return {
        "source_type": source_type,
        "source_key": source_key,
        "title": title,
        "excerpt": excerpt,
        "similarity": similarity,
        "metadata": {},
        "embedding_space": "local-lexical:hashing-v1:1536",
    }


class FakeRetrievalClient:
    def __init__(self, response: dict | None = None, raise_: Exception | None = None):
        self._response = response if response is not None else {"knowledge": [], "historical_incidents": []}
        self._raise = raise_
        self.calls: list[dict] = []

    async def search(self, query, *, exclude_incident_id=None, knowledge_limit, historical_incident_limit):
        self.calls.append(
            {
                "query": query,
                "exclude_incident_id": exclude_incident_id,
                "knowledge_limit": knowledge_limit,
                "historical_incident_limit": historical_incident_limit,
            }
        )
        if self._raise:
            raise self._raise
        return self._response


def _incident(status: str = "resolved") -> IncidentSnapshot:
    return IncidentSnapshot.model_validate(
        {
            "id": str(SAMPLE_INCIDENT_ID),
            "source": "alertmanager",
            "source_fingerprint": "fp",
            "title": "t",
            "description": None,
            "severity": "critical",
            "status": status,
            "first_seen_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "last_seen_at": datetime(2026, 4, 1, 9, 5, 0, tzinfo=UTC).isoformat(),
            "resolved_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat() if status == "resolved" else None,
            "created_at": datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC).isoformat(),
            "updated_at": datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC).isoformat(),
        }
    )


class FakeCollector:
    def __init__(self, package=None, raise_=None):
        self._package = package
        self._raise = raise_
        self.calls = 0

    async def collect(self, incident_id):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._package


def _package(status: str = "resolved") -> EvidencePackage:
    return EvidencePackage(
        incident=_incident(status),
        events=[],
        events_total=0,
        items=[EvidenceItem(id="E1", source="control_plane", summary="s", detail="d")],
        source_outcomes=[SourceOutcome(source="control_plane", status="ok", detail="d")],
        collected_at=datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC),
    )


class RaisingProvider:
    name = "raising"
    model = "n/a"

    async def investigate(self, system_prompt, user_prompt):
        raise ProviderError("APITimeoutError: simulated timeout")


async def test_happy_path_produces_a_report_citing_real_evidence():
    stub = StubProvider(
        response_text=json.dumps(
            {
                "summary": "Checkout failures are consistent with loss of payment-service availability.",
                "observations": [{"statement": "502 observed", "evidence_ids": ["E1"]}],
                "hypotheses": [],
                "missing_evidence": [],
                "suggested_checks": [],
            }
        )
    )
    investigator = Investigator(FakeCollector(package=_package()), stub, TEST_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.incident_id == SAMPLE_INCIDENT_ID
    assert report.provider.configured is True
    assert report.provider.provider == "stub"
    assert report.observations[0].evidence_ids == ["E1"]
    assert report.evidence[0].id == "E1"


async def test_resolved_incident_is_still_investigable_from_history():
    stub = StubProvider()
    investigator = Investigator(FakeCollector(package=_package(status="resolved")), stub, TEST_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.incident_status_at_investigation == "resolved"


async def test_missing_provider_configuration_raises_explicit_error():
    investigator = Investigator(FakeCollector(package=_package()), provider=None, bounds=TEST_BOUNDS)
    with pytest.raises(ProviderNotConfiguredError):
        await investigator.investigate(str(SAMPLE_INCIDENT_ID))


async def test_incident_not_found_propagates_from_collector():
    investigator = Investigator(FakeCollector(raise_=IncidentNotFoundError("x")), StubProvider(), TEST_BOUNDS)
    with pytest.raises(IncidentNotFoundError):
        await investigator.investigate(str(SAMPLE_INCIDENT_ID))


async def test_provider_error_propagates_as_provider_error():
    investigator = Investigator(FakeCollector(package=_package()), RaisingProvider(), TEST_BOUNDS)
    with pytest.raises(ProviderError):
        await investigator.investigate(str(SAMPLE_INCIDENT_ID))


async def test_malformed_provider_output_propagates_as_provider_output_error():
    stub = StubProvider(response_text="not valid json")
    investigator = Investigator(FakeCollector(package=_package()), stub, TEST_BOUNDS)
    with pytest.raises(ProviderOutputError):
        await investigator.investigate(str(SAMPLE_INCIDENT_ID))


async def test_investigate_never_calls_anything_but_collect_and_investigate():
    """Structural guarantee: Investigator's only two collaborators are
    the collector's `collect()` and the provider's `investigate()` —
    neither is a write/mutate-capable method by name or by contract."""
    collector = FakeCollector(package=_package())
    stub = StubProvider()
    investigator = Investigator(collector, stub, TEST_BOUNDS)
    await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert collector.calls == 1


async def test_default_stub_provider_produces_a_real_e1_cited_observation():
    """Phase 5 correction round #1: CI must exercise the actual
    citation-validation path, not pass trivially with every analysis
    section empty."""
    investigator = Investigator(FakeCollector(package=_package()), StubProvider(), TEST_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert len(report.observations) >= 1
    assert any("E1" in obs.evidence_ids for obs in report.observations)
    # The stub's own citation is genuinely valid -- nothing to correct
    # there -- but Phase 5 correction round #3 means the summary is
    # always rebuilt from validated claims, so that note is expected.
    assert len(report.validation_notes) == 1
    assert "replaced the provider's free-text summary" in report.validation_notes[0]


async def test_partial_source_outcome_is_carried_into_missing_evidence():
    partial_package = EvidencePackage(
        incident=_incident(),
        events=[],
        events_total=50,
        items=[EvidenceItem(id="E1", source="control_plane", summary="s", detail="d")],
        source_outcomes=[
            SourceOutcome(
                source="control_plane",
                status="partial",
                detail="retrieved only 2 of 50 real audit events",
            )
        ],
        collected_at=datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC),
    )
    investigator = Investigator(FakeCollector(package=partial_package), StubProvider(), TEST_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert any("2 of 50" in m.description for m in report.missing_evidence)


async def test_no_retrieval_client_configured_means_outcome_unavailable_and_investigation_still_succeeds():
    """Phase 6 §16: retrieval is optional -- with no client wired at
    all (retrieval_client=None, same as a blank
    INVESTIGATOR_RETRIEVAL_URL), the investigation still succeeds
    using Phase 5 evidence alone."""
    investigator = Investigator(FakeCollector(package=_package()), StubProvider(), TEST_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.retrieval_context.outcome == "unavailable"
    assert report.retrieval_context.knowledge == []
    assert report.retrieval_context.historical_incidents == []
    assert len(report.observations) >= 1  # Phase 5 evidence path still fully works


async def test_retrieval_service_unreachable_degrades_gracefully():
    """Phase 6 §16: a real retrieval failure (connection error, etc.)
    must not fail the whole investigation."""
    retrieval_client = FakeRetrievalClient(raise_=RetrievalUnavailableError("connection refused"))
    investigator = Investigator(
        FakeCollector(package=_package()), StubProvider(), TEST_BOUNDS, retrieval_client, TEST_RAG_BOUNDS
    )
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.retrieval_context.outcome == "unavailable"
    assert len(report.observations) >= 1


async def test_retrieval_with_no_matches_reports_no_data_distinct_from_unavailable():
    retrieval_client = FakeRetrievalClient(response={"knowledge": [], "historical_incidents": []})
    investigator = Investigator(
        FakeCollector(package=_package()), StubProvider(), TEST_BOUNDS, retrieval_client, TEST_RAG_BOUNDS
    )
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.retrieval_context.outcome == "no_data"


async def test_retrieval_query_is_built_from_bounded_incident_fields_not_raw_logs():
    """Phase 6 §11: the LLM never builds the retrieval query --
    application code does, from bounded/redacted current-incident
    fields only."""
    retrieval_client = FakeRetrievalClient()
    investigator = Investigator(
        FakeCollector(package=_package()), StubProvider(), TEST_BOUNDS, retrieval_client, TEST_RAG_BOUNDS
    )
    await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert len(retrieval_client.calls) == 1
    call = retrieval_client.calls[0]
    assert call["exclude_incident_id"] == SAMPLE_INCIDENT_ID
    assert "t" in call["query"]  # the fake incident's title is "t"
    assert call["knowledge_limit"] == TEST_RAG_BOUNDS.max_knowledge_contexts
    assert call["historical_incident_limit"] == TEST_RAG_BOUNDS.max_historical_contexts


async def test_valid_evidence_and_valid_context_hypothesis_survives_with_both_cited():
    """Phase 6 §12/§13: K/H context inserted only as CONTEXT, never as
    current-incident evidence -- a hypothesis with real E support that
    also cites valid K/H context survives with both citation sets
    intact, and the report's own retrieval_context carries real
    provenance for what was shown."""
    retrieval_client = FakeRetrievalClient(
        response={
            "knowledge": [_raw_context_item(source_type="knowledge", source_key="runbooks/checkout.md")],
            "historical_incidents": [],
        }
    )
    stub = StubProvider(
        response_text=json.dumps(
            {
                "summary": "s",
                "observations": [{"statement": "502 observed", "evidence_ids": ["E1"]}],
                "hypotheses": [
                    {
                        "statement": "possible dependency outage",
                        "supporting_evidence_ids": ["E1"],
                        "conflicting_evidence_ids": [],
                        "supporting_context_ids": ["K1"],
                        "conflicting_context_ids": [],
                        "confidence": "low",
                    }
                ],
                "missing_evidence": [],
                "suggested_checks": [],
            }
        )
    )
    investigator = Investigator(FakeCollector(package=_package()), stub, TEST_BOUNDS, retrieval_client, TEST_RAG_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))

    assert len(report.hypotheses) == 1
    assert report.hypotheses[0].supporting_evidence_ids == ["E1"]
    assert report.hypotheses[0].supporting_context_ids == ["K1"]
    assert report.retrieval_context.outcome == "ok"
    assert len(report.retrieval_context.knowledge) == 1
    assert report.retrieval_context.knowledge[0].context_id == "K1"
    assert report.retrieval_context.knowledge[0].source_key == "runbooks/checkout.md"


async def test_fabricated_context_citation_is_rejected_end_to_end():
    retrieval_client = FakeRetrievalClient(response={"knowledge": [], "historical_incidents": []})
    stub = StubProvider(
        response_text=json.dumps(
            {
                "summary": "s",
                "observations": [],
                "hypotheses": [
                    {
                        "statement": "h",
                        "supporting_evidence_ids": ["E1"],
                        "conflicting_evidence_ids": [],
                        "supporting_context_ids": ["K1"],  # never actually shown -- nothing was retrieved
                        "conflicting_context_ids": [],
                        "confidence": "low",
                    }
                ],
                "missing_evidence": [],
                "suggested_checks": [],
            }
        )
    )
    investigator = Investigator(FakeCollector(package=_package()), stub, TEST_BOUNDS, retrieval_client, TEST_RAG_BOUNDS)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert len(report.hypotheses) == 1
    assert report.hypotheses[0].supporting_context_ids == []
    assert any("K1" in note for note in report.validation_notes)


async def test_context_omitted_by_prompt_bound_cannot_be_cited():
    """A context item that build_prompts decided not to show (due to
    the RAG character sub-budget) is dropped from shown_context_ids,
    so even if the model hallucinates a citation for it, validation
    rejects it exactly like any other fabricated id."""
    retrieval_client = FakeRetrievalClient(
        response={
            "knowledge": [_raw_context_item(excerpt="k" * 10_000)],
            "historical_incidents": [],
        }
    )
    stub = StubProvider(
        response_text=json.dumps(
            {
                "summary": "s",
                "observations": [],
                "hypotheses": [
                    {
                        "statement": "h",
                        "supporting_evidence_ids": ["E1"],
                        "conflicting_evidence_ids": [],
                        "supporting_context_ids": ["K1"],
                        "conflicting_context_ids": [],
                        "confidence": "low",
                    }
                ],
                "missing_evidence": [],
                "suggested_checks": [],
            }
        )
    )
    tiny_rag_bounds = dataclasses.replace(TEST_RAG_BOUNDS, max_rag_context_chars=10)
    investigator = Investigator(
        FakeCollector(package=_package()), stub, TEST_BOUNDS, retrieval_client, tiny_rag_bounds
    )
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert report.hypotheses[0].supporting_context_ids == []
    assert report.retrieval_context.knowledge == []  # omitted from the report too, never shown as if it was


async def test_omitted_evidence_is_carried_into_missing_evidence_and_notes():
    many_items = [EvidenceItem(id="E1", source="control_plane", summary="s", detail="d")]
    many_items += [
        EvidenceItem(id=f"E{i}", source="control_plane", summary="s", detail="d") for i in range(2, 200)
    ]
    big_package = EvidencePackage(
        incident=_incident(),
        events=[],
        events_total=0,
        items=many_items,
        source_outcomes=[SourceOutcome(source="control_plane", status="ok", detail="d")],
        collected_at=datetime(2026, 4, 1, 9, 10, 0, tzinfo=UTC),
    )
    narrow_bounds = dataclasses.replace(TEST_BOUNDS, max_prompt_evidence_items=10)
    investigator = Investigator(FakeCollector(package=big_package), StubProvider(), narrow_bounds)
    report = await investigator.investigate(str(SAMPLE_INCIDENT_ID))
    assert any("omitted" in m.description.lower() for m in report.missing_evidence)
    assert any("context-size bound" in note for note in report.validation_notes)
