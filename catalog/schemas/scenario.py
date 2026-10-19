"""Gate B: the normalized scenario record schema.

One `ScenarioRecord` per `### D<NN>-F<NN>` entry in
`catalog/source/40-domains-800-scenarios.md`. Every field below is
REQUIRED and preserves the source text verbatim (trimmed of
surrounding whitespace only) -- this module never rewrites, corrects,
summarizes, or silently drops a field. A taxonomy review (Gate C,
`catalog/reviews/`) may flag a field as questionable; it never edits
this record.

`original_*` field names are deliberate: they make explicit that the
source document's own classification (failure class, severity,
automation label) is being preserved AS DOCUMENTATION, never
re-asserted as this system's own authoritative judgment. See Gate G
(`catalog/policy/`) for why `original_automation_label` can never
authorize an executable action.
"""

from pydantic import BaseModel, ConfigDict, Field

FailureClass = str  # 20 recurring values in the real source; not a closed enum here (Gate B never invents a stricter contract than the source actually has -- see validation.py for the exact observed set check)
DefaultSeverity = str  # observed: "Critical" | "High" | "Medium" (no "Low" scenario exists in the source)
AutomationLabel = str  # observed: "Guarded automatic action" | "Human approval required" | "Investigate / propose fix"


class SourceProvenance(BaseModel):
    """Exact traceability back to the source document -- Gate B's own
    'source-to-output traceability' requirement. Never a vague claim;
    always the literal line range this record was parsed from."""

    model_config = ConfigDict(extra="forbid")

    source_file: str
    source_sha256: str
    heading_line: int
    block_start_line: int
    block_end_line: int


class ScenarioRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^D\d{2}-F\d{2}$")
    domain_id: str = Field(pattern=r"^D\d{2}$")
    domain_name: str
    title: str
    original_failure_class: FailureClass
    original_default_severity: DefaultSeverity
    original_automation_label: AutomationLabel
    detection_description: str
    instrumentation_description: str
    likely_causes: str
    triage_description: str
    potential_remediation: str
    verification_description: str
    source_file: str
    source_provenance: SourceProvenance
    catalog_version: str
