"""Gate B (Phase 12A): the Kubernetes observation contract.

Mirrors the same honesty discipline Phase 11B already established for
Prometheus/Tempo/control-plane: a collection attempt always produces
one of a small, explicit set of outcomes -- success, a genuinely empty
(but successfully retrieved) result, missing/partial evidence, a
malformed response, an unreachable API server, or an RBAC-forbidden
response -- and these are NEVER conflated. A failed or forbidden
collection must never be reported as, or silently treated as, a
healthy result.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class CollectionOutcome(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"  # the API call succeeded and genuinely returned zero items
    PARTIAL = "partial"  # correction round (Issues 1/2): some real evidence was collected and is
    # preserved, but collection is KNOWN INCOMPLETE -- e.g. a continuation page remained
    # uncollected, the bounded item/page cap was reached while more pages existed, a
    # subsequent page failed/was forbidden, or some items on an otherwise-successful page
    # could not be parsed. PARTIAL must NEVER be treated as a complete, healthy observation.
    MALFORMED = "malformed"  # a 200 response that was not valid/expected JSON shape
    UNAVAILABLE = "unavailable"  # could not reach the API server at all (network/connection failure)
    FORBIDDEN = "forbidden"  # the API server reached, but returned HTTP 403 (RBAC)
    NOT_FOUND = "not_found"  # the API server reached, resource/namespace genuinely does not exist (404)


class ContainerWaitingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    message: str | None = None


class ContainerTerminatedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None


class ContainerResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu: str | None = None
    memory: str | None = None


class ContainerStatusObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_name: str
    image: str | None = None
    ready: bool | None = None
    restart_count: int | None = None
    waiting: ContainerWaitingState | None = None
    running: bool = False
    terminated: ContainerTerminatedState | None = None
    last_terminated: ContainerTerminatedState | None = None
    limits: ContainerResourceLimits | None = None


class PodConditionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    status: str | None = None
    reason: str | None = None
    message: str | None = None
    last_transition_time: str | None = None


class PodObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    name: str
    uid: str | None = None
    phase: str | None = None
    node_name: str | None = None
    owner_kind: str | None = None
    owner_name: str | None = None
    container_statuses: list[ContainerStatusObservation] = []
    conditions: list[PodConditionObservation] = []
    creation_timestamp: str | None = None


class DeploymentConditionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    status: str | None = None
    reason: str | None = None
    message: str | None = None
    last_update_time: str | None = None
    last_transition_time: str | None = None


class DeploymentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    name: str
    uid: str | None = None
    generation: int | None = None
    observed_generation: int | None = None
    replicas: int | None = None
    ready_replicas: int | None = None
    available_replicas: int | None = None
    updated_replicas: int | None = None
    unavailable_replicas: int | None = None
    conditions: list[DeploymentConditionObservation] = []


class ReplicaSetObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    name: str
    uid: str | None = None
    owner_name: str | None = None
    replicas: int | None = None
    ready_replicas: int | None = None
    revision: str | None = None


class EventObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    involved_object_kind: str | None = None
    involved_object_name: str | None = None
    reason: str | None = None
    message: str | None = None
    type: str | None = None  # "Normal" | "Warning"
    count: int | None = None
    first_timestamp: str | None = None
    last_timestamp: str | None = None


class K8sDetectionResult(str, Enum):
    CONFIRMED = "confirmed"  # real, direct evidence establishes this specific failure pattern
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # a suspicious signal exists, but not enough to confirm
    SOURCE_UNAVAILABLE = "source_unavailable"  # collection itself failed -- classification was never attempted


class K8sDetectionFinding(BaseModel):
    """One classifier's output for one specific resource -- never
    emitted for a genuinely healthy resource (a detector returns an
    empty list for those, rather than a noisy "NOT_PRESENT" entry per
    object). `result` is always CONFIRMED or INSUFFICIENT_EVIDENCE
    here; SOURCE_UNAVAILABLE is reserved for the collection layer
    itself and is represented by a `CollectionResult`, not this
    model."""

    model_config = ConfigDict(extra="forbid")

    detector_id: str
    resource_kind: str  # "Pod" | "Deployment"
    namespace: str
    resource_name: str
    # Correction round (Phase 12B-D, Issue 6): the resource's own UID,
    # read directly from the already-collected PodObservation/
    # DeploymentObservation this finding was built from -- never
    # fabricated. This is what lets a downstream consumer (control-
    # plane's Kubernetes finding-ingestion endpoint, and in turn
    # agent-runtime-service's propose_remediation) demonstrate a real
    # identity/ownership relationship between a specific incident and
    # a specific live resource, rather than only a name/namespace
    # match. None only when the underlying object genuinely had no uid
    # field in the collected API response (never silently defaulted to
    # a placeholder).
    resource_uid: str | None = None
    container_name: str | None = None
    result: K8sDetectionResult
    evidence: dict[str, str] = {}
    supporting_event_reasons: list[str] = []
    decision_rationale: str
    uncertainty_notes: str | None = None


class CollectionResult(BaseModel):
    """Wraps EVERY Kubernetes collection call -- callers must always
    check `outcome` before trusting `items`; `items` is only ever
    meaningful when `outcome == SUCCESS` (non-empty), `EMPTY`, or
    `PARTIAL` (meaningful but KNOWN INCOMPLETE -- see `detail`)."""

    model_config = ConfigDict(extra="forbid")

    outcome: CollectionOutcome
    resource_kind: str
    namespace: str
    detail: str
    items_count: int = 0
