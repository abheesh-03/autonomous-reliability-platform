"""The investigation request/response contract (Phase 5 §7) and the
raw, untrusted shape the LLM provider must produce (validated against
the real evidence package before ever reaching a caller — see
investigator_service/llm/validation.py).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from investigator_service.domain.evidence import EvidenceItem, SourceOutcome
from investigator_service.domain.incident_snapshot import Status


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID


class Observation(BaseModel):
    """A direct, evidence-grounded observation — not a hypothesis."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_ids: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    """A plausible, UNCONFIRMED explanation. Never presented as fact —
    see llm/prompt.py's explicit instruction that the model must never
    state an unverified root cause as confirmed."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"


class MissingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str


class SuggestedCheck(BaseModel):
    """A read-only diagnostic suggestion — never a remediation action,
    and never phrased as something already executed."""

    model_config = ConfigDict(extra="forbid")

    description: str
    rationale: str = ""


class LLMInvestigationOutput(BaseModel):
    """The exact JSON shape the provider must return. Untrusted until
    every evidence_id reference in it has been checked against the
    real EvidencePackage — see llm/validation.py. This model alone
    does not guarantee that; it only guarantees shape/type."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    suggested_checks: list[SuggestedCheck] = Field(default_factory=list)


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    provider: str
    model: str | None = None


class InvestigationReport(BaseModel):
    """The full POST /api/v1/investigations response body."""

    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    investigated_at: datetime
    incident_status_at_investigation: Status
    summary: str
    observations: list[Observation]
    hypotheses: list[Hypothesis]
    missing_evidence: list[MissingEvidence]
    suggested_checks: list[SuggestedCheck]
    evidence: list[EvidenceItem]
    source_outcomes: list[SourceOutcome]
    provider: ProviderMetadata
    validation_notes: list[str] = Field(default_factory=list)
