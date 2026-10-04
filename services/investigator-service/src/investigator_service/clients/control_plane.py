"""Read-only client for control-plane's EXISTING GET APIs.

Calls exactly two endpoints, both already unauthenticated/read-only:
  GET /api/v1/incidents/{id}
  GET /api/v1/incidents/{id}/events

Never calls PATCH /api/v1/incidents/{id}/status or
POST /internal/v1/alertmanager/webhook — this client has no code path
that could (there is no method for either), and this service is never
given either of control-plane's write-capable Bearer tokens in the
first place (see docker-compose.yml's investigator-service block).
"""

import logging

import httpx

from investigator_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot

logger = logging.getLogger("investigator_service.control_plane")


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
        # Real network by default (transport=None); tests inject an
        # httpx.MockTransport here to simulate control-plane's real
        # HTTP responses without any network call.
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

        return IncidentSnapshot.model_validate(resp.json())

    async def get_all_events(self, incident_id: str, *, page_size: int = 100, max_events: int = 200) -> tuple[list[IncidentEventSnapshot], int]:
        """Fully paginates the audit timeline via the endpoint's own
        limit/offset contract (page_size capped at the API's documented
        max of 100) — never silently truncated to one page. Stops once
        either every real event has been fetched or `max_events` (a
        bounded safety cap, not an invented truncation of real data —
        see §5's "bound evidence item count") is reached; the real
        total is always returned alongside whatever was collected so a
        caller can tell the two apart.
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
