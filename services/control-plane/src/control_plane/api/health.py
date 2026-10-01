"""Liveness and readiness endpoints.

/health/live never touches the database — it only proves the FastAPI
process itself is running, so Docker's healthcheck (see
docker-compose.yml) can report this container as up well before any
migration has been applied.

/health/ready performs a real query against reliability.incidents and
reports 503 whenever that fails for any reason (PostgreSQL unreachable,
not yet healthy, or the table/schema not yet migrated) — it never
raises, and never echoes the underlying error back to the caller (see
docs/api/control-plane.md's error-handling section for why).
"""

import logging

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("control_plane.health")

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "UP"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    engine = request.app.state.db_engine
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1 FROM reliability.incidents LIMIT 1"))
    except Exception:
        # Logged server-side only (for operator diagnosis); the HTTP
        # response never includes the exception message, which could
        # otherwise surface connection details.
        logger.warning("readiness check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})
