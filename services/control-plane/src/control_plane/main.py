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

As of Phase 3C, lifespan also reads the webhook Bearer token once
(WebhookSettings.from_env()) and stores it on app.state — see
api/webhook_auth.py and api/webhook.py. This never blocks startup
either: an absent token simply means every webhook request fails
closed (401), the same non-blocking-startup philosophy as the database
engine above.
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
from control_plane.api.webhook import router as webhook_router
from control_plane.api.webhook_limits import WebhookBodySizeLimitMiddleware
from control_plane.core.config import DatabaseSettings, WebhookSettings
from control_plane.db.engine import create_engine

logger = logging.getLogger("control_plane")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings.from_env()
    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app.state.webhook_token = WebhookSettings.from_env().token
    try:
        yield
    finally:
        # Clean engine disposal on shutdown: closes every pooled
        # connection instead of leaking sockets on restart/redeploy.
        await engine.dispose()


app = FastAPI(
    title="Autonomous Reliability Platform Control Plane",
    description=(
        "Read-only API over reliability.incidents (GET /api/v1/incidents, "
        "GET /api/v1/incidents/{id}), plus, as of Phase 3C, one trusted "
        "internal write path: POST /internal/v1/alertmanager/webhook, "
        "which requires 'Authorization: Bearer <token>' and ingests real "
        "firing Alertmanager alerts as reliability.incidents rows "
        "(deduplicated per-fingerprint via a real PostgreSQL upsert). "
        "Resolved alert notifications are accepted and acknowledged but "
        "do not change any incident's lifecycle status yet — no "
        "lifecycle transitions exist until Phase 3D. Local development "
        "only — the read API has no authentication at all."
    ),
    lifespan=lifespan,
)

# Must be ASGI middleware, not a route dependency — see
# api/webhook_limits.py's own docstring for why a FastAPI Depends()
# cannot genuinely enforce a body-size limit (the body is already
# fully read before any dependency runs). Internally scoped to only
# POST /internal/v1/alertmanager/webhook; every other route is
# unaffected.
app.add_middleware(WebhookBodySizeLimitMiddleware)

app.include_router(health_router)
app.include_router(incidents_router)
app.include_router(webhook_router)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    # A single, consistent translation point for "the database is
    # temporarily unavailable" into HTTP 503 — applied to every route
    # uniformly, rather than duplicated try/except blocks per handler.
    # The exception (which can contain connection details) is logged
    # server-side only; the HTTP response body never includes it, never
    # includes the connection string, and never includes credentials.
    logger.error("database error handling %s %s", request.method, request.url.path, exc_info=True)
    return JSONResponse(status_code=503, content={"detail": "database temporarily unavailable"})


# SQLAlchemyError covers the large majority of real failure modes
# (connection refused, pool checkout timeout, a genuine query error
# against a not-yet-migrated schema). It does NOT cover every possible
# connection-establishment failure, though: a Phase 3C real-outage
# test (scripts/verify-webhook-ingestion.sh) found that fully stopping
# PostgreSQL (docker compose stop, not restart) can make the
# "postgres" hostname itself stop resolving inside the Compose
# network, which asyncpg/SQLAlchemy's asyncpg dialect — confirmed by
# reading the real traceback — re-raises as the raw
# socket.gaierror it originated as, never wrapped into a
# SQLAlchemyError at all. This app's only external I/O dependency is
# PostgreSQL (no other network call exists anywhere in this service),
# so it is safe and correct to also treat any OSError reaching this
# level (gaierror, ConnectionRefusedError, a bare socket timeout, ...)
# as the database being temporarily unavailable, not an unrelated bug.
app.add_exception_handler(SQLAlchemyError, _database_unavailable)
app.add_exception_handler(OSError, _database_unavailable)
