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


async def get_incident_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentRepository:
    return IncidentRepository(session)
