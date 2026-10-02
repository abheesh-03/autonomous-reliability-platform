"""ASGI-level request-body size guard for the Alertmanager webhook
endpoint (Phase 3C).

This MUST be ASGI middleware, not a FastAPI `Depends()`: FastAPI reads
and fully buffers a route's entire request body via
`await request.body()` BEFORE any dependency (including an
authentication dependency) ever runs — confirmed directly from
FastAPI's own `get_request_handler` source (the installed
fastapi==0.142.2). A regular dependency therefore cannot genuinely
prevent an oversized body from being buffered into memory first; it
could only reject after the buffering already happened. ASGI
middleware wraps the raw `receive()` callable at the transport
boundary instead, so it sees bytes as they actually arrive from the
client and can reject before Starlette/FastAPI ever buffers them.

Pydantic's own structural bounds
(domain/alertmanager_webhook.py: at most 100 alerts, 50 labels/
annotations each, 2000 characters per value) already cap a theoretical
worst case, but that worst case is still tens of megabytes. This adds
a direct, aggregate raw byte limit on the whole request body — modest
and documented below.

Enforced genuinely, not merely via the Content-Length header: the
actual bytes received are counted as ASGI `http.request` messages
arrive, so a missing Content-Length (e.g. chunked transfer-encoding)
or a dishonest one cannot bypass this limit. If the running total
never exceeds the limit, the already-drained messages are replayed
to the wrapped application exactly once (consolidated into a single
message) so normal request processing is unaffected; if the limit IS
exceeded, a 413 response is sent directly, and the wrapped application
is never invoked at all for that request — it never sees any part of
the oversized body.

Deliberately scoped to only one path (POST
/internal/v1/alertmanager/webhook): every other route in this service
either has no request body (GET only) or is otherwise unaffected, so
scoping this narrowly keeps the guard's blast radius minimal.

Runs independent of (and before) the authentication dependency
(api/webhook_auth.py) — an oversized body from even an unauthenticated
sender is rejected immediately, which is MORE protective for a
resource-exhaustion concern, not less: nothing downstream, including
authentication, ever does any work against a body this large. Never
inspects or logs the Authorization header or any part of the body
content — only its aggregate length.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

WEBHOOK_PATH = "/internal/v1/alertmanager/webhook"

# Modest and documented: a real Alertmanager webhook batch (bounded,
# per this service's own Pydantic limits above, to at most 100 alerts
# / 50 labels and annotations each / 2000 characters per value) is
# realistically well under 100 KB. 1 MiB leaves generous headroom for
# legitimate large batches while remaining far below the
# tens-of-megabytes those structural bounds alone would otherwise
# allow through.
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024  # 1 MiB

_TOO_LARGE_BODY = b'{"detail":"request body too large"}'


class WebhookBodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != WEBHOOK_PATH or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        trailing_message: Message | None = None

        while True:
            message = await receive()
            if message["type"] != "http.request":
                # Only other possibility on an HTTP scope is
                # http.disconnect — stop draining and let it be
                # replayed to the wrapped app unchanged below.
                trailing_message = message
                break

            body = message.get("body", b"")
            total += len(body)
            if total > MAX_WEBHOOK_BODY_BYTES:
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
