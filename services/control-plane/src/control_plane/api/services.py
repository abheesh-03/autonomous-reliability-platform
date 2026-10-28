"""Phase 15 Gate 7: the services registry's two real endpoints --
list and create, nothing else yet (no update/delete this phase; see
docs/architecture/phase-15-product-experience.md's "known limitations"
section). Both ALWAYS require a real, verified actor (never the
nullable `get_actor_context` every other read endpoint in this service
uses) -- see core/authz.py::require_actor_context's own docstring for
why this brand-new resource has no legacy-mode exception.

Independent-review correction round, BLOCKER 2: `create_service`
additionally enforces `ROLES_THAT_MAY_REGISTER_SERVICES` -- a real
organization MUTATION, unlike the list endpoint (every member may
read the catalog, matching every other resource's own read policy).

Independent-review correction round, BLOCKER 4: `list_services` is now
genuinely paginated (bounded `limit`/`offset`, a real COUNT-based
`total`) -- mirrors api/incidents.py's own `limit`/`offset` Query
bounds exactly, so the two list endpoints never silently diverge in
contract shape.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from control_plane.api.dependencies import get_service_repository
from control_plane.core.authz import ActorContext, require_actor_context, require_role
from control_plane.core.authz import ROLES_THAT_MAY_REGISTER_SERVICES
from control_plane.domain.service import (
    CreateServiceRequest,
    Service,
    ServiceListResponse,
)
from control_plane.repositories.service_repository import ServiceAlreadyExistsError, ServiceRepository

router = APIRouter(prefix="/api/v1")


@router.get("/services", response_model=ServiceListResponse)
async def list_services(
    repo: Annotated[ServiceRepository, Depends(get_service_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> ServiceListResponse:
    rows, total = await repo.list_services(actor.organization_id, limit=limit, offset=offset)
    return ServiceListResponse(
        items=[Service.model_validate(dict(row)) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/services/{service_id}", response_model=Service)
async def get_service(
    service_id: str,
    repo: Annotated[ServiceRepository, Depends(get_service_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
) -> Service:
    """Phase 16 Gate 5/7: the Services detail page's own data source --
    404 (never any other status) for a service that does not exist OR
    belongs to a different organization, the same convention every
    other cross-tenant lookup in this service already uses."""
    row = await repo.get_by_id_for_organization(actor.organization_id, service_id)
    if row is None:
        raise HTTPException(status_code=404, detail="service not found")
    return Service.model_validate(dict(row))


@router.post("/services", response_model=Service, status_code=201)
async def create_service(
    body: CreateServiceRequest,
    repo: Annotated[ServiceRepository, Depends(get_service_repository)],
    actor: Annotated[ActorContext, Depends(require_actor_context)],
) -> Service:
    require_role(actor, ROLES_THAT_MAY_REGISTER_SERVICES, action="register a service")
    try:
        row = await repo.create_service(
            organization_id=actor.organization_id,
            name=body.name,
            kind=body.kind,
            language=body.language,
            description=body.description,
            created_by_user_id=actor.user_id,
        )
    except ServiceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail=f"a service named {body.name!r} is already registered in this organization"
        ) from exc
    return Service.model_validate(dict(row))
