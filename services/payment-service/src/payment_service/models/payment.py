from typing import Literal

from pydantic import BaseModel, Field

CURRENCY_PATTERN = r"^[A-Z]{3}$"


class AuthorizePaymentRequest(BaseModel):
    checkout_id: str = Field(..., min_length=1, max_length=100)
    amount_cents: int = Field(..., gt=0)
    currency: str = Field(..., pattern=CURRENCY_PATTERN)


class AuthorizePaymentResponse(BaseModel):
    payment_id: str
    checkout_id: str
    status: Literal["AUTHORIZED"]
    amount_cents: int
    currency: str
