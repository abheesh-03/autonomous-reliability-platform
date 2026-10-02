"""Bearer-token authentication dependencies for this service's two
trusted internal write endpoints:

- `require_webhook_token` — POST /internal/v1/alertmanager/webhook
  (Phase 3C). Checked against CONTROL_PLANE_WEBHOOK_TOKEN.
- `require_lifecycle_token` — PATCH /api/v1/incidents/{id}/status
  (Phase 3D). Checked against CONTROL_PLANE_LIFECYCLE_TOKEN.

These are deliberately TWO SEPARATE secrets, not one shared token:
Alertmanager must never be able to invoke the human/operator lifecycle
endpoint (it only ever receives the webhook token, via
observability/alertmanager/secrets/webhook-token — see
scripts/init-webhook-secret.sh), and an operator's lifecycle credential
must never double as something an automated alert source could present.
Both share the exact same constant-time comparison logic (via
`_require_token` below) so that guarantee is enforced identically and
isn't duplicated/able to drift between the two.

Every other route in this service — GET /api/v1/*, GET /health/* —
remains unauthenticated, loopback-only local-dev read access, unchanged
by either phase (see docs/api/control-plane.md's security-limitations
section).
"""

import hmac
import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("control_plane.auth")


def _require_token(
    *, state_attr: str, env_var_name: str
) -> Callable[[Request, str | None], Coroutine[Any, Any, None]]:
    async def check(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        # Fail closed: an unset server-side secret means authentication
        # can never succeed, not that it is bypassed. app.state.* is
        # set once at startup (main.py's lifespan). Its value is never
        # logged and never included in any exception or response, here
        # or anywhere else.
        expected = getattr(request.app.state, state_attr, None)
        if not expected:
            logger.warning("request rejected: %s is not configured", env_var_name)
            raise HTTPException(status_code=401, detail="unauthorized")

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="unauthorized")

        supplied = authorization[len("Bearer ") :]
        # Constant-time comparison: a naive `==` leaks timing
        # information proportional to the number of matching leading
        # bytes, a real (if minor, for a local-dev service) side
        # channel. hmac.compare_digest is the standard stdlib way to
        # avoid it.
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    return check


require_webhook_token = _require_token(state_attr="webhook_token", env_var_name="CONTROL_PLANE_WEBHOOK_TOKEN")
require_lifecycle_token = _require_token(state_attr="lifecycle_token", env_var_name="CONTROL_PLANE_LIFECYCLE_TOKEN")
