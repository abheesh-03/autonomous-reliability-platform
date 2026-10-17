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
from control_plane.repositories.incident_repository import IncidentRepository
from control_plane.repositories.remediation_repository import RemediationRepository


async def get_incident_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentRepository:
    return IncidentRepository(session)


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
