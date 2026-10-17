"""Bearer-token authentication dependencies for payment-service's two
trusted internal fault-control endpoints (Phase 8):

- `require_fault_injection_token` — POST
  /internal/v1/faults/authorization/enable. Checked against
  PAYMENT_FAULT_INJECTION_TOKEN. Used ONLY by the test/operator
  failure-injection path -- tool-gateway must NEVER receive this
  token.
- `require_remediation_token` — POST
  /internal/v1/faults/authorization/clear and GET
  /internal/v1/faults/authorization. Checked against
  PAYMENT_REMEDIATION_TOKEN. This is the ONE token tool-gateway holds.

These are deliberately TWO SEPARATE secrets, never interchangeable:
the execution system that RECOVERS this demo service must never also
be able to CREATE the failure it is supposedly fixing (Phase 8
§SEPARATE FAILURE-INJECTION AND REMEDIATION CREDENTIALS). Both share
the exact same constant-time comparison logic (via `_require_token`
below, the same convention control_plane.api.auth already establishes)
so that guarantee is enforced identically and cannot drift between
them.

POST /payments/authorize itself remains completely unauthenticated,
unchanged by this phase -- it was never a trusted/internal endpoint.
"""

import hmac
import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("payment_service.auth")


def _require_token(
    *, state_attr: str, env_var_name: str
) -> Callable[[Request, str | None], Coroutine[Any, Any, None]]:
    async def check(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        # Fail closed: an unset server-side secret means authentication
        # can never succeed, not that it is bypassed. Never logged,
        # never included in any exception or response.
        expected = getattr(request.app.state, state_attr, None)
        if not expected:
            logger.warning("request rejected: %s is not configured", env_var_name)
            raise HTTPException(status_code=401, detail="unauthorized")

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="unauthorized")

        supplied = authorization[len("Bearer ") :]
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    return check


require_fault_injection_token = _require_token(
    state_attr="fault_injection_token", env_var_name="PAYMENT_FAULT_INJECTION_TOKEN"
)
require_remediation_token = _require_token(
    state_attr="fault_remediation_token", env_var_name="PAYMENT_REMEDIATION_TOKEN"
)
