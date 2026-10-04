"""Liveness and readiness.

/health/live never depends on anything external — this service has no
database and no required startup dependency, so it is trivially always
"up" once the process is running.

/health/ready reports the LLM provider's configuration state honestly
(Phase 5 §6/§10: "Health/readiness must communicate configuration
honestly") — it still returns 200 even when unconfigured, since this
service remains genuinely able to serve evidence-only requests and
report that state; it is POST /api/v1/investigations that fails
explicitly (503) for an actual investigation request when unconfigured,
never this endpoint silently claiming full capability.

Phase 5 correction round #6: `llm_provider.provider` ("openai" or
"stub") is reported explicitly, not just `configured` — this is what
lets scripts/verify-investigator.sh (and anyone else) distinguish a
real-but-unconfigured OpenAI mode from the deterministic stub mode it
temporarily forces, and verify that a provider-mode override was
genuinely restored afterward. Never includes an API key or any other
credential.
"""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "UP"}


@router.get("/health/ready")
async def readiness(request: Request) -> dict:
    llm_settings = request.app.state.llm_settings
    return {
        "status": "ready",
        "llm_provider": {
            "provider": llm_settings.provider,
            "configured": llm_settings.configured,
            "model": llm_settings.model if llm_settings.configured else None,
        },
    }
