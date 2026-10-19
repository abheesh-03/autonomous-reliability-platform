"""Gate F: the honest coverage/capability-evidence model.

Eight dimensions, tracked INDEPENDENTLY per scenario -- never assumed
sequential, never auto-derived from each other. `catalogued` is the
only dimension this module may ever set without external evidence
(being present in the built catalog IS the evidence for that one
dimension). Every dimension above it requires an explicit
`CapabilityEvidence` record naming the concrete artifact that backs
the claim; with no evidence, `catalog.coverage.tracker` reports zero
for that dimension -- it never infers or invents partial credit.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class CoverageDimension(str, Enum):
    CATALOGUED = "catalogued"
    TAXONOMY_REVIEWED = "taxonomy_reviewed"
    INSTRUMENTED = "instrumented"
    DETECTOR_IMPLEMENTED = "detector_implemented"
    DETECTION_VALIDATED = "detection_validated"
    INVESTIGATION_VALIDATED = "investigation_validated"
    REMEDIATION_SUPPORTED = "remediation_supported"
    RECOVERY_VERIFICATION_VALIDATED = "recovery_verification_validated"


class EvidenceKind(str, Enum):
    TEST_REFERENCE = "test_reference"
    DETECTOR_IMPLEMENTATION_REFERENCE = "detector_implementation_reference"
    INTEGRATION_FIXTURE = "integration_fixture"
    ACCEPTANCE_RESULT = "acceptance_result"
    REVIEWED_POLICY_IDENTIFIER = "reviewed_policy_identifier"
    RECOVERY_VERIFICATION_ARTIFACT = "recovery_verification_artifact"


class CapabilityEvidence(BaseModel):
    """A single, concrete, checkable artifact backing one coverage
    claim for one scenario and one dimension. `evidence_reference`
    must point at something real and inspectable (a test node id, a
    module path, a fixture file, a policy identifier) -- never a bare
    assertion."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    dimension: CoverageDimension
    evidence_kind: EvidenceKind
    evidence_reference: str
    recorded_by: str
    detector_family_id: str | None = None
    notes: str | None = None
