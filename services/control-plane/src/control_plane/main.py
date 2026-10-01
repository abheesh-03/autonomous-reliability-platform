"""FastAPI application factory.

Startup/shutdown lifecycle (see the `lifespan` context manager below)
constructs the database engine once and disposes it once — route
handlers never build their own engine. Engine construction is
non-blocking (see db/engine.py's docstring): this process starts and
stays alive even if PostgreSQL is not yet reachable or
reliability.incidents has not been migrated yet, which the existing
`flyway` Compose service (profiles: ["tools"]) does not do
automatically. GET /health/ready is the only thing that actually
reports this.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from control_plane.api.health import router as health_router
from control_plane.api.incidents import router as incidents_router
from control_plane.core.config import DatabaseSettings
from control_plane.db.engine import create_engine

logger = logging.getLogger("control_plane")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings.from_env()
    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        # Clean engine disposal on shutdown: closes every pooled
        # connection instead of leaking sockets on restart/redeploy.
        await engine.dispose()


app = FastAPI(
    title="Autonomous Reliability Platform Control Plane",
    description=(
        "Read-only Phase 3B API over reliability.incidents. No alert "
        "ingestion (Phase 3C) and no lifecycle transitions (Phase 3D) "
        "exist yet. Local development only — no authentication."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(incidents_router)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # A single, consistent translation point for "the database is
    # temporarily unavailable" (connection refused, pool timeout,
    # schema/table not migrated yet, etc.) into HTTP 503 — applied to
    # every route uniformly, rather than duplicated try/except blocks
    # per handler. The exception (which can contain connection
    # details) is logged server-side only; the HTTP response body never
    # includes it, never includes the connection string, and never
    # includes credentials.
    logger.error("database error handling %s %s", request.method, request.url.path, exc_info=True)
    return JSONResponse(status_code=503, content={"detail": "database temporarily unavailable"})
