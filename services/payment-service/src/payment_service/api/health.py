from fastapi import APIRouter

from payment_service.models.health import HealthResponse

SERVICE_NAME = "payment-service"

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="UP", service=SERVICE_NAME)
