from fastapi import FastAPI

from payment_service.api.health import router as health_router
from payment_service.api.payments import router as payments_router

app = FastAPI(title="Autonomous Reliability Platform Payment Service")

app.include_router(health_router)
app.include_router(payments_router)
