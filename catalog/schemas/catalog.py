"""The full, versioned, normalized catalog -- Gate B's own build
output. Includes the source document's own preamble/closing guidance
text verbatim (never discarded, per Gate B's "do not silently discard
any fields" requirement, which this module reads as applying to the
WHOLE document, not only each scenario's own fields)."""

from pydantic import BaseModel, ConfigDict, Field

from catalog.schemas.scenario import ScenarioRecord


class CatalogPreamble(BaseModel):
    """Preserved verbatim from the source document's own introductory
    material (everything before the first domain heading) -- never
    parsed as a scenario, never discarded."""

    model_config = ConfigDict(extra="forbid")

    title: str
    purpose: str
    use_safely: str
    field_guide: str
    shared_reliability_foundation: str


class CatalogClosing(BaseModel):
    """Preserved verbatim from the source document's own
    'Implementation guidance' closing section."""

    model_config = ConfigDict(extra="forbid")

    heading: str
    guidance_items: list[str]


class CatalogManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    source_file: str
    source_sha256: str
    generated_at: str
    scenario_count: int
    domain_count: int
    preamble: CatalogPreamble
    closing: CatalogClosing
    scenarios: list[ScenarioRecord] = Field(default_factory=list)
