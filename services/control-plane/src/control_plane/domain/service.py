"""Phase 15 Gate 7: the services registry's response/request models.

Field set matches database/migrations/V12__create_services_registry.sql
exactly. Deliberately no `health`/`connection_status`/`last_observed_at`
field anywhere on this model -- see that migration's own docstring for
why: this platform has no real telemetry-correlation capability yet to
honestly populate one. Every caller (the web console in particular)
must treat the ABSENCE of such a field as the honest signal it is,
never assume or render a fabricated "healthy"/"connected" state for a
registered service.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceKind = Literal[
    "rest_api",
    "graphql_api",
    "microservice",
    "database",
    "queue_worker",
    "kubernetes_workload",
    "cloud_resource",
    "other",
]

VALID_SERVICE_KINDS: frozenset[str] = frozenset(ServiceKind.__args__)


class Service(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    kind: ServiceKind
    language: str | None
    description: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class ServiceListResponse(BaseModel):
    items: list[Service]
    total: int
    limit: int
    offset: int


class CreateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    kind: ServiceKind
    language: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
