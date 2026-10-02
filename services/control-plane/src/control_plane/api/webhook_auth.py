"""Bearer-token authentication for the internal Alertmanager webhook
(Phase 3C). This is the ONLY authenticated route in this service —
every existing GET /api/v1/* and /health/* route remains
unauthenticated, loopback-only local-dev read access, unchanged by
this phase (see docs/api/control-plane.md's security-limitations
section).
"""

import hmac
import logging
from typing import Annotated

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("control_plane.webhook_auth")


async def require_webhook_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    # Fail closed: an unset server-side secret means authentication can
    # never succeed, not that it is bypassed. app.state.webhook_token
    # is set once at startup (main.py's lifespan) from
    # CONTROL_PLANE_WEBHOOK_TOKEN. Its value is never logged and never
    # included in any exception or response, here or anywhere else.
    expected = getattr(request.app.state, "webhook_token", None)
    if not expected:
        logger.warning("alertmanager webhook rejected: CONTROL_PLANE_WEBHOOK_TOKEN is not configured")
        raise HTTPException(status_code=401, detail="unauthorized")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")

    supplied = authorization[len("Bearer ") :]
    # Constant-time comparison: a naive `==` leaks timing information
    # proportional to the number of matching leading bytes, a real
    # (if minor, for a local-dev service) side channel. hmac.compare_digest
    # is the standard stdlib way to avoid it.
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
