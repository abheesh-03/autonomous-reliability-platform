"""Phase 12B-D: request/response models for the authenticated
Kubernetes finding-ingestion endpoint
(POST /internal/v1/kubernetes/findings).

This is control-plane's OWN typed contract for the shape of ONE
Kubernetes failure observation -- it intentionally mirrors
`detectors.schemas.kubernetes.K8sDetectionFinding`'s field names and
vocabulary (cluster/namespace/resource_kind/resource_name/
resource_uid/detector_id/result/evidence/decision_rationale), but is
NOT a reuse of that Pydantic class itself: control-plane is a
separately deployed service with its own dependency tree (it does not,
and must not, depend on the `detectors`/`catalog` packages at runtime
-- the same boundary AlertmanagerWebhookPayload already keeps from
Alertmanager's own alert model). Reuse happens at the SHAPE/VOCABULARY
level, exactly like AlertmanagerWebhookPayload mirrors Alertmanager's
real webhook JSON without importing Alertmanager's own code.

Every field here is bounded and validated before ever reaching the
database -- this is the ONE write path into reliability.incidents that
is driven by machine-collected, API-derived data rather than a human
decision or Alertmanager's own long-established webhook contract, so
it gets the same defense-in-depth discipline Phase 8's remediation
proposal model already established (BoundedId-style per-field limits,
never a free-form unbounded string).
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.domain.incident import VALID_SEVERITIES

# Mirrors detectors.kubernetes.collector's own MAX_ITEMS-style defensive
# ceilings -- generous for a trusted, already-Bearer-authenticated
# internal endpoint, but never unbounded.
MAX_EVIDENCE_ENTRIES = 50
MAX_EVIDENCE_VALUE_CHARS = 2000
MAX_SUPPORTING_EVENT_REASONS = 50
MAX_RATIONALE_CHARS = 2000
MAX_IDENTITY_CHARS = 200
MAX_DETECTOR_ID_CHARS = 100

# The real Kubernetes DNS-1123-ish identity patterns -- the same
# discipline detectors/clients/kubernetes_client.py's own
# `_NAMESPACE_RE` already applies at the collection boundary; applied
# again HERE at the ingestion boundary, since this endpoint trusts a
# caller's Bearer token, never the caller's own claimed field values
# (Gate 2: "prevent ... cross-namespace injection").
_NAMESPACE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_RESOURCE_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
_RESOURCE_KIND_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,62}$")

# Phase 12B-D scope: the ONE Kubernetes finding-producing detector
# pipeline that exists (Phase 12A) only ever reports CONFIRMED or
# INSUFFICIENT_EVIDENCE results -- mirrors
# detectors.schemas.kubernetes.K8sDetectionResult exactly, minus
# SOURCE_UNAVAILABLE (that outcome means a detector was never even
# attempted, so it has no finding to report here at all).
DetectorResult = Literal["confirmed", "insufficient_evidence"]

# Mirrors detectors.schemas.kubernetes.CollectionOutcome's own
# completeness vocabulary -- Gate 2: "partial collections must preserve
# evidence gaps" / "missing signals never mean healthy". A caller MUST
# say which one applies; there is no default that silently claims
# complete coverage.
CollectionCompleteness = Literal["complete", "partial"]


class KubernetesFindingIngestRequest(BaseModel):
    """POST /internal/v1/kubernetes/findings request body -- the
    kubernetes-ingestion-token-only internal endpoint. One request
    represents ONE detector's finding for ONE Kubernetes resource at
    ONE observation instant; a caller with multiple findings (e.g. the
    offline pipeline's own `K8sDetectionFinding` list) sends one
    request per finding -- this endpoint deliberately does not accept
    a batch in this round (a documented scope decision, not an
    oversight: a partial batch failure's semantics -- which findings
    "count" -- would need its own careful design this round does not
    need to solve to satisfy Gate 2)."""

    model_config = ConfigDict(extra="forbid")

    cluster: str = Field(..., min_length=1, max_length=MAX_IDENTITY_CHARS)
    namespace: str = Field(..., min_length=1, max_length=63)
    resource_kind: str = Field(..., min_length=1, max_length=63)
    resource_name: str = Field(..., min_length=1, max_length=253)
    # Optional ONLY in the sense that a caller's own collection may not
    # have one (Gate 2: "resource UIDs ... must be validated" -- when
    # present, it is validated below; its ABSENCE is a real, honestly
    # weaker identity, never silently treated as equivalent to a UID
    # match).
    resource_uid: str | None = Field(default=None, min_length=1, max_length=MAX_IDENTITY_CHARS)
    detector_id: str = Field(..., min_length=1, max_length=MAX_DETECTOR_ID_CHARS)
    result: DetectorResult
    collection_completeness: CollectionCompleteness
    # The detector's own observation-collection instant (mirrors
    # Alertmanager's `startsAt` role exactly -- see
    # ingestion/kubernetes_service.py's occurrence-identity logic,
    # which reuses the SAME occurrence_starts_at watermark column via
    # this field). Must be timezone-aware and never in the future
    # relative to the server's own clock by more than a small
    # tolerance (clock skew only, never a stale replay passed off as
    # current -- Gate 2: "a previous stale event must not establish
    # current failure").
    collected_at: datetime
    decision_rationale: str = Field(..., max_length=MAX_RATIONALE_CHARS)
    uncertainty_notes: str | None = Field(default=None, max_length=MAX_RATIONALE_CHARS)
    evidence: dict[str, str] = Field(default_factory=dict, max_length=MAX_EVIDENCE_ENTRIES)
    supporting_event_reasons: list[str] = Field(default_factory=list, max_length=MAX_SUPPORTING_EVENT_REASONS)

    @model_validator(mode="after")
    def _validate_identity_and_bounds(self) -> "KubernetesFindingIngestRequest":
        if not _NAMESPACE_RE.match(self.namespace):
            raise ValueError(f"namespace {self.namespace!r} is not a valid Kubernetes namespace name")
        if not _RESOURCE_KIND_RE.match(self.resource_kind):
            raise ValueError(f"resource_kind {self.resource_kind!r} is not a valid Kubernetes Kind")
        if not _RESOURCE_NAME_RE.match(self.resource_name):
            raise ValueError(f"resource_name {self.resource_name!r} is not a valid Kubernetes resource name")
        if not self.cluster.strip():
            raise ValueError("cluster must not be blank")
        if self.resource_uid is not None and not self.resource_uid.strip():
            raise ValueError("resource_uid must not be blank when provided")
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must include timezone information")

        for key, value in self.evidence.items():
            if len(key) > MAX_DETECTOR_ID_CHARS or len(value) > MAX_EVIDENCE_VALUE_CHARS:
                raise ValueError(f"evidence[{key!r}] exceeds the bounded key/value size")
        for reason in self.supporting_event_reasons:
            if len(reason) > MAX_DETECTOR_ID_CHARS:
                raise ValueError("supporting_event_reasons entries must each be short (a Kubernetes Event reason)")
        return self


class KubernetesIncidentEvidence(BaseModel):
    """Phase 12B-D correction round (Issue 1): GET /api/v1/incidents/
    {id}/kubernetes-evidence's response shape -- the ONE trusted,
    persisted source of a Kubernetes-sourced incident's own resource
    identity, extracted from the most recent actor_type='kubernetes'
    incident_event's metadata (repositories/incident_repository.py's
    own get_latest_kubernetes_evidence_event). Read-only, unauthenticated
    -- same local-development policy as every other incident GET route
    -- this is evidence ABOUT an incident, never a secret."""

    model_config = ConfigDict(extra="ignore")

    cluster: str
    namespace: str
    resource_kind: str
    resource_name: str
    resource_uid: str | None = None
    detector_id: str
    result: DetectorResult
    collection_completeness: CollectionCompleteness
    collected_at: datetime


class KubernetesFindingIngestResponse(BaseModel):
    """A deliberately small acknowledgement -- never the full incident
    row (a caller with a kubernetes-ingestion token has no business
    reading other incidents' fields; GET /api/v1/incidents/{id} is the
    separate, unauthenticated read path for that, same convention as
    WebhookAckResponse)."""

    incident_id: str
    outcome: Literal["created", "updated", "ignored"]
    severity: str


# Re-exported purely so tests/other modules can reference the real DB
# vocabulary this module's severity mapping must stay inside.
__all__ = [
    "KubernetesFindingIngestRequest",
    "KubernetesFindingIngestResponse",
    "KubernetesIncidentEvidence",
    "VALID_SEVERITIES",
]
