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

from investigator_service.authz import current_actor, sign_derivative_assertion
from investigator_service.config import ServiceAssertionSettings
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
        internal_read_token: str = "",
        service_assertion_settings: ServiceAssertionSettings | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        # Real network by default (transport=None); tests inject an
        # httpx.MockTransport here to simulate control-plane's real
        # HTTP responses without any network call.
        self._transport = transport
        # Phase 14 correction round, Issue 3: this service's own
        # distinct internal-read identity
        # (CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR) -- only
        # actually required by control-plane once
        # CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is enabled. Kept
        # as the fallback for legacy/local-dev callers that never
        # relay an actor at all (see _internal_headers, below).
        self._internal_read_token = internal_read_token
        # Phase 14 correction round, Blocker 1: when a relayed actor is
        # bound for the current request (authz.bind_actor, set by
        # api/investigations.py), every GET below relays a FRESH,
        # further-derived assertion naming that EXACT actor instead --
        # control-plane's own incident/evidence routes no longer accept
        # the bare internal token above at all.
        self._service_assertion_settings = service_assertion_settings

    def _internal_headers(self) -> dict[str, str]:
        actor = current_actor()
        if actor is not None and self._service_assertion_settings is not None:
            token = sign_derivative_assertion(
                actor, self._service_assertion_settings, audience=self._service_assertion_settings.control_plane_audience
            )
            return {"X-Service-Assertion": token}
        return {"X-Internal-Service-Token": self._internal_read_token} if self._internal_read_token else {}

    async def get_incident(self, incident_id: str) -> IncidentSnapshot:
        url = f"{self._base_url}/api/v1/incidents/{incident_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, headers=self._internal_headers())
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            raise IncidentNotFoundError(incident_id)
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        return IncidentSnapshot.model_validate(resp.json())

    async def get_kubernetes_evidence(self, incident_id: str) -> dict | None:
        """GET /api/v1/incidents/{id}/kubernetes-evidence (Phase 12B-D
        correction round, Issue 6A) -- the ONE trusted, persisted
        source of a Kubernetes-sourced incident's own resource identity
        (same endpoint agent-runtime-service's propose_remediation
        already reads, Issue 1). Returns the raw, already-bounded
        response dict (cluster/namespace/resource_kind/resource_name/
        resource_uid/detector_id/result/collection_completeness/
        collected_at) or None for a 404 (no recorded Kubernetes
        evidence for this incident -- a real, honest "nothing to show"
        outcome, never an error that would abort the whole
        investigation). Deliberately returns a plain dict rather than a
        new pydantic model: evidence_collector.py only ever reads a
        handful of string/datetime fields out of it into a bounded,
        redacted EvidenceItem -- it never needs a typed domain object
        of its own."""
        url = f"{self._base_url}/api/v1/incidents/{incident_id}/kubernetes-evidence"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, headers=self._internal_headers())
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        body = resp.json()
        return body if isinstance(body, dict) else None

    async def get_aws_evidence(self, incident_id: str) -> dict | None:
        """GET /api/v1/incidents/{id}/aws-evidence (Phase 13) -- the
        ONE trusted, persisted source of an AWS-sourced incident's own
        resource identity. Mirrors `get_kubernetes_evidence`'s own
        contract and error handling exactly: returns the raw,
        already-bounded response dict, or None for a 404 (no recorded
        AWS evidence for this incident -- a real, honest outcome,
        never an error that would abort the whole investigation)."""
        url = f"{self._base_url}/api/v1/incidents/{incident_id}/aws-evidence"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, headers=self._internal_headers())
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        body = resp.json()
        return body if isinstance(body, dict) else None

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
                    resp = await client.get(url, params={"limit": page_size, "offset": offset}, headers=self._internal_headers())
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
