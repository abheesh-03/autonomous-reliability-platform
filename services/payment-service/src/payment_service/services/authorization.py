import uuid

from payment_service.models.payment import AuthorizePaymentRequest, AuthorizePaymentResponse


def authorize_payment(request: AuthorizePaymentRequest) -> AuthorizePaymentResponse:
    """Simulate a payment authorization. Always succeeds in this phase —
    no real payment provider, no declines, no persistence."""
    return AuthorizePaymentResponse(
        payment_id=str(uuid.uuid4()),
        checkout_id=request.checkout_id,
        status="AUTHORIZED",
        amount_cents=request.amount_cents,
        currency=request.currency,
    )
