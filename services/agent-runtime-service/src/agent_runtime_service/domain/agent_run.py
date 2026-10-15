"""The agent-run API contract (Phase 7 §API) -- a closed, Pydantic
response shape. Never exposes a raw LangGraph checkpoint blob, a
database internal, a secret, or a raw provider exception -- only
already-bounded/redacted workflow data (Phase 5/6's own bounding/
redaction guarantees are preserved end to end: this service never
re-collects or re-renders evidence text itself, it only carries
through what investigator-service already produced and validated).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport

AgentRunStatus = Literal["running", "completed", "failed"]
# Phase 7 correction round (finding #12): renamed from "conclusive" --
# that word implied a confirmed root cause; this is orchestration
# metadata derived from the model's OWN declared confidence and never
# a claim stronger than investigator-service's own Phase 5/6 epistemic
# boundary (confirmed observation vs. unconfirmed hypothesis) already
# makes. See graph/nodes.py::classify_investigation for the exact
# definition of each value.
ResultQuality = Literal["well_supported", "inconclusive", "partial"]


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID


class AgentRun(BaseModel):
    """A safe, normalized view of one durable agent run -- loaded from
    the real LangGraph checkpoint state (see api/agent_runs.py), never
    a raw checkpoint payload."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    thread_id: str
    incident_id: uuid.UUID
    status: AgentRunStatus
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    current_node: str
    completed_nodes: list[str] = Field(default_factory=list)
    incident_snapshot: IncidentSnapshot | None = None
    investigation_report: InvestigationReport | None = None
    result_quality: ResultQuality | None = None
    validation_notes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    resumable: bool


class AgentRunHistoryEntry(BaseModel):
    """One durable checkpoint, as SAFE metadata only -- never the raw
    checkpoint binary/JSON blob itself (Phase 7 §API: "Do not expose
    raw checkpoint blobs")."""

    model_config = ConfigDict(extra="forbid")

    step: int
    checkpoint_id: str
    node: str
    status_at_step: AgentRunStatus
    created_at: datetime
    next_nodes: list[str] = Field(default_factory=list)


class AgentRunHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    thread_id: str
    entries: list[AgentRunHistoryEntry]
