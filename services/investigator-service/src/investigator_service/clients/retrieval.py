"""Read-only client for retrieval-service's ONE search endpoint
(Phase 6 §11): `POST /api/v1/retrieval/search`. This is a plain HTTP
call, same trust boundary as clients/prometheus.py et al -- no
PostgreSQL credential, no write capability, and no method on this
client could ever call anything else (there is nothing else to call;
retrieval-service exposes no mutation endpoint at all).

Any failure (connection error, timeout, non-2xx, malformed response)
is raised as `RetrievalUnavailableError` -- the caller
(investigator.py) degrades gracefully (Phase 6 §16): the investigation
still proceeds using Phase 5 evidence alone, never a fabricated
fallback for retrieved context.
"""

import logging
import uuid

import httpx

from investigator_service.authz import current_actor, sign_derivative_assertion
from investigator_service.config import ServiceAssertionSettings

logger = logging.getLogger("investigator_service.retrieval")


class RetrievalUnavailableError(Exception):
    pass


class RetrievalClient:
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
        self._transport = transport
        # Phase 14 correction round, Issue 3: this service's own
        # distinct internal-read identity for retrieval-service
        # (RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR) -- UNCHANGED,
        # still sent on every call (it remains the thing that proves
        # "this is really investigator-service" to
        # require_internal_caller).
        self._internal_read_token = internal_read_token
        # Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A:
        # ADDITIVE to the token above. When a verified actor is bound
        # for the current request, also relays a fresh, short-lived
        # derived assertion naming that EXACT actor -- retrieval-
        # service's own tenant-scope decision now REQUIRES this (the
        # bare internal token alone is no longer sufficient to
        # authorize a historical-incident search scoped to a specific
        # tenant; see retrieval_service.search's own docstring).
        self._service_assertion_settings = service_assertion_settings

    async def search(
        self,
        query: str,
        *,
        exclude_incident_id: uuid.UUID | str | None = None,
        knowledge_limit: int,
        historical_incident_limit: int,
        organization_id: str | None = None,
    ) -> dict:
        """Returns the raw, already-JSON-decoded response body
        (`{"knowledge": [...], "historical_incidents": [...],
        "embedding_space": "..."}`) -- normalized into this service's
        own `RetrievalContext` domain model by the caller, never
        trusted as-is beyond basic shape (Pydantic validation happens
        one level up, in investigator.py).

        `organization_id` (Phase 14 correction round, Issue 2:
        "tenant-specific retrieval results"), when given, is forwarded
        so retrieval-service can exclude `historical_incident` chunks
        belonging to a DIFFERENT organization -- `knowledge` chunks
        (runbooks) remain global/public regardless, per this
        platform's explicitly modeled global-public policy (see
        docs/architecture/phase-14-security-multitenancy.md)."""
        url = f"{self._base_url}/api/v1/retrieval/search"
        body = {
            "query": query,
            "knowledge_limit": knowledge_limit,
            "historical_incident_limit": historical_incident_limit,
        }
        if exclude_incident_id is not None:
            body["exclude_incident_id"] = str(exclude_incident_id)
        if organization_id is not None:
            body["organization_id"] = str(organization_id)

        headers = {"X-Internal-Service-Token": self._internal_read_token} if self._internal_read_token else {}
        actor = current_actor()
        if actor is not None and self._service_assertion_settings is not None:
            headers["X-Service-Assertion"] = sign_derivative_assertion(
                actor, self._service_assertion_settings, audience=self._service_assertion_settings.retrieval_audience
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise RetrievalUnavailableError(f"could not reach retrieval-service at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise RetrievalUnavailableError(f"retrieval-service returned HTTP {resp.status_code} for {url}")

        try:
            return resp.json()
        except ValueError as exc:
            raise RetrievalUnavailableError(f"retrieval-service returned a non-JSON response from {url}") from exc
