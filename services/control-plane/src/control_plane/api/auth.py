"""Bearer-token authentication dependencies for this service's trusted
internal write endpoints:

- `require_webhook_token` — POST /internal/v1/alertmanager/webhook
  (Phase 3C). Checked against CONTROL_PLANE_WEBHOOK_TOKEN.
- `require_lifecycle_token` — PATCH /api/v1/incidents/{id}/status
  (Phase 3D). Checked against CONTROL_PLANE_LIFECYCLE_TOKEN.
- `require_remediation_proposal_token` — POST
  /internal/v1/remediation-proposals (Phase 8). Held ONLY by
  agent-runtime-service. Checked against
  CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN.
- `require_remediation_approver_token` — POST
  /api/v1/remediation-proposals/{id}/decision (Phase 8). Held ONLY by a
  human/operator (or a CI acceptance script simulating one). Checked
  against CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN.
- `require_remediation_executor_token` — POST
  /internal/v1/remediation-proposals/{id}/execution/{start,result}
  (Phase 8). Held ONLY by tool-gateway. Checked against
  CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN.
- `require_kubernetes_ingestion_token` — POST
  /internal/v1/kubernetes/findings (Phase 12B-D). Held ONLY by the
  Kubernetes observation pipeline (detectors/kubernetes, Phase 12A) --
  never by Alertmanager, a human operator, agent-runtime-service, or
  tool-gateway. Checked against CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN.

These are deliberately SIX SEPARATE secrets, never interchangeable:
Alertmanager must never be able to invoke the human/operator lifecycle
endpoint; agent-runtime-service must never be able to approve/reject a
proposal or record an execution result; tool-gateway must never be
able to create or approve a proposal; and a human approver's credential
must never double as anything an automated service could present (see
docs/architecture/phase-8-human-approval-remediation.md's credential
boundary table, and tests/test_remediation.py's explicit cross-token
rejection tests). All five share the exact same constant-time
comparison logic (via `_require_token` below) so that guarantee is
enforced identically and isn't duplicated/able to drift between them.

Every other route in this service — GET /api/v1/*, GET /health/* —
remains unauthenticated, loopback-only local-dev read access, unchanged
by any phase (see docs/api/control-plane.md's security-limitations
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
require_remediation_proposal_token = _require_token(
    state_attr="remediation_proposal_token", env_var_name="CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN"
)
require_remediation_approver_token = _require_token(
    state_attr="remediation_approver_token", env_var_name="CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN"
)
require_remediation_executor_token = _require_token(
    state_attr="remediation_executor_token", env_var_name="CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN"
)
require_kubernetes_ingestion_token = _require_token(
    state_attr="kubernetes_ingestion_token", env_var_name="CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN"
)
