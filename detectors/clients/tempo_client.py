"""A bounded, read-only Tempo client for the detectors/ package --
independent of `services/investigator-service`'s own client (same
rationale as `prometheus_client.py`). Uses Tempo's real, already-proven
`GET /api/search` and `GET /api/v2/traces/{traceID}` endpoints (see
`scripts/verify-tempo-trace.py`), searching traces rooted at
checkout-service -- the one entry point every real checkout request
passes through, and the only root this repository's own trace
verification script already proved against this real Tempo.

Known, honestly-stated limitation (same as
`investigator_service.clients.tempo`'s own docstring): this is a time +
service search, never a guaranteed causal link to any specific
incident -- a trace found in an incident's window is a CANDIDATE, never
confirmed to be "the" trace for that incident.
"""

import logging

import httpx

from detectors.schemas.dependency import TraceParseResult
from detectors.traces.parser import parse_trace_detail

logger = logging.getLogger("detectors.clients.tempo")

SEARCH_ROOT_SERVICE = "checkout-service"
MAX_TRACES_PER_SEARCH = 50
DEFAULT_TIMEOUT_SECONDS = 10.0


class TempoClientError(Exception):
    pass


class TempoUnavailableError(Exception):
    pass


class TempoClient:
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

    async def search_window(self, window_start_epoch: int, window_end_epoch: int, *, max_traces: int = 20) -> list[str]:
        """Returns candidate trace ids rooted at `SEARCH_ROOT_SERVICE`
        within the window -- bounded to `min(max_traces,
        MAX_TRACES_PER_SEARCH)`, never an unbounded result."""
        if window_end_epoch <= window_start_epoch:
            raise TempoClientError("window_end_epoch must be after window_start_epoch")
        max_traces = min(max_traces, MAX_TRACES_PER_SEARCH)

        url = f"{self._base_url}/api/search"
        params = {
            "tags": f"service.name={SEARCH_ROOT_SERVICE}",
            "start": str(window_start_epoch),
            "end": str(window_end_epoch),
            "limit": str(max_traces),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise TempoUnavailableError(f"could not reach Tempo at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise TempoUnavailableError(f"Tempo returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
            raw_traces = body.get("traces") or []
            if not isinstance(raw_traces, list):
                raise ValueError("'traces' was not a list")
            trace_ids = []
            for raw in raw_traces[:max_traces]:
                trace_id = raw.get("traceID") if isinstance(raw, dict) else None
                if trace_id:
                    trace_ids.append(trace_id)
        except Exception as exc:
            raise TempoUnavailableError(f"malformed response from Tempo search at {url}: {exc}") from exc

        return trace_ids

    async def get_trace_detail(self, trace_id: str) -> TraceParseResult | None:
        """Best-effort enrichment of one already-found candidate trace
        id. Returns None (never raises) on ANY retrieval failure -- a
        failure here only means this one candidate's span detail is
        unavailable; it must never fail a whole batch, and never
        fabricate a relationship that wasn't actually retrieved."""
        url = f"{self._base_url}/api/v2/traces/{trace_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return None
            body = resp.json()
        except Exception:
            logger.warning("could not retrieve/parse trace detail for %s", trace_id, exc_info=True)
            return None

        return parse_trace_detail(trace_id, body)
