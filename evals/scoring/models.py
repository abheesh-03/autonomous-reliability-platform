"""Shared schema for every evaluation case and every scoring result.

Deliberately generic at the top level (`input`/`expected_outcome` stay
as plain dicts here) -- each scoring module (citation.py, retrieval.py,
investigation_quality.py, remediation_safety.py) owns the narrow,
mode-specific shape it actually expects and validates that itself, so
adding a new evaluation mode never requires widening this shared model.

PASS / FAIL / NOT_EVALUATED (never a bare boolean): a case whose
required measurement could not be taken at all (a missing fixture
file, an exception while constructing the real production objects the
case depends on) is NOT_EVALUATED, never silently counted as a PASS.
Only a check the harness actually performed may ever report PASS or
FAIL.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvaluationMode = Literal[
    "citation",
    "retrieval",
    "investigation_quality",
    "remediation_safety",
    "adversarial_deterministic",
]

ProvenanceKind = Literal["synthetic", "real_corpus", "real_fixture"]


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProvenanceKind
    notes: str


class Case(BaseModel):
    """One versioned, reviewable evaluation case -- see
    evals/cases/v1/*.json for real examples and evals/README.md for
    the full field-by-field contract."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    dataset_version: str
    category: str
    scenario_description: str
    evaluation_mode: EvaluationMode
    provenance: Provenance
    ground_truth_rationale: str
    input: dict[str, Any]
    expected_outcome: dict[str, Any]
    acceptable_variations: list[str] = Field(default_factory=list)
    forbidden_outcomes: list[str] = Field(default_factory=list)
    # A HARD safety invariant (e.g. "rejection must never execute")
    # failing always fails the offline evaluation outright. A SOFT
    # quality metric (e.g. retrieval MRR, investigation classification)
    # is reported and compared against its documented threshold/
    # baseline, but is never conflated with a safety violation.
    is_hard_safety_invariant: bool = False


class Result(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    evaluation_mode: EvaluationMode
    result: Result
    is_hard_safety_invariant: bool
    detail: str
    # Soft, numeric measurements this case's scoring module actually
    # computed (e.g. {"hit_at_5": 1.0, "mrr": 0.5}) -- empty when the
    # case has no soft metric of its own (e.g. a pure safety check).
    metrics: dict[str, float] = Field(default_factory=dict)


class RegressionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    baseline_result: Result
    current_result: Result
    is_hard_safety_invariant: bool
    detail: str


class MetricDrift(BaseModel):
    """A SOFT, informational signal only -- see RunReport.exit_code()'s
    own docstring. Numeric metric drift (e.g. a retrieval
    reciprocal_rank dropping from 1.0 to 0.5) is reported and made
    visible in both the JSON and Markdown reports even when the case's
    own PASS/FAIL outcome is unchanged, but it never by itself gates
    CI -- there is no arbitrary accuracy threshold here, only an
    honest delta against the last reviewed baseline."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    metric_name: str
    baseline_value: float
    current_value: float
    delta: float


class Baseline(BaseModel):
    """The versioned regression baseline's own schema
    (evals/datasets/<version>/regression_baseline.json) -- validated,
    never treated as a bare untyped dict, so a malformed or
    wrong-dataset-version baseline fails closed with a clear error
    instead of silently comparing against nothing (see
    evals/scoring/regression.py's own BaselineError/BaselineMissingError)."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    results: dict[str, Result]
    # Keyed by case_id, then metric name -> value. Empty for a case
    # that recorded no soft numeric metric of its own (e.g. a pure
    # safety check) -- never fabricated.
    metrics: dict[str, dict[str, float]] = Field(default_factory=dict)


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    generated_at: str
    runtime_seconds: float
    evaluated_case_count: int
    passed: int
    failed: int
    not_evaluated: int
    safety_violations: list[str]
    case_results: list[CaseResult]
    regression_findings: list[RegressionFinding] = Field(default_factory=list)
    metric_drift: list[MetricDrift] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    # Populated only when the optional real-model mode actually ran a
    # real provider; absent (not a fabricated "n/a") in offline mode.
    real_provider: dict[str, str] | None = None

    def exit_code(self) -> int:
        """Nonzero if ANY case FAILed, any hard safety invariant
        regressed, OR any case (hard OR soft) is NOT_EVALUATED.

        A required measurement that could not be taken is an
        INCOMPLETE benchmark, never a passing one -- this is why
        `not_evaluated > 0` alone is now sufficient to fail the run,
        independent of `failed`/`safety_violations`. This is
        deliberately NEVER achieved by folding NOT_EVALUATED cases
        into `safety_violations` itself (that list stays reserved for
        genuine, detected hard-FAIL safety violations) -- a missing
        measurement and a DETECTED violation are different facts, and
        conflating them would fabricate a safety violation that was
        never actually observed."""
        if self.failed > 0 or self.safety_violations:
            return 1
        if self.not_evaluated > 0:
            return 1
        if any(f.is_hard_safety_invariant for f in self.regression_findings):
            return 1
        return 0

    def is_fully_successful(self) -> bool:
        """Stricter than `exit_code() == 0`: used ONLY to gate whether
        `--update-baseline` may replace the reviewed baseline file.
        Deliberately ignores `regression_findings` (which compare
        against the OLD baseline this run may be about to replace) --
        what matters for a baseline UPDATE is that every case in THIS
        run was itself a clean, real PASS, never that it agreed with
        whatever the previous baseline happened to say."""
        return self.failed == 0 and self.not_evaluated == 0 and not self.safety_violations
