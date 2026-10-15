"""Read-only/computational client for investigator-service's EXISTING
`POST /api/v1/investigations` (Phase 7 node 2, run_investigation).
This is the ONLY investigator-service endpoint this client (or this
whole service) ever calls -- it never re-implements Phase 5/6's own
evidence collection, RAG retrieval, prompt construction, or citation
validation. investigator-service remains the one canonical
investigation engine.

That endpoint is itself documented (Phase 5 §8/§10) as computational,
read-only, and non-mutating -- it never writes an incident or audit
event. Calling it does not weaken investigator-service's own
read-only guarantees in any way.
"""

import logging
import uuid

import httpx
from pydantic import ValidationError

from agent_runtime_service.domain.investigation import InvestigationReport

logger = logging.getLogger("agent_runtime_service.investigator")


class InvestigatorUnavailableError(Exception):
    pass


class InvestigatorOutputError(Exception):
    """The response was reachable (2xx) but did not match the
    expected InvestigationReport shape -- never trusted into durable
    graph state regardless."""


class InvestigatorClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float,
        request_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        self._transport = transport

    async def investigate(self, incident_id: uuid.UUID | str) -> InvestigationReport:
        url = f"{self._base_url}/api/v1/investigations"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(url, json={"incident_id": str(incident_id)})
        except httpx.HTTPError as exc:
            raise InvestigatorUnavailableError(f"could not reach investigator-service at {url}: {exc}") from exc

        if resp.status_code != 200:
            # Deliberately never forwards investigator-service's own
            # response body verbatim (it could, in principle, carry a
            # provider-shaped detail string) -- only the status code,
            # the same "type/class, not raw text" discipline every
            # other provider-facing boundary in this platform already
            # follows.
            raise InvestigatorUnavailableError(
                f"investigator-service returned HTTP {resp.status_code} for {url}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise InvestigatorOutputError(f"investigator-service returned a non-JSON response from {url}") from exc

        try:
            return InvestigationReport.model_validate(body)
        except ValidationError as exc:
            # Phase 7 correction round (finding #5): pydantic's
            # ValidationError.__str__ includes each failing field's
            # `input_value` -- i.e. the actual upstream response
            # content, verbatim. That string must never reach a raised
            # exception's message (it can be persisted into durable
            # `error_detail`, Phase 7's own no-raw-upstream-text
            # guarantee from the graph-state docstring) or the raw
            # response body. Log safe, structural metadata only; raise
            # a fixed, generic message.
            logger.warning(
                "investigator-service response failed shape validation (%d error(s))",
                exc.error_count(),
            )
            raise InvestigatorOutputError(
                "investigator-service response did not match the expected response contract"
            ) from exc
