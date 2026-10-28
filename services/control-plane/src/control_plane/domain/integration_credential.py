"""Phase 16 Gate 2/3: integration-credential request/response models.

`IntegrationCredentialCreated` is the ONE response shape that ever
carries a real secret value -- returned ONLY from the create endpoint,
exactly once, never persisted anywhere this model's own caller could
re-read it later. Every other model here (`IntegrationCredential`) is
the secret-free, list/display-safe view.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectionType = Literal["opentelemetry"]
CredentialStatus = Literal["active", "revoked"]


class IntegrationCredential(BaseModel):
    """The secret-free view -- safe to list, log, or render in the UI.
    Never includes credential_secret_hash, let alone a plaintext
    secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    service_id: uuid.UUID
    connection_type: ConnectionType
    credential_id: str
    status: CredentialStatus
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None
    last_verified_telemetry_at: datetime | None


class IntegrationCredentialListResponse(BaseModel):
    items: list[IntegrationCredential]


class CreateIntegrationCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_type: ConnectionType = Field(default="opentelemetry")


class IntegrationCredentialCreated(BaseModel):
    """Returned ONLY once, from POST .../integrations. `bearer_token`
    is the full `<credential_id>.<secret>` string a real client sends
    as `Authorization: Bearer <this>` -- shown here and NEVER again;
    this service stores only a hash of the secret portion."""

    model_config = ConfigDict(from_attributes=True)

    credential: IntegrationCredential
    bearer_token: str
