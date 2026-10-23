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
from investigator_service.clients.retrieval import RetrievalClient
from investigator_service.clients.tempo import TempoClient
from investigator_service.config import (
    EvidenceBounds,
    InternalServiceTokenSettings,
    LLMSettings,
    OrganizationContextSettings,
    RagBounds,
    RetrievalSettings,
    ServiceAssertionSettings,
    TelemetrySettings,
)
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
    retrieval_settings = RetrievalSettings.from_env()
    rag_bounds = RagBounds.from_env()

    internal_service_tokens = InternalServiceTokenSettings.from_env()
    # Phase 14 correction round, Blocker 1: lets control_plane's own
    # client relay a further-derived assertion for whatever actor
    # api/investigations.py binds for the current request.
    service_assertion_settings = ServiceAssertionSettings.from_env()

    control_plane = ControlPlaneClient(
        telemetry.control_plane_url,
        telemetry.connect_timeout_seconds,
        telemetry.request_timeout_seconds,
        internal_read_token=internal_service_tokens.control_plane_token,
        service_assertion_settings=service_assertion_settings,
    )
    prometheus = PrometheusClient(
        telemetry.prometheus_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds
    )
    loki = LokiClient(telemetry.loki_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds)
    tempo = TempoClient(telemetry.tempo_url, telemetry.connect_timeout_seconds, telemetry.request_timeout_seconds)

    collector = EvidenceCollector(control_plane, prometheus, loki, tempo, bounds)
    provider = _build_provider(llm_settings)

    # Phase 6: retrieval is OPTIONAL -- a blank INVESTIGATOR_RETRIEVAL_URL
    # (the default) disables it entirely, same non-blocking-startup
    # philosophy as the LLM provider above. Investigation still works
    # using Phase 5 evidence alone either way (Phase 6 §16).
    retrieval_client = (
        RetrievalClient(
            retrieval_settings.url,
            retrieval_settings.connect_timeout_seconds,
            retrieval_settings.request_timeout_seconds,
            internal_read_token=internal_service_tokens.retrieval_token,
            service_assertion_settings=service_assertion_settings,
        )
        if retrieval_settings.url
        else None
    )

    app.state.llm_settings = llm_settings
    app.state.investigator = Investigator(collector, provider, bounds, retrieval_client, rag_bounds)
    # Phase 14 correction round, Issue 2/3: non-blocking at startup,
    # same philosophy as every setting above -- an unconfigured
    # agent_runtime_caller_token just makes require_internal_caller
    # fail every request closed once enforcement is on; it never
    # crashes this service.
    app.state.organization_context_settings = OrganizationContextSettings.from_env()
    app.state.internal_service_tokens = internal_service_tokens
    app.state.service_assertion_settings = service_assertion_settings
    # Phase 14 correction round, Blocker 1: exposed directly (mirrors
    # agent_runtime_service.main's own app.state.control_plane_client)
    # so a test overriding app.state.service_assertion_settings after
    # startup can also update THIS already-constructed client's own
    # captured settings -- `ServiceAssertionSettings` is an immutable
    # dataclass VALUE, so reassigning app.state alone does not retroactively
    # change what an already-built client holds; this accessor is what
    # lets a test (or any other future reconfiguration path) reach it.
    app.state.control_plane_client = control_plane
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
