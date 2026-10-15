"""Read-only client for control-plane's EXISTING GET APIs (Phase 6
§7): the indexer's ONLY source of historical incident data --
reliability.incidents / reliability.incident_events are never queried
directly.

Calls exactly three endpoints, all already unauthenticated/read-only:
  GET /api/v1/incidents                      (fully paginated)
  GET /api/v1/incidents/{id}
  GET /api/v1/incidents/{id}/events           (fully paginated)

Never calls PATCH /api/v1/incidents/{id}/status or
POST /internal/v1/alertmanager/webhook -- this client has no method
for either, and this service is never given either of control-plane's
write-capable Bearer tokens (CONTROL_PLANE_WEBHOOK_TOKEN /
CONTROL_PLANE_LIFECYCLE_TOKEN) in the first place.
"""

import logging

import httpx

from retrieval_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot

logger = logging.getLogger("retrieval_service.control_plane")


class IncidentNotFoundError(Exception):
    pass


class ControlPlaneUnavailableError(Exception):
    pass


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
        self._transport = transport

    async def list_all_incidents(self, *, page_size: int = 100, max_incidents: int) -> list[IncidentSnapshot]:
        """Fully paginates GET /api/v1/incidents via its own
        limit/offset contract (page_size capped at the API's
        documented max of 100). Stops once either every real incident
        has been fetched or `max_incidents` (a bounded safety cap, not
        an invented truncation of real data) is reached.
        """
        page_size = min(page_size, 100)
        items: list[IncidentSnapshot] = []
        offset = 0
        while True:
            url = f"{self._base_url}/api/v1/incidents"
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    resp = await client.get(url, params={"limit": page_size, "offset": offset})
            except httpx.HTTPError as exc:
                raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

            if resp.status_code != 200:
                raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

            body = resp.json()
            total = body.get("total", 0)
            page_items = [IncidentSnapshot.model_validate(raw) for raw in body.get("items", [])]
            items.extend(page_items)
            offset += page_size
            if not page_items or offset >= total or len(items) >= max_incidents:
                break

        return items[:max_incidents]

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

        return IncidentSnapshot.model_validate(resp.json())

    async def get_all_events(
        self, incident_id: str, *, page_size: int = 100, max_events: int
    ) -> tuple[list[IncidentEventSnapshot], int]:
        """Fully paginates the audit timeline. An incident with no
        audit events (Phase 6 §7: "remains a valid historical record
        with an empty history") simply returns `([], 0)` -- never
        invented history.
        """
        page_size = min(page_size, 100)
        items: list[IncidentEventSnapshot] = []
        offset = 0
        total = 0
        while True:
            url = f"{self._base_url}/api/v1/incidents/{incident_id}/events"
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    resp = await client.get(url, params={"limit": page_size, "offset": offset})
            except httpx.HTTPError as exc:
                raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

            if resp.status_code == 404:
                raise IncidentNotFoundError(incident_id)
            if resp.status_code != 200:
                raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

            body = resp.json()
            total = body.get("total", 0)
            page_items = [IncidentEventSnapshot.model_validate(raw) for raw in body.get("items", [])]
            items.extend(page_items)
            offset += page_size
            if not page_items or offset >= total or len(items) >= max_events:
                break

        return items[:max_events], total
