from fastapi import FastAPI

from payment_service.api.health import router as health_router

app = FastAPI(title="Autonomous Reliability Platform Payment Service")

app.include_router(health_router)
