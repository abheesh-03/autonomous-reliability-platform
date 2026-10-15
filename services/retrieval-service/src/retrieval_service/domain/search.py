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
