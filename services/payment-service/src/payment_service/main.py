from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from payment_service.api.faults import router as faults_router
from payment_service.api.health import router as health_router
from payment_service.api.payments import router as payments_router
from payment_service.config import FaultInjectionSettings
from payment_service.fault_state import AuthorizationFaultState


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Phase 8: one process-local fault flag (fault_state.py's own
    # docstring explains why -- never persisted, never shared across
    # replicas, reset on restart) plus the two separate, never-
    # interchangeable Bearer tokens that guard enabling vs.
    # clearing/reading it. Same non-blocking-startup philosophy every
    # other service in this platform already follows: an unconfigured
    # token just makes its own endpoint fail closed, never a crash.
    settings = FaultInjectionSettings.from_env()
    app.state.fault_state = AuthorizationFaultState()
    app.state.fault_injection_settings = settings
    app.state.fault_injection_token = settings.injection_token
    app.state.fault_remediation_token = settings.remediation_token
    yield


app = FastAPI(title="Autonomous Reliability Platform Payment Service", lifespan=lifespan)

app.include_router(health_router)
app.include_router(payments_router)
app.include_router(faults_router)
