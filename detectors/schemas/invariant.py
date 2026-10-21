"""Gate D: the reusable business-invariant contract. An invariant is a
domain CORRECTNESS requirement (e.g. "every recorded status transition
is legal per the lifecycle state machine"), never a catalog scenario
title, and never something this package writes, repairs, or replays --
checking is always read-only.

`SOURCE_UNAVAILABLE` and `INSUFFICIENT_EVIDENCE` are both distinct from
`SATISFIED` on purpose: a missing data source must never be reported as
`SATISFIED` (Gate D's own explicit requirement) -- the honest default
when evidence cannot be fully gathered is one of these two, never a
false pass.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class InvariantCheckResult(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SOURCE_UNAVAILABLE = "source_unavailable"


class InvariantDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invariant_id: str
    description: str
    required_sources: list[str]
    scope: str
    expected_condition: str
    completeness_prerequisites: list[str]
    evidence_required: list[str]
    severity_hint: str
    verification_method: str


class InvariantViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    explanation: str
    evidence_reference: str


class InvariantCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invariant_id: str
    checked_observation_window_start: str
    checked_observation_window_end: str
    result: InvariantCheckResult
    subjects_checked: int
    violations: list[InvariantViolation]
    explanation: str
    evidence_provenance: list[str]
