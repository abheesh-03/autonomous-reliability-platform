"""ASGI-level request-body size guard for the telemetry ingestion
endpoint (Phase 16 Gate 4) -- a direct sibling of api/webhook_limits.py,
same rationale verbatim: FastAPI buffers a route's entire body before
any `Depends()` (including authentication) ever runs, so only ASGI
middleware wrapping the raw `receive()` callable can genuinely reject
an oversized body before it is ever buffered into memory.

Scoped to only POST /api/v1/telemetry/otlp/v1/metrics.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

TELEMETRY_INGEST_PATH = "/api/v1/telemetry/otlp/v1/metrics"

# Gate 4: a real OTLP histogram export for one metric, bounded to
# domain/telemetry.py's own structural limits (<=4 resourceMetrics,
# <=4 scopeMetrics each, <=4 metrics each, <=200 data points each,
# <=16 attributes each) is realistically well under 256 KiB even at
# the structural maximum. 512 KiB leaves headroom for real-world JSON
# verbosity (OTLP JSON is not a compact wire format) while remaining
# far below an uncontrolled-ingestion-cost concern (Gate 11: "No
# uncontrolled ingestion costs").
MAX_TELEMETRY_BODY_BYTES = 512 * 1024  # 512 KiB

_TOO_LARGE_BODY = b'{"detail":"request body too large"}'


class TelemetryBodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != TELEMETRY_INGEST_PATH or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        trailing_message: Message | None = None

        while True:
            message = await receive()
            if message["type"] != "http.request":
                trailing_message = message
                break

            body = message.get("body", b"")
            total += len(body)
            if total > MAX_TELEMETRY_BODY_BYTES:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})
                return

            chunks.append(body)
            if not message.get("more_body", False):
                break

        replay: list[Message] = [{"type": "http.request", "body": b"".join(chunks), "more_body": False}]
        if trailing_message is not None:
            replay.append(trailing_message)

        async def replay_receive() -> Message:
            if replay:
                return replay.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)
