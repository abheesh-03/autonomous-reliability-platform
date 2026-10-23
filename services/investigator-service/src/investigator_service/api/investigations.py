"""POST /api/v1/investigations — the one endpoint this service
exposes beyond health checks. Purely computational: it is an explicit
request to COMPUTE an investigation from real, existing evidence. It
never persists anything (no database, no write path anywhere in this
service) and never mutates the incident it investigates — see
investigator_service/clients/control_plane.py's own docstring for why
that is structurally impossible, not just avoided by convention.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from investigator_service.authz import ActorContext, bind_actor, get_relayed_actor, require_internal_caller
from investigator_service.clients.control_plane import ControlPlaneUnavailableError, IncidentNotFoundError
from investigator_service.domain.investigation import InvestigationReport, InvestigationRequest
from investigator_service.investigator import Investigator, ProviderNotConfiguredError
from investigator_service.llm.prompt import PromptTooLargeError
from investigator_service.llm.provider import ProviderError
from investigator_service.llm.validation import ProviderOutputError

logger = logging.getLogger("investigator_service.api.investigations")

router = APIRouter(prefix="/api/v1")


@router.post(
    "/investigations",
    response_model=InvestigationReport,
    dependencies=[Depends(require_internal_caller)],
)
async def create_investigation(
    body: InvestigationRequest,
    request: Request,
    actor: Annotated[ActorContext | None, Depends(get_relayed_actor)],
) -> InvestigationReport:
    # body.incident_id: uuid.UUID already makes FastAPI/Pydantic
    # return 422 for a malformed UUID or a malformed request body
    # before this function body ever runs.
    investigator: Investigator = request.app.state.investigator

    # Phase 14 correction round, Blocker 1: binds the relayed actor (if
    # any) for the duration of investigate() so this service's own
    # control-plane client (clients/control_plane.py) relays a
    # further-derived assertion naming it, instead of the
    # now-insufficient bare internal token, when it reads this
    # incident's evidence from control-plane.
    try:
        with bind_actor(actor):
            return await investigator.investigate(str(body.incident_id))
    except IncidentNotFoundError:
        raise HTTPException(status_code=404, detail="incident not found")
    except ControlPlaneUnavailableError:
        logger.warning("control-plane unavailable while investigating %s", body.incident_id, exc_info=True)
        raise HTTPException(status_code=503, detail="control-plane is temporarily unavailable")
    except ProviderNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail=(
                "no LLM provider is configured — set INVESTIGATOR_LLM_API_KEY to enable real AI "
                "investigation (see docs/architecture/phase-5-ai-investigator.md)"
            ),
        )
    except PromptTooLargeError:
        logger.error(
            "configured max_prompt_chars is too small for incident %s's mandatory evidence content",
            body.incident_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "this investigation's mandatory evidence content does not fit within the configured "
                "prompt size bound — this is a configuration issue (INVESTIGATOR_MAX_PROMPT_CHARS / "
                "INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH), not a transient failure"
            ),
        )
    except ProviderError:
        logger.warning("LLM provider request failed for incident %s", body.incident_id, exc_info=True)
        raise HTTPException(status_code=502, detail="LLM provider request failed")
    except ProviderOutputError:
        logger.warning("LLM provider returned invalid output for incident %s", body.incident_id, exc_info=True)
        raise HTTPException(status_code=502, detail="LLM provider returned output that could not be validated")
