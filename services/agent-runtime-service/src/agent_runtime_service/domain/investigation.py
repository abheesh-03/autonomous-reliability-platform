"""Local mirror of investigator-service's existing
POST /api/v1/investigations response contract
(investigator_service.domain.investigation.InvestigationReport) --
kept consistent BY HAND, the same separate-deployable convention
already used throughout this platform (see
investigator_service.domain.incident_snapshot's own docstring for why).

This is used ONLY to validate the SHAPE of investigator-service's real
response before trusting it into durable graph state (Phase 7 must
never persist a malformed/partial response as if it were a real
report) -- it is never a second implementation of Phase 5/6's own
evidence collection, prompt construction, or citation validation.
investigator-service remains the one and only canonical investigation
engine; this module only mirrors its OUTPUT shape.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["open", "acknowledged", "investigating", "remediating", "resolved", "closed"]
EvidenceSource = Literal["control_plane", "prometheus", "loki", "tempo"]
CollectionStatus = Literal["ok", "partial", "no_data", "unavailable"]
RetrievalOutcome = Literal["ok", "no_data", "unavailable"]


class SourceOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: EvidenceSource
    status: CollectionStatus
    detail: str
    query_summary: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source: EvidenceSource
    observed_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    summary: str
    detail: str
    reference: dict[str, str] = {}


class Observation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statement: str
    evidence_ids: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statement: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_context_ids: list[str] = Field(default_factory=list)
    conflicting_context_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"


class MissingEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str


class SuggestedCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    rationale: str = ""


class RetrievedContextItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    context_id: str
    source_type: Literal["knowledge", "historical_incident"]
    source_key: str
    title: str
    excerpt: str
    similarity: float
    metadata: dict = {}
    embedding_space: str


class RetrievalContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    knowledge: list[RetrievedContextItem] = []
    historical_incidents: list[RetrievedContextItem] = []
    outcome: RetrievalOutcome
    detail: str = ""


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    configured: bool
    provider: str
    model: str | None = None


class InvestigationReport(BaseModel):
    """investigator-service's real POST /api/v1/investigations
    response body -- validated here (extra="ignore" so a future,
    additive investigator-service field never breaks this older
    mirror; shape/type of every field THIS module cares about is
    still enforced) before being trusted into durable graph state."""

    model_config = ConfigDict(extra="ignore")

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
    retrieval_context: RetrievalContext
    provider: ProviderMetadata
    validation_notes: list[str] = Field(default_factory=list)
