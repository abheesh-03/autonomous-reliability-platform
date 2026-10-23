"""The POST /api/v1/retrieval/search request/response contract (Phase
6 §9). A bounded, read-only search -- the query is never persisted
anywhere, and the request accepts no arbitrary SQL/filter expression,
no provider selection (the active embedding provider is a startup-time
configuration choice, never a per-request parameter).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)
    exclude_incident_id: uuid.UUID | None = None
    knowledge_limit: int = Field(default=3, ge=0, le=50)
    historical_incident_limit: int = Field(default=3, ge=0, le=50)
    # Phase 14 correction round, Issue 2 / Blocker 2: scopes
    # `historical_incident` results to this organization only (never
    # `knowledge` results -- see search.py's own docstring).
    #
    # TRUSTED ONLY in the isolated local-development mode
    # (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT disabled) -- a plain
    # client-supplied field is never proof of real tenant ownership.
    # Once that enforcement is enabled, this value is IGNORED entirely:
    # search.py independently derives the real tenant scope from
    # `exclude_incident_id`'s own, actual organization_id (a direct,
    # trusted database lookup -- see
    # db.get_incident_organization_id / search._resolve_historical_
    # organization_scope), never from this field. Left in the request
    # schema only for the legacy/local-dev path and to avoid breaking
    # existing callers that still send it.
    organization_id: uuid.UUID | None = None


class SearchResultItem(BaseModel):
    """`similarity` is a RETRIEVAL RANKING SCORE ONLY (1 - cosine
    distance) -- it is NOT a probability and NOT an LLM confidence
    value. A higher score means "ranked closer by this embedding
    space", nothing more."""

    model_config = ConfigDict(extra="forbid")

    id: int
    source_type: str
    source_key: str
    title: str
    excerpt: str
    similarity: float
    metadata: dict
    embedding_space: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge: list[SearchResultItem]
    historical_incidents: list[SearchResultItem]
    embedding_space: str
