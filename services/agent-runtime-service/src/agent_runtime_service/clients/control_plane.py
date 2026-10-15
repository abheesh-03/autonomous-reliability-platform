"""Read-only client for control-plane's EXISTING GET API (Phase 7
node 1, load_incident). Calls exactly ONE endpoint, already
unauthenticated/read-only:

  GET /api/v1/incidents/{id}

Never calls PATCH /api/v1/incidents/{id}/status or
POST /internal/v1/alertmanager/webhook -- this client has no method
for either, and this service is never given either of control-plane's
write-capable Bearer tokens (CONTROL_PLANE_WEBHOOK_TOKEN /
CONTROL_PLANE_LIFECYCLE_TOKEN) in the first place.
"""

import logging

import httpx
from pydantic import ValidationError

from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot

logger = logging.getLogger("agent_runtime_service.control_plane")


class IncidentNotFoundError(Exception):
    pass


class ControlPlaneUnavailableError(Exception):
    pass


class ControlPlaneOutputError(Exception):
    """The response was reachable (200) but did not match the
    expected IncidentSnapshot shape -- never trusted into durable graph
    state regardless (Phase 7 correction round, finding #5 -- same
    discipline as InvestigatorOutputError)."""


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float,
        request_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        # Real network by default (transport=None); tests inject an
        # httpx.MockTransport here, the same seam-based convention
        # investigator-service's own control-plane client tests use.
        self._transport = transport

    async def get_incident(self, incident_id: str) -> IncidentSnapshot:
        url = f"{self._base_url}/api/v1/incidents/{incident_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            raise IncidentNotFoundError(incident_id)
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ControlPlaneOutputError(f"control-plane returned a non-JSON response from {url}") from exc

        try:
            return IncidentSnapshot.model_validate(body)
        except ValidationError as exc:
            # Never concatenate str(exc) or the raw body -- pydantic's
            # ValidationError message includes each failing field's
            # actual input_value verbatim (Phase 7 correction round,
            # finding #5). Safe, structural metadata only.
            logger.warning("control-plane response failed shape validation (%d error(s))", exc.error_count())
            raise ControlPlaneOutputError(
                "control-plane response did not match the expected response contract"
            ) from exc
