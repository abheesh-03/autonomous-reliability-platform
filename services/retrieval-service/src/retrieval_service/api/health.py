"""Liveness and readiness.

/health/live never touches the database -- this service's process
being up is independently meaningful even if PostgreSQL is briefly
unavailable.

/health/ready reports BOTH the database connection and the configured
embedding provider honestly, matching investigator-service's and
control-plane's own non-blocking-startup philosophy: a temporarily
unavailable retrieval-service (Phase 6 §16) must be distinguishable
from "it is running but degraded", so investigator-service's own
readiness is never forced to fail just because this optional service
is briefly down.
"""

import logging

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("retrieval_service.api.health")

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "UP"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict:
    pool = request.app.state.pool
    embedding_provider = request.app.state.embedding_provider

    db_ok = True
    try:
        await pool.fetchval("SELECT 1")
    except Exception:  # noqa: BLE001 -- any DB failure means "not ready", not a 500
        logger.warning("database not reachable during readiness check", exc_info=True)
        db_ok = False

    body = {
        "status": "ready" if db_ok else "not ready",
        "database": {"reachable": db_ok},
        "embedding_provider": {
            "provider": embedding_provider.name,
            "model": embedding_provider.model,
            "embedding_space": embedding_provider.embedding_space,
        },
    }
    if not db_ok:
        response.status_code = 503
    return body
