"""Phase 14 correction round, Issue 2/3: closes the "a direct,
unauthenticated HTTP call to this service's own exposed port
(127.0.0.1:8001) can bypass the frontend/agent-runtime-service
entirely and produce an investigation report for any incident" gap.

This service has no browser-facing API and no human-actor concept of
its own -- it is reachable only via agent-runtime-service's own
internal orchestration. So, unlike control-plane's `core/authz.py`,
there is no PRIMARY human assertion verification here -- only a
single, bounded, static "is this really agent-runtime-service" check
(`require_internal_caller`, below, UNCHANGED since the first
correction round), gated behind the SAME shared
`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` toggle every other
service in this platform uses, so secure mode is one switch, never
independently enabled/disabled per service.

Phase 14 correction round, BLOCKER 1 (additive): agent-runtime-service
ALSO relays a signed `X-Service-Assertion` alongside that same static
token, carrying the real human actor ITS OWN API boundary already
verified for the current request. This module verifies that relayed
assertion (`get_relayed_actor`) and makes it available via a
contextvar (`bind_actor`/`current_actor`) so this service's own
`clients/control_plane.py` can mint a FURTHER-derived assertion
(`sign_derivative_assertion`, `iss="investigator-service"`) instead of
relying on its own bare internal token -- control-plane's
incident/evidence routes no longer accept that bare token at all.

This is deliberately NOT a replacement for `require_internal_caller`:
a request missing the static token is still rejected exactly as
before, regardless of whether it carries a valid assertion. An
assertion that is simply ABSENT is not itself an error here (this
service's own inbound gate remains the static token, by design) --
but one that IS present and fails verification is always rejected,
never silently ignored.
"""

import contextlib
import hmac
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from fastapi import Header, HTTPException, Request

from investigator_service.config import ServiceAssertionSettings

logger = logging.getLogger("investigator_service.authz")

INTERNAL_SERVICE_TOKEN_HEADER = "x-internal-service-token"
SERVICE_ASSERTION_HEADER = "x-service-assertion"
THIS_SERVICE_ISSUER = "investigator-service"
DERIVED_ASSERTION_TTL_SECONDS = 15

Role = Literal["OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"]


async def require_internal_caller(
    request: Request,
    x_internal_service_token: Annotated[str | None, Header()] = None,
) -> None:
    org_context_settings = request.app.state.organization_context_settings
    if not org_context_settings.enabled:
        return

    expected = request.app.state.internal_service_tokens.agent_runtime_caller_token
    if not expected:
        logger.warning("request rejected: INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME is not configured")
        raise HTTPException(status_code=401, detail="unauthorized")

    if not x_internal_service_token or not hmac.compare_digest(x_internal_service_token, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@dataclass(frozen=True)
class ActorContext:
    user_id: str
    organization_id: str
    role: Role


class InvalidServiceAssertionError(Exception):
    pass


def verify_service_assertion(token: str, settings: ServiceAssertionSettings) -> ActorContext:
    if settings.secret is None:
        raise InvalidServiceAssertionError("SERVICE_ASSERTION_SIGNING_SECRET is not configured")
    try:
        payload = jwt.decode(
            token,
            settings.secret,
            algorithms=["HS256"],
            audience=settings.audience,
            leeway=settings.max_clock_skew_seconds,
            options={"require": ["exp", "iat", "sub", "org", "role", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidServiceAssertionError(str(exc)) from exc

    issuer = payload.get("iss")
    if issuer not in settings.trusted_issuers:
        raise InvalidServiceAssertionError(f"untrusted issuer: {issuer!r}")

    role = payload.get("role")
    if role not in ("OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"):
        raise InvalidServiceAssertionError(f"unrecognized role in service assertion: {role!r}")
    return ActorContext(user_id=str(payload["sub"]), organization_id=str(payload["org"]), role=role)


async def get_relayed_actor(
    request: Request,
    x_service_assertion: Annotated[str | None, Header()] = None,
) -> ActorContext | None:
    """Opportunistic, never REQUIRED by itself -- `require_internal_caller`
    (the route's actual auth gate) is unaffected either way. Returns
    None when no assertion was relayed at all (nothing to bind; this
    service's own control-plane client falls back to its bare internal
    token, the pre-Blocker-1 behavior, for legacy/local-dev callers).
    Raises 401 when one WAS presented but fails verification -- a
    present-but-invalid assertion is never silently dropped."""
    if not x_service_assertion:
        return None
    settings: ServiceAssertionSettings = request.app.state.service_assertion_settings
    try:
        return verify_service_assertion(x_service_assertion, settings)
    except InvalidServiceAssertionError as exc:
        logger.warning("rejected an invalid relayed service assertion: %s", exc)
        raise HTTPException(status_code=401, detail="unauthorized") from exc


# ---------------------------------------------------------------------
# BLOCKER 1: derived-assertion signing + request-scoped actor binding
# (mirrors agent_runtime_service.authz's own identical mechanism)
# ---------------------------------------------------------------------

_current_actor: ContextVar["ActorContext | None"] = ContextVar("current_actor", default=None)


class bind_actor(contextlib.AbstractContextManager):
    def __init__(self, actor: "ActorContext | None") -> None:
        self._actor = actor
        self._token = None

    def __enter__(self) -> "bind_actor":
        self._token = _current_actor.set(self._actor)
        return self

    def __exit__(self, *exc_info: object) -> None:
        _current_actor.reset(self._token)


def current_actor() -> "ActorContext | None":
    return _current_actor.get()


def sign_derivative_assertion(actor: ActorContext, settings: ServiceAssertionSettings, *, audience: str) -> str:
    """Mints a FURTHER-derived assertion for `audience` (control-plane),
    carrying `actor`'s IDENTICAL verified sub/org/role, signed with
    `iss="investigator-service"` -- never re-deriving or trusting
    anything beyond the actor this service's OWN `get_relayed_actor`
    already verified for the current request."""
    if settings.secret is None:
        raise InvalidServiceAssertionError("SERVICE_ASSERTION_SIGNING_SECRET is not configured")
    now = datetime.now(UTC)
    payload = {
        "sub": actor.user_id,
        "org": actor.organization_id,
        "role": actor.role,
        "iss": THIS_SERVICE_ISSUER,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=DERIVED_ASSERTION_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.secret, algorithm="HS256")
