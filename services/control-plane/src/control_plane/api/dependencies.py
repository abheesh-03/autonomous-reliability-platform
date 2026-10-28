"""Shared FastAPI dependencies for the API layer.

Routes depend on `get_incident_repository`, not on `get_session`
directly — this is the seam unit tests override (via
`app.dependency_overrides`) to inject a fake repository with canned
responses, without needing a real database or a faked SQLAlchemy
session/result object.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.db.session import get_session
from control_plane.repositories.auth_membership_repository import AuthMembershipRepository
from control_plane.repositories.dashboard_repository import DashboardRepository
from control_plane.repositories.incident_repository import IncidentRepository
from control_plane.repositories.integration_credential_repository import IntegrationCredentialRepository
from control_plane.repositories.remediation_repository import RemediationRepository
from control_plane.repositories.service_repository import ServiceRepository
from control_plane.repositories.telemetry_repository import TelemetryRepository


async def get_incident_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentRepository:
    return IncidentRepository(session)


async def get_auth_membership_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthMembershipRepository:
    # Phase 14 correction round, Blocker 4: same request-scoped session
    # as every other repository -- a read-only cross-schema SELECT, no
    # transactional interaction with the remediation decision itself.
    return AuthMembershipRepository(session)


async def get_remediation_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RemediationRepository:
    # Phase 8: constructed from the SAME request-scoped session as
    # get_incident_repository would be for the same request -- this is
    # what lets api/remediation.py's decide()/record_execution_result()
    # perform a remediation-proposal mutation and an incident-lifecycle
    # mutation in ONE atomic transaction (see
    # repositories/remediation_repository.py's own docstring).
    return RemediationRepository(session)


async def get_dashboard_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DashboardRepository:
    # Phase 15: read-only, so sharing the request-scoped session has no
    # transactional consequence -- same convention as every other
    # repository dependency above.
    return DashboardRepository(session)


async def get_service_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ServiceRepository:
    return ServiceRepository(session)


async def get_integration_credential_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrationCredentialRepository:
    return IntegrationCredentialRepository(session)


async def get_telemetry_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TelemetryRepository:
    return TelemetryRepository(session)
