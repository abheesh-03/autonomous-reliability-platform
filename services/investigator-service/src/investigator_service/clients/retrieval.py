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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        self._transport = transport

    async def search(
        self,
        query: str,
        *,
        exclude_incident_id: uuid.UUID | str | None = None,
        knowledge_limit: int,
        historical_incident_limit: int,
    ) -> dict:
        """Returns the raw, already-JSON-decoded response body
        (`{"knowledge": [...], "historical_incidents": [...],
        "embedding_space": "..."}`) -- normalized into this service's
        own `RetrievalContext` domain model by the caller, never
        trusted as-is beyond basic shape (Pydantic validation happens
        one level up, in investigator.py)."""
        url = f"{self._base_url}/api/v1/retrieval/search"
        body = {
            "query": query,
            "knowledge_limit": knowledge_limit,
            "historical_incident_limit": historical_incident_limit,
        }
        if exclude_incident_id is not None:
            body["exclude_incident_id"] = str(exclude_incident_id)

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise RetrievalUnavailableError(f"could not reach retrieval-service at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise RetrievalUnavailableError(f"retrieval-service returned HTTP {resp.status_code} for {url}")

        try:
            return resp.json()
        except ValueError as exc:
            raise RetrievalUnavailableError(f"retrieval-service returned a non-JSON response from {url}") from exc
