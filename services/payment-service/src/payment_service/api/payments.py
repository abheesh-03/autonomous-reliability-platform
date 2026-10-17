from fastapi import APIRouter, HTTPException, Request

from payment_service.models.payment import AuthorizePaymentRequest, AuthorizePaymentResponse
from payment_service.services.authorization import authorize_payment

router = APIRouter()


@router.post("/payments/authorize", response_model=AuthorizePaymentResponse)
def authorize(request: AuthorizePaymentRequest, http_request: Request) -> AuthorizePaymentResponse:
    # Phase 8 §PAYMENT SERVICE CONTROLLED FAULT: a deterministic,
    # non-2xx failure while the controlled authorization fault is
    # active -- checked here (the route handler, which has access to
    # app.state) rather than inside authorize_payment() itself
    # (services/authorization.py stays a pure function with no
    # FastAPI/app-state dependency, unchanged in shape from before this
    # phase). checkout-service's own PaymentClient treats ANY non-2xx
    # response as a downstream failure (confirmed directly against its
    # source: RestClient's default `.retrieve()` raises for any
    # non-2xx status, which checkout's own exception handler then
    # reports as its existing, real `downstream_failure` 502 -- never
    # a fabricated error path invented for this phase), so this is a
    # genuine, deterministic safe failure, not a crash or an arbitrary
    # exception.
    if http_request.app.state.fault_state.is_active():
        raise HTTPException(status_code=502, detail="authorization_fault_active")
    return authorize_payment(request)
