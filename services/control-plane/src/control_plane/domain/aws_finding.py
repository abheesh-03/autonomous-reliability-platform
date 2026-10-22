"""Phase 13: request/response models for the authenticated AWS
finding-ingestion endpoint (POST /internal/v1/aws/findings). Mirrors
`control_plane.domain.kubernetes_finding`'s own structure and
discipline exactly, for the AWS source instead of Kubernetes --
including the SAME boundary: this is shape/vocabulary reuse of
`detectors.schemas.aws.AwsDetectionFinding`, never an import of it
(control-plane never depends on the `detectors`/`catalog` packages at
runtime).

Every field here is bounded and validated before ever reaching the
database -- the same defense-in-depth discipline every other
machine-collected ingestion path in this service already applies.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVIDENCE_ENTRIES = 50
MAX_EVIDENCE_VALUE_CHARS = 2000
MAX_SUPPORTING_CHANGE_EVENTS = 20
MAX_RATIONALE_CHARS = 2000
MAX_IDENTITY_CHARS = 200
MAX_DETECTOR_ID_CHARS = 100

_ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
_REGION_RE = re.compile(r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d$")
_RESOURCE_KIND_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,62}$")

# Phase 13 scope: the ONE AWS finding-producing detector pipeline that
# exists only ever reports CONFIRMED or INSUFFICIENT_EVIDENCE results
# -- mirrors detectors.schemas.aws.AwsDetectionResult exactly, minus
# SOURCE_UNAVAILABLE (that outcome means a detector was never even
# attempted, so it has no finding to report here at all).
DetectorResult = Literal["confirmed", "insufficient_evidence"]

# Mirrors detectors.schemas.aws.AwsCollectionOutcome's own completeness
# vocabulary -- a caller MUST say which one applies; there is no
# default that silently claims complete coverage.
CollectionCompleteness = Literal["complete", "partial"]


class AwsFindingIngestRequest(BaseModel):
    """POST /internal/v1/aws/findings request body -- the
    aws-ingestion-token-only internal endpoint. One request represents
    ONE detector's finding for ONE AWS resource at ONE observation
    instant; a caller with multiple findings sends one request per
    finding (same documented scope decision as the Kubernetes path --
    see kubernetes_finding.py's own docstring)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(..., min_length=12, max_length=12)
    region: str = Field(..., min_length=1, max_length=30)
    resource_kind: str = Field(..., min_length=1, max_length=63)
    resource_id: str = Field(..., min_length=1, max_length=MAX_IDENTITY_CHARS)
    resource_arn: str | None = Field(default=None, min_length=1, max_length=400)
    detector_id: str = Field(..., min_length=1, max_length=MAX_DETECTOR_ID_CHARS)
    result: DetectorResult
    collection_completeness: CollectionCompleteness
    # The detector's own observation-collection instant -- mirrors
    # KubernetesFindingIngestRequest.collected_at's own role exactly
    # (see ingestion/aws_service.py's occurrence-identity logic).
    collected_at: datetime
    decision_rationale: str = Field(..., max_length=MAX_RATIONALE_CHARS)
    evidence: dict[str, str] = Field(default_factory=dict, max_length=MAX_EVIDENCE_ENTRIES)
    supporting_change_events: list[str] = Field(default_factory=list, max_length=MAX_SUPPORTING_CHANGE_EVENTS)

    @model_validator(mode="after")
    def _validate_identity_and_bounds(self) -> "AwsFindingIngestRequest":
        if not _ACCOUNT_ID_RE.match(self.account_id):
            raise ValueError(f"account_id {self.account_id!r} is not a valid 12-digit AWS account id")
        if not _REGION_RE.match(self.region):
            raise ValueError(f"region {self.region!r} is not a valid AWS region identifier")
        if not _RESOURCE_KIND_RE.match(self.resource_kind):
            raise ValueError(f"resource_kind {self.resource_kind!r} is not a valid identifier")
        if not self.resource_id.strip():
            raise ValueError("resource_id must not be blank")
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must include timezone information")

        for key, value in self.evidence.items():
            if len(key) > MAX_DETECTOR_ID_CHARS or len(value) > MAX_EVIDENCE_VALUE_CHARS:
                raise ValueError(f"evidence[{key!r}] exceeds the bounded key/value size")
        for event in self.supporting_change_events:
            if len(event) > MAX_RATIONALE_CHARS:
                raise ValueError("supporting_change_events entries must each be a short, bounded summary")
        return self


class AwsIncidentEvidence(BaseModel):
    """GET /api/v1/incidents/{id}/aws-evidence's response shape -- the
    ONE trusted, persisted source of an AWS-sourced incident's own
    resource identity, extracted from the most recent actor_type='aws'
    incident_event's metadata. Read-only, unauthenticated -- same
    local-development policy as every other incident GET route."""

    model_config = ConfigDict(extra="ignore")

    account_id: str
    region: str
    resource_kind: str
    resource_id: str
    resource_arn: str | None = None
    detector_id: str
    result: DetectorResult
    collection_completeness: CollectionCompleteness
    collected_at: datetime
    # Correction round, Issue 4: the detector's own bounded, allowlisted
    # measurements (e.g. CloudWatch state_value/state_reason, EC2
    # instance_status/system_status, ECS desired_count/running_count)
    # and its decision_rationale -- previously omitted from this model
    # entirely, which meant the investigator could never actually see
    # the original symptom or supporting measurements at all, even
    # though they were accepted at ingestion. Both fields are already
    # bounded at ingestion by AwsFindingIngestRequest's own field
    # limits (MAX_EVIDENCE_ENTRIES/MAX_EVIDENCE_VALUE_CHARS/
    # MAX_RATIONALE_CHARS below) -- never re-bounded here, and never
    # redacted here either (redaction of this untrusted external text
    # happens at the SAME boundary every other untrusted text in this
    # platform is redacted at -- investigator-service's own evidence
    # collector, not at storage/retrieval).
    decision_rationale: str
    evidence: dict[str, str] = Field(default_factory=dict)
    supporting_change_events: list[str] = Field(default_factory=list)


class AwsFindingIngestResponse(BaseModel):
    """A deliberately small acknowledgement -- same convention as
    KubernetesFindingIngestResponse."""

    incident_id: str
    outcome: Literal["created", "updated", "ignored"]
    severity: str


__all__ = [
    "AwsFindingIngestRequest",
    "AwsFindingIngestResponse",
    "AwsIncidentEvidence",
]
