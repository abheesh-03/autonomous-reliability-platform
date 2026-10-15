"""Phase 6 §13's RAG response contract: retrieved context, kept
EXPLICITLY separate from Phase 5's current-incident evidence (E
items). A `RetrievedContextItem` is never an `EvidenceItem` — it has
no `evidence_ids`-shaped field, and the two are rendered/cited under
entirely different id namespaces (K<n>/H<n> vs E<n>, see llm/prompt.py
and llm/validation.py) so they can never be confused with each other
in the response or collapsed together by a caller.

`outcome` distinguishes three cases (Phase 6 §16):
  - "ok": retrieval-service was reachable and returned at least one
    result in at least one of the two groups.
  - "no_data": retrieval-service was reachable but returned zero
    results in both groups -- itself real, honest information, never
    conflated with "unavailable".
  - "unavailable": retrieval-service could not be reached at all (or
    returned a malformed/error response) -- the investigation still
    proceeds using Phase 5 evidence alone; no fallback/invented
    historical knowledge is ever substituted.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

RetrievalOutcome = Literal["ok", "no_data", "unavailable"]


class RetrievedContextItem(BaseModel):
    """One retrieved knowledge or historical-incident chunk, as shown
    to the model under its own K<n>/H<n> id (see llm/prompt.py) --
    never an E id, and never treated as evidence about the current
    incident."""

    model_config = ConfigDict(extra="forbid")

    context_id: str
    source_type: Literal["knowledge", "historical_incident"]
    source_key: str
    title: str
    excerpt: str
    similarity: float
    metadata: dict = {}
    embedding_space: str


class RetrievalContext(BaseModel):
    """The full retrieval_context field of InvestigationReport (Phase
    6 §13)."""

    model_config = ConfigDict(extra="forbid")

    knowledge: list[RetrievedContextItem] = []
    historical_incidents: list[RetrievedContextItem] = []
    outcome: RetrievalOutcome
    detail: str = ""
