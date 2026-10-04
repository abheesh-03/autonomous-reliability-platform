"""FastAPI application factory.

Startup (the `lifespan` context manager below) constructs every
read-only telemetry client, the evidence collector, and the LLM
provider (or None, if unconfigured) exactly once — route handlers
never construct their own. Matches control-plane's own
non-blocking-startup philosophy: an absent LLM API key does not
prevent this process from starting or from serving health checks and
evidence-only responses; it only makes a real AI investigation fail
explicitly (see api/investigations.py).

This service is given NO PostgreSQL credentials and NEITHER of
control-plane's write-capable Bearer tokens (CONTROL_PLANE_WEBHOOK_TOKEN /
CONTROL_PLANE_LIFECYCLE_TOKEN) — see docker-compose.yml's
investigator-service block. There is no environment variable this
service reads that could authorize a write anywhere.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from investigator_service.api.health import router as health_router
from investigator_service.api.investigations import router as investigations_router
from investigator_service.clients.control_plane import ControlPlaneClient
from investigator_service.clients.loki import LokiClient
from investigator_service.clients.prometheus import PrometheusClient
from investigator_service.clients.tempo import TempoClient
from investigator_service.config import EvidenceBounds, LLMSettings, TelemetrySettings
from investigator_service.evidence_collector import EvidenceCollector
from investigator_service.investigator import Investigator
from investigator_service.llm.provider import LLMProvider, OpenAIProvider, StubProvider

logger = logging.getLogger("investigator_service")


def _build_provider(settings: LLMSettings) -> LLMProvider | None:
    if settings.provider == "stub":
        # Only reachable via INVESTIGATOR_LLM_PROVIDER=stub — never the
        # default. Exists solely so scripts/verify-investigator.sh can
        # exercise this service's real HTTP/evidence pipeline
        # end-to-end without a real, paid API key; see LLMSettings'
        # own docstring.
        logger.warning(
            "INVESTIGATOR_LLM_PROVIDER=stub — using the deterministic stub provider, NOT a real "
            "LLM. This should only ever be set by scripts/verify-investigator.sh, never in a real "
            "deployment."
        )
        return StubProvider()

    if not settings.configured:
        logger.warning(
            "INVESTIGATOR_LLM_API_KEY is not set — real AI investigation is disabled; "
            "evidence-only collection still works, and POST /api/v1/investigations will "
            "return 503 for an actual investigation request"
        )
        return None
    return OpenAIProvider(
        api_key=settings.api_key,  # type: ignore[arg-type]
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    telemetry = TelemetrySettings.from_env()
    llm_settings = LLMSettings.from_env()
    bounds = EvidenceBounds.from_env()

    control_plane = ControlPlaneClient(
        telemetry.control_plane_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds
    )
    prometheus = PrometheusClient(
        telemetry.prometheus_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds
    )
    loki = LokiClient(telemetry.loki_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds)
    tempo = TempoClient(telemetry.tempo_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds)

    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, bounds)
    provider = _build_provider(llm_settings)

    app.state.llm_settings = llm_settings
    app.state.investigator = Investigator(collector, provider, bounds)
    yield


app = FastAPI(
    title="Autonomous Reliability Platform — Incident Investigator",
    description=(
        "Phase 5: a strictly READ-ONLY AI incident investigator. Given an existing incident "
        "UUID, retrieves its real evidence from control-plane's existing GET APIs plus "
        "read-only Prometheus/Loki/Tempo queries, and returns a structured, evidence-grounded "
        "investigation via a configurable LLM provider. Never inserts, updates, or deletes an "
        "incident or audit event; never calls a write-capable control-plane endpoint; holds no "
        "database credentials. This is not an autonomous agent — one incident in, one "
        "investigation report out, no tool use, no iteration."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(investigations_router)
