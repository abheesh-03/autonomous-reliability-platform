"""Read-only Loki client.

Exposes exactly ONE allowlisted, code-defined LogQL template — never
an arbitrary caller- or LLM-supplied query. Matches the real `service`
label Alloy actually attaches (see observability/alloy/config.alloy
and scripts/verify-loki-logs.py's own `{service="..."}` convention) for
all four application services, scoped to the incident's own real time
window via GET /loki/api/v1/query_range.

Known limitation, stated honestly (see
docs/architecture/phase-5-ai-investigator.md): application logs carry
no trace or span ID today (Phase 2B.2's own documented limitation,
still true as of Phase 4). This client never claims a log line
correlates to a specific trace — it only reports what Loki's real
labels and message text actually contain.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger("investigator_service.loki")

APP_SERVICES: tuple[str, ...] = ("checkout-service", "payment-service", "inventory-service", "notification-service")

# {service=~"a|b|c|d"} — alternation over the exact, real label values
# Alloy attaches; never built from incident content.
LOG_QUERY = "{service=~\"" + "|".join(APP_SERVICES) + "\"}"


@dataclass(frozen=True)
class LogLine:
    service: str
    timestamp: datetime
    message: str


class LokiUnavailableError(Exception):
    pass


class LokiClient:
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

    async def query_window(
        self, window_start: datetime, window_end: datetime, *, max_lines: int, max_line_length: int
    ) -> list[LogLine]:
        url = f"{self._base_url}/loki/api/v1/query_range"
        params = {
            "query": LOG_QUERY,
            "start": str(int(window_start.timestamp() * 1_000_000_000)),
            "end": str(int(window_end.timestamp() * 1_000_000_000)),
            "limit": str(max_lines),
            "direction": "backward",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise LokiUnavailableError(f"could not reach Loki at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise LokiUnavailableError(f"Loki returned HTTP {resp.status_code} for {url}")

        # Phase 5 correction round #3: a 200 response is not
        # necessarily well-formed. Any shape surprise here (not valid
        # JSON, an unexpected "data"/"result" shape, a non-numeric
        # timestamp, a non-string message) is a collection FAILURE for
        # this best-effort source, never an uncaught exception.
        try:
            body = resp.json()
            if body.get("status") != "success":
                raise LokiUnavailableError("Loki query did not report status=success")

            lines: list[LogLine] = []
            for stream in body.get("data", {}).get("result", []):
                service = stream.get("stream", {}).get("service", "unknown")
                for ts_ns, message in stream.get("values", []):
                    if not isinstance(message, str):
                        continue
                    try:
                        timestamp = datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=window_start.tzinfo)
                    except (TypeError, ValueError, OSError, OverflowError):
                        continue
                    truncated = message if len(message) <= max_line_length else message[: max_line_length - 3] + "..."
                    lines.append(LogLine(service=service, timestamp=timestamp, message=truncated))
        except LokiUnavailableError:
            raise
        except Exception as exc:
            raise LokiUnavailableError(f"malformed response from Loki: {exc}") from exc

        lines.sort(key=lambda line: line.timestamp)
        return lines[:max_lines]
