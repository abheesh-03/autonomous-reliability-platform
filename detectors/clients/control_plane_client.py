"""A bounded, read-only control-plane client for the detectors/
package. Uses ONLY the two existing, already-unauthenticated GET
routes (`services/control_plane/api/incidents.py`):
`GET /api/v1/incidents` and `GET /api/v1/incidents/{id}/events` --
never the authenticated `PATCH .../status` write endpoint, and this
package never calls it."""

from dataclasses import dataclass, field

import httpx

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_PAGES = 20  # hard bound on pagination -- never an unbounded fetch loop
PAGE_SIZE = 100  # the API's own documented maximum (Query(..., le=100))


class ControlPlaneUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class IncidentEventRecord:
    id: int
    incident_id: str
    event_type: str
    actor_type: str
    previous_status: str | None
    new_status: str
    occurred_at: str


@dataclass(frozen=True)
class IncidentRecord:
    id: str
    status: str
    severity: str
    source: str


@dataclass
class IncidentEventPage:
    events: list[IncidentEventRecord]
    total: int
    complete: bool  # True only if every page up to `total` was actually fetched


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=request_timeout)
        self._transport = transport

    async def list_incidents(self, *, status: str | None = None, max_incidents: int = 200) -> list[IncidentRecord]:
        """Bounded to `max_incidents` total, fetched `PAGE_SIZE` at a
        time, never more than `MAX_PAGES` requests."""
        incidents: list[IncidentRecord] = []
        offset = 0
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for _ in range(MAX_PAGES):
                params: dict[str, str | int] = {"limit": min(PAGE_SIZE, max_incidents - len(incidents)), "offset": offset}
                if status is not None:
                    params["status"] = status
                url = f"{self._base_url}/api/v1/incidents"
                try:
                    resp = await client.get(url, params=params)
                except httpx.HTTPError as exc:
                    raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc
                if resp.status_code != 200:
                    raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")
                try:
                    body = resp.json()
                    items = body["items"]
                    total = int(body["total"])
                except Exception as exc:
                    raise ControlPlaneUnavailableError(f"malformed response from control-plane at {url}: {exc}") from exc

                for item in items:
                    try:
                        incidents.append(
                            IncidentRecord(
                                id=str(item["id"]), status=item["status"], severity=item["severity"], source=item["source"]
                            )
                        )
                    except (KeyError, TypeError):
                        continue  # one malformed item never aborts the whole page

                offset += len(items)
                if not items or len(incidents) >= max_incidents or offset >= total:
                    break
        return incidents[:max_incidents]

    async def list_all_incident_events(self, incident_id: str, *, max_events: int = 500) -> IncidentEventPage:
        """Fetches the FULL event history for one incident, bounded to
        `max_events` and `MAX_PAGES` requests. `complete` is True only
        when pagination genuinely reached the reported `total` within
        those bounds -- a caller must treat `complete=False` as
        partial/possibly-incomplete history, never silently assume
        completeness."""
        events: list[IncidentEventRecord] = []
        offset = 0
        total = None
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for _ in range(MAX_PAGES):
                url = f"{self._base_url}/api/v1/incidents/{incident_id}/events"
                params = {"limit": PAGE_SIZE, "offset": offset}
                try:
                    resp = await client.get(url, params=params)
                except httpx.HTTPError as exc:
                    raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc
                if resp.status_code != 200:
                    raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")
                try:
                    body = resp.json()
                    items = body["items"]
                    total = int(body["total"])
                except Exception as exc:
                    raise ControlPlaneUnavailableError(f"malformed response from control-plane at {url}: {exc}") from exc

                for item in items:
                    try:
                        events.append(
                            IncidentEventRecord(
                                id=int(item["id"]),
                                incident_id=str(item["incident_id"]),
                                event_type=item["event_type"],
                                actor_type=item["actor_type"],
                                previous_status=item.get("previous_status"),
                                new_status=item["new_status"],
                                occurred_at=item["occurred_at"],
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue

                offset += len(items)
                if not items or offset >= total or len(events) >= max_events:
                    break

        complete = total is not None and len(events) >= total and len(events) <= max_events
        return IncidentEventPage(events=events[:max_events], total=total or 0, complete=complete)
