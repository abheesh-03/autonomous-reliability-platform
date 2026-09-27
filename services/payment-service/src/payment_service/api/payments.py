from fastapi import APIRouter

from payment_service.models.payment import AuthorizePaymentRequest, AuthorizePaymentResponse
from payment_service.services.authorization import authorize_payment

router = APIRouter()


@router.post("/payments/authorize", response_model=AuthorizePaymentResponse)
def authorize(request: AuthorizePaymentRequest) -> AuthorizePaymentResponse:
    return authorize_payment(request)
