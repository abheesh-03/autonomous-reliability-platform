"""The normalized evidence package assembled BEFORE any LLM call
(Phase 5 §5). Every field here is bounded, deterministic, and
traceable back to a real query against a real source — nothing in
this module is ever populated from the LLM's own output.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from investigator_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot

EvidenceSource = Literal["control_plane", "prometheus", "loki", "tempo"]

# "ok": the source was reachable and returned at least one relevant
# item. "no_data": the source was reachable but genuinely had nothing
# relevant in the queried window — itself real, reportable evidence,
# never conflated with failure. "unavailable": the source could not be
# queried at all (timeout, connection error, non-2xx, or a malformed/
# unparseable response) — the investigation proceeds without it,
# flagged explicitly as a limitation rather than silently omitted.
# "partial" (Phase 5 correction round #2A): the source WAS reachable
# and DID return real data, but a configured safety bound stopped
# retrieval before the complete, real set was obtained — used today
# only for control-plane's mandatory audit-event retrieval when the
# real total exceeds INVESTIGATOR_MAX_AUDIT_EVENTS. Never conflated
# with "ok" — a partial mandatory retrieval must never be described as
# complete.
CollectionStatus = Literal["ok", "partial", "no_data", "unavailable"]


class SourceOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    status: CollectionStatus
    detail: str
    query_summary: str | None = None


class EvidenceItem(BaseModel):
    """One bounded, attributable fact. `id` is stable within a single
    investigation (E1, E2, ... in deterministic collection order —
    control-plane evidence first, then Prometheus, then Loki, then
    Tempo, each internally ordered by time) so the LLM — and this
    service's own post-validation of the LLM's citations — can refer
    to it unambiguously.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source: EvidenceSource
    observed_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    summary: str
    detail: str
    reference: dict[str, str] = {}


class EvidencePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident: IncidentSnapshot
    events: list[IncidentEventSnapshot]
    events_total: int
    items: list[EvidenceItem]
    source_outcomes: list[SourceOutcome]
    collected_at: datetime

    def evidence_ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.items)
