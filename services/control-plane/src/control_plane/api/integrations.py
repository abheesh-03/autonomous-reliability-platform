"""Phase 16 Gate 2/3: the real OpenTelemetry integration-credential
lifecycle -- create (shows the secret once), list (secret-free), and
revoke. Every route here ALWAYS requires a real, verified actor via
`require_actor_context` (the same unconditional dependency Phase 15's
services registry established), never the nullable `get_actor_context`.

Mutations (create/revoke) additionally require
`ROLES_THAT_MAY_REGISTER_SERVICES` (OWNER/ADMIN/ENGINEER) -- Gate 2:
"Do not allow VIEWER or INCIDENT_APPROVER to create integration
credentials." Reused directly from core/authz.py rather than a new,
parallel constant: creating a credential is the same class of
organization-scoped operational mutation service registration already
is, and Phase 15's own role matrix already answered exactly this
question for exactly this set of roles.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from control_plane.api.dependencies import (
    get_integration_credential_repository,
    get_service_repository,
)
from control_plane.core.authz import ROLES_THAT_MAY_REGISTER_SERVICES, ActorContext, require_actor_context, require_role
from control_plane.core.credentials import (
    format_bearer_token,
    generate_credential_id,
    generate_secret,
    hash_secret,
)
from control_plane.domain.integration_credential import (
    CreateIntegrationCredentialRequest,
    IntegrationCredential,
    IntegrationCredentialCreated,
    IntegrationCredentialListResponse,
)
from control_plane.repositories.integration_credential_repository import IntegrationCredentialRepository
from control_plane.repositories.service_repository import ServiceRepository

router = APIRouter(prefix="/api/v1")


async def _require_owned_service(
    repo: ServiceRepository, actor: ActorContext, service_id: str
) -> None:
    """Gate 2: "a service belongs to exactly one organization." 404
    (never 403) if the service does not exist OR belongs to a
    different organization -- this service never confirms to an actor
    that a cross-tenant service id exists at all, the same convention
    `require_same_organization` already established for incidents."""
    service = await repo.get_by_id_for_organization(actor.organization_id, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="service not found")


@router.post(
    "/services/{service_id}/integrations",
    response_model=IntegrationCredentialCreated,
    status_code=201,
)
async def create_integration_credential(
    service_id: str,
    body: CreateIntegrationCredentialRequest,
    services: Annotated[ServiceRepository, Depends(get_service_repository)],
    repo: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
) -> IntegrationCredentialCreated:
    require_role(actor, ROLES_THAT_MAY_REGISTER_SERVICES, action="create an integration credential")
    await _require_owned_service(services, actor, service_id)

    credential_id = generate_credential_id()
    secret = generate_secret()
    row = await repo.create(
        organization_id=actor.organization_id,
        service_id=service_id,
        connection_type=body.connection_type,
        credential_id=credential_id,
        credential_secret_hash=hash_secret(secret),
        created_by_user_id=actor.user_id,
    )
    return IntegrationCredentialCreated(
        credential=IntegrationCredential.model_validate(dict(row)),
        bearer_token=format_bearer_token(credential_id, secret),
    )


@router.get(
    "/services/{service_id}/integrations",
    response_model=IntegrationCredentialListResponse,
)
async def list_integration_credentials(
    service_id: str,
    services: Annotated[ServiceRepository, Depends(get_service_repository)],
    repo: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
) -> IntegrationCredentialListResponse:
    await _require_owned_service(services, actor, service_id)
    rows = await repo.list_for_service(actor.organization_id, service_id)
    return IntegrationCredentialListResponse(items=[IntegrationCredential.model_validate(dict(r)) for r in rows])


@router.post(
    "/services/{service_id}/integrations/{integration_id}/revoke",
    response_model=IntegrationCredential,
)
async def revoke_integration_credential(
    service_id: str,
    integration_id: str,
    services: Annotated[ServiceRepository, Depends(get_service_repository)],
    repo: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
) -> IntegrationCredential:
    require_role(actor, ROLES_THAT_MAY_REGISTER_SERVICES, action="revoke an integration credential")
    await _require_owned_service(services, actor, service_id)

    existing = await repo.get_by_id_for_organization(actor.organization_id, integration_id)
    if existing is None or str(existing["service_id"]) != str(service_id):
        raise HTTPException(status_code=404, detail="integration credential not found")

    row = await repo.revoke(integration_id)
    assert row is not None
    return IntegrationCredential.model_validate(dict(row))
