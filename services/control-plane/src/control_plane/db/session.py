"""Per-request AsyncSession dependency.

The engine and sessionmaker are created once, in the application
lifespan (see main.py), and stored on `app.state` — route handlers
never construct their own engine. This function is overridden in unit
tests via FastAPI's `dependency_overrides` to inject a fake session,
without needing a real database.
"""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.db_sessionmaker
    async with session_factory() as session:
        yield session
