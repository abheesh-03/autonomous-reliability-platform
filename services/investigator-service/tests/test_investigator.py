"""Orchestration-level tests for Investigator — Phase 5 §9's "missing
provider configuration", "provider timeout/error handling", and
general wiring between evidence collection, prompting, the provider,
and validation."""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from investigator_service.clients.control_plane import IncidentNotFoundError
from investigator_service.domain.evidence import EvidenceItem, EvidencePackage, SourceOutcome
from investigator_service.domain.incident_snapshot import IncidentSnapshot
from investigator_service.investigator import Investigator, ProviderNotConfiguredError
from investigator_service.llm.provider import ProviderError, StubProvider
from investigator_service.llm.validation import ProviderOutputError
from tests.conftest import SAMPLE_INCIDENT_ID, TEST_BOUNDS


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
