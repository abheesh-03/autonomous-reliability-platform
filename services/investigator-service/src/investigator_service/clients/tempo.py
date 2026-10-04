"""Read-only Tempo client.

Exposes exactly TWO allowlisted, code-defined operations — never an
arbitrary caller- or LLM-supplied query, and NEVER a trace ID
fabricated from the incident's own fingerprint or any other field
(Alertmanager's fingerprint is a hash of alert labels, unrelated to
any real OTel trace ID — there is no legitimate way to derive one from
the other):

1. `search_window` — Tempo's own real tag-based search API
   (GET /api/search) for traces rooted at checkout-service — the one
   service every real checkout request passes through — within the
   incident's real time window, bounded to a small result count.
2. `get_trace_detail` — for a trace ID ALREADY found by (1), fetches
   its real spans via GET /api/v2/traces/{traceID} (the exact endpoint
   and response shape scripts/verify-tempo-trace.py already proved
   against this real Tempo) and summarizes real span/service
   relationships. Never a new, independent search; purely an
   enrichment of an already-bounded candidate.

Known limitation, stated honestly: this is a time + service search,
not a guaranteed causal link to this exact incident — Phase 2B.2 never
added trace/span IDs to application logs, so there is no reliable way
to confirm a specific trace belongs to this specific incident versus
simply having occurred in the same window. Reported as "candidate
traces in this window", never as "the trace for this incident" — and
`get_trace_detail` succeeding only adds real span/service detail to
that same candidate; it never upgrades it to a confirmed link.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger("investigator_service.tempo")

SEARCH_ROOT_SERVICE = "checkout-service"


@dataclass(frozen=True)
class TraceSummary:
    trace_id: str
    root_service_name: str
    root_trace_name: str
    start_time: datetime
    duration_ms: int


@dataclass(frozen=True)
class TraceDetail:
    trace_id: str
    span_count: int
    service_names: tuple[str, ...]
    root_span_services: tuple[str, ...]


class TempoUnavailableError(Exception):
    pass


class TempoClient:
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

    async def search_window(
        self, window_start: datetime, window_end: datetime, *, max_traces: int
    ) -> list[TraceSummary]:
        url = f"{self._base_url}/api/search"
        params = {
            "tags": f"service.name={SEARCH_ROOT_SERVICE}",
            "start": str(int(window_start.timestamp())),
            "end": str(int(window_end.timestamp())),
            "limit": str(max_traces),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise TempoUnavailableError(f"could not reach Tempo at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise TempoUnavailableError(f"Tempo returned HTTP {resp.status_code} for {url}")

        # Phase 5 correction round #3: a 200 response is not
        # necessarily well-formed. Any shape surprise here (not valid
        # JSON, "traces" not a list, a missing/non-numeric field on one
        # entry) is a collection FAILURE for this best-effort source,
        # never a crash and never silently-wrong data.
        try:
            body = resp.json()
            traces: list[TraceSummary] = []
            for raw in (body.get("traces") or [])[:max_traces]:
                trace_id = raw.get("traceID")
                if not trace_id:
                    continue
                start_ns = int(raw.get("startTimeUnixNano", 0) or 0)
                traces.append(
                    TraceSummary(
                        trace_id=trace_id,
                        root_service_name=raw.get("rootServiceName", "unknown"),
                        root_trace_name=raw.get("rootTraceName", ""),
                        start_time=datetime.fromtimestamp(start_ns / 1_000_000_000, tz=window_start.tzinfo)
                        if start_ns
                        else window_start,
                        duration_ms=int(raw.get("durationMs", 0) or 0),
                    )
                )
        except Exception as exc:
            raise TempoUnavailableError(f"malformed response from Tempo search at {url}: {exc}") from exc

        return traces

    async def get_trace_detail(self, trace_id: str) -> TraceDetail | None:
        """Best-effort enrichment of a candidate trace already found
        by `search_window`. Returns None (never raises) on ANY
        failure — a failure here only means detailed span/service
        relationships are unavailable for this one candidate; it must
        never fail the whole investigation, and never fabricate a
        relationship that wasn't actually retrieved."""
        url = f"{self._base_url}/api/v2/traces/{trace_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return None
            body = resp.json()
            spans = _extract_spans(body)
        except Exception:
            logger.warning("could not retrieve/parse trace detail for %s", trace_id, exc_info=True)
            return None

        if not spans:
            return None

        service_names = sorted({s["service_name"] for s in spans if s.get("service_name")})
        root_services = sorted(
            {s["service_name"] for s in spans if not s.get("parent_id") and s.get("service_name")}
        )
        return TraceDetail(
            trace_id=trace_id,
            span_count=len(spans),
            service_names=tuple(service_names),
            root_span_services=tuple(root_services),
        )


def _extract_spans(body: dict) -> list[dict]:
    """Flattens Tempo's real resourceSpans/scopeSpans/spans structure
    (the exact shape GET /api/v2/traces/{traceID} returns — see
    scripts/verify-tempo-trace.py's own `extract_spans`, which proved
    this exact structure against this real Tempo) into a flat list of
    {service_name, parent_id}. Only what this summary needs — not the
    full span IDs, since this is a coarse relationship summary, not a
    span-by-span proof. Any unexpected shape here raises, which the
    caller (get_trace_detail) turns into a clean `None`."""
    spans = []
    trace = body.get("trace", {})
    for rs in trace.get("resourceSpans", []):
        service_name = None
        for attr in rs.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service_name = attr.get("value", {}).get("stringValue")
        for ss in rs.get("scopeSpans", []):
            for s in ss.get("spans", []):
                spans.append({"service_name": service_name, "parent_id": s.get("parentSpanId")})
    return spans
