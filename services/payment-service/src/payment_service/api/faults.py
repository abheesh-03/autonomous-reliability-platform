"""Phase 8 controlled authorization-fault endpoints.

Three tightly-scoped internal endpoints, one boolean fault mode only
-- never arbitrary delays, arbitrary status codes, arbitrary Python
execution, or arbitrary exception injection (Phase 8 §PAYMENT INTERNAL
CONTROL ENDPOINTS). See fault_state.py and api/auth.py for the actual
state/token mechanics; this module only wires request/response shaping
to them.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from payment_service.api.auth import require_fault_injection_token, require_remediation_token
from payment_service.models.faults import FaultClearResponse, FaultStatusResponse

router = APIRouter(prefix="/internal/v1/faults")


@router.post(
    "/authorization/enable",
    response_model=FaultStatusResponse,
    dependencies=[Depends(require_fault_injection_token)],
)
def enable_authorization_fault(request: Request) -> FaultStatusResponse:
    """Test/operator failure-injection path ONLY -- tool-gateway never
    receives PAYMENT_FAULT_INJECTION_TOKEN and therefore can never call
    this. Also refuses safely (403) if
    PAYMENT_FAULT_INJECTION_ENABLED is not explicitly true -- a
    correctly-held token alone is not enough; this mechanism must be
    explicitly opted into (Compose/CI only), never active by accident
    in an environment that didn't ask for it.
    """
    settings = request.app.state.fault_injection_settings
    if not settings.enabled:
        raise HTTPException(
            status_code=403,
            detail="fault injection is disabled (PAYMENT_FAULT_INJECTION_ENABLED is not true)",
        )
    request.app.state.fault_state.enable()
    return FaultStatusResponse(active=True)


@router.post(
    "/authorization/clear",
    response_model=FaultClearResponse,
    dependencies=[Depends(require_remediation_token)],
)
def clear_authorization_fault(request: Request) -> FaultClearResponse:
    """The ONE endpoint tool-gateway may call. Idempotent: clearing an
    already-inactive fault is always a safe 200, never an error."""
    result = request.app.state.fault_state.clear()
    return FaultClearResponse(**result)


@router.get(
    "/authorization",
    response_model=FaultStatusResponse,
    dependencies=[Depends(require_remediation_token)],
)
def get_authorization_fault(request: Request) -> FaultStatusResponse:
    """Read-only. Authenticated with the SAME remediation token as
    CLEAR (never the injection token) -- this is what lets
    tool-gateway independently verify the fault's real state using
    only the one credential it holds (Phase 8 §TOOL-GATEWAY
    PRECONDITION ENDPOINT)."""
    return FaultStatusResponse(active=request.app.state.fault_state.is_active())
