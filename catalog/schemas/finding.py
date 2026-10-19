"""Gate D: the general-purpose incident-finding representation.

This is deliberately NOT keyed on the 800-scenario catalog: a
`FailureFinding` must remain a fully valid, meaningful record for an
incident that matches no known scenario at all. `scenario_id` (via
`candidate_known_scenario_matches`) is always OPTIONAL and the system
must never invent one to force a classification -- an empty list of
candidate matches, with `unresolved_classification=True`, is a normal
and expected state, not an error.

The six stages below (OBSERVATION, HYPOTHESIS, DIAGNOSTIC CHECK,
REMEDIATION PROPOSAL, EXECUTION, RECOVERY VERIFICATION) are kept as
separate models on purpose: an `Observation` is evidence, never proof
of root cause; a `Hypothesis` built from it is a candidate explanation,
never a conclusion; correlation (e.g. a shared trace id or a
`CandidateScenarioMatch`) is not proof of causation. Nothing here
authorizes execution -- see `catalog/policy/boundary.py` for why a
`RemediationProposal` can never become an `Execution` on its own
authority, regardless of anything in this module.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceProvenance(BaseModel):
    """Where a piece of evidence actually came from -- never implied,
    always explicit, so a reviewer can trace any claim back to its
    source signal."""

    model_config = ConfigDict(extra="forbid")

    source_system: str
    source_identifier: str
    collected_at: str
    collection_method: str


class MeasuredSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_name: str
    observed_value: str
    unit: str | None = None
    expected_or_baseline_value: str | None = None
    evidence: EvidenceProvenance


class CandidateScenarioMatch(BaseModel):
    """A possible link to a catalogued scenario -- always a candidate,
    never an assertion. `match_confidence` and `match_rationale` exist
    specifically so a reviewer can see WHY the match was suggested and
    judge it themselves; a match is never auto-promoted to
    `scenario_id`-equivalent certainty."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^D\d{2}-F\d{2}$")
    match_confidence: float = Field(ge=0.0, le=1.0)
    match_rationale: str


class Observation(BaseModel):
    """A raw, evidence-grounded record of what was actually observed.
    Never itself a diagnosis, never proof of root cause."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    observed_service_or_resource: str
    observation_window_start: str
    observation_window_end: str | None = None
    measured_signals: list[MeasuredSignal] = Field(default_factory=list)
    expected_or_baseline_behavior: str | None = None
    actual_behavior: str
    anomaly_or_invariant_evidence: str | None = None
    relevant_trace_identifiers: list[str] = Field(default_factory=list)
    evidence: EvidenceProvenance


class Hypothesis(BaseModel):
    """A candidate explanation for one or more observations. Explicitly
    NOT a conclusion: `supporting_observation_ids` names the evidence
    it rests on, and `confidence` is always a stated degree of belief,
    never a fact."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    statement: str
    supporting_observation_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    likely_affected_dependencies: list[str] = Field(default_factory=list)
    correlated_alert_identifiers: list[str] = Field(default_factory=list)
    uncertainty_notes: str | None = None


class DiagnosticCheck(BaseModel):
    """A SUGGESTED, read-only follow-up check -- never a remediation,
    never a write/mutating action. Designing/validating this schema
    does not authorize running any check against a live system.
    `read_only` is typed `Literal[True]`, not `bool`, specifically so
    that an explicit `read_only=False` is a `ValidationError`, not a
    silently-accepted value -- a mutating "diagnostic check" is a
    contradiction in terms for this schema."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    hypothesis_id: str
    description: str
    read_only: Literal[True] = True
    expected_evidence_if_hypothesis_true: str


class RemediationProposal(BaseModel):
    """A PROPOSAL only. See `catalog/policy/boundary.py`:
    `requires_human_approval` is typed `Literal[True]`, not `bool` --
    an explicit `requires_human_approval=False` is a `ValidationError`,
    never a silently-accepted value, so nothing in this module can ever
    construct a proposal that claims to bypass approval. A proposal
    existing is still never itself authorization to execute it."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    hypothesis_id: str
    description: str
    requires_human_approval: Literal[True] = True
    risk_notes: str


class Execution(BaseModel):
    """Records that an already-approved action was actually carried
    out through the existing, authoritative deterministic
    remediation/approval system (Phase 8/9) -- this schema does not
    grant or perform execution itself; it only represents the fact of
    one, after the fact, for audit purposes."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    proposal_id: str
    approved_by: str
    executed_at: str
    outcome_summary: str


class RecoveryVerification(BaseModel):
    """Independent confirmation that an executed action actually
    resolved the original observation(s) -- never assumed from the
    execution outcome alone."""

    model_config = ConfigDict(extra="forbid")

    verification_id: str
    execution_id: str
    verified_at: str
    verification_method: str
    resolved: bool
    residual_evidence: str | None = None


class FailureFinding(BaseModel):
    """The top-level, general-purpose incident record. `scenario_id`
    is intentionally ABSENT as a direct field -- only
    `candidate_known_scenario_matches` (always possibly empty) exists,
    so an unknown incident is a fully valid `FailureFinding` with no
    special-casing required anywhere that consumes this schema."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    origin_detector_family_id: str | None = None
    observed_service_or_resource: str
    observation_window_start: str
    observation_window_end: str | None = None

    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    diagnostic_checks: list[DiagnosticCheck] = Field(default_factory=list)
    remediation_proposals: list[RemediationProposal] = Field(default_factory=list)
    executions: list[Execution] = Field(default_factory=list)
    recovery_verifications: list[RecoveryVerification] = Field(default_factory=list)

    candidate_known_scenario_matches: list[CandidateScenarioMatch] = Field(default_factory=list)
    unresolved_classification: bool = True
    classification_uncertainty_notes: str | None = None
    evidence_provenance: list[EvidenceProvenance] = Field(default_factory=list)
    suggested_read_only_diagnostic_checks: list[str] = Field(default_factory=list)
