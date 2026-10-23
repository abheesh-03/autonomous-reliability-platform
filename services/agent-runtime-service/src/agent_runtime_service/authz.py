"""Phase 14 Gate 8: verification of the signed service assertion
web-console's BFF mints for THIS service specifically (a distinct
audience from the one it mints for control-plane -- see config.py's
ServiceAssertionSettings docstring), plus the tenant-ownership check
every agent-run route applies.

"Agent run IDs and checkpoint thread IDs are not authorization
credentials" (Gate 8) -- knowing/guessing a valid run_id must never be
sufficient to read or resume it. The actual check is always: fetch the
run's OWN incident_id from its real checkpoint state (never trust a
client-supplied incident_id for this purpose), ask control-plane for
that incident's real organization_id (control-plane is the single
source of truth for incident ownership, never duplicated here), and
compare it to the verified actor's own organization_id.

Phase 14 correction round, BLOCKER 1: this module ALSO now signs
DERIVED service assertions this service relays onward (to
control-plane directly, and to investigator-service for
run_investigation) -- carrying the IDENTICAL, already-verified actor
this service's own API boundary (get_actor_context, below) resolved
for the current request. `iss="agent-runtime-service"` on a derived
assertion is itself trusted by control-plane/investigator-service
(their own `trusted_issuers` allowlists), but this service never
re-derives or trusts a client-supplied org/role when minting one --
only the actor its OWN verification already produced for THIS request
is ever relayed. `bind_actor`/`current_actor` make that verified actor
available via a contextvar for the lifetime of the request, including
to code running deep inside a LangGraph node (LangGraph's own
async/await execution stays on the same asyncio task, so a contextvar
set at the API boundary is visible there without threading it through
every node's own function signature).
"""

import contextlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from fastapi import Header, HTTPException, Request

from agent_runtime_service.config import OrganizationContextSettings, ServiceAssertionSettings

THIS_SERVICE_ISSUER = "agent-runtime-service"

# A derived assertion is minted fresh on every outgoing call and only
# ever needs to survive the single, immediate downstream HTTP request
# -- deliberately much shorter-lived than the 60s window web-console's
# own original assertions use.
DERIVED_ASSERTION_TTL_SECONDS = 15

# Phase 14 Gate 5: see control_plane.core.authz's identical constant
# and docstring for why this is a dedicated header, never `Authorization`.
SERVICE_ASSERTION_HEADER = "x-service-assertion"

logger = logging.getLogger("agent_runtime_service.authz")

Role = Literal["OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"]

# Gate 3: VIEWER may read; starting/resuming an investigation is an
# ENGINEER-or-above capability (VIEWER may not trigger graph
# execution, even for an incident in their own organization).
ROLES_THAT_MAY_RUN_INVESTIGATIONS: frozenset[str] = frozenset({"OWNER", "ADMIN", "ENGINEER"})


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
            issuer=settings.issuer,
            audience=settings.audience,
            leeway=settings.max_clock_skew_seconds,
            options={"require": ["exp", "iat", "sub", "org", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidServiceAssertionError(str(exc)) from exc

    role = payload.get("role")
    if role not in ("OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"):
        raise InvalidServiceAssertionError(f"unrecognized role in service assertion: {role!r}")
    return ActorContext(user_id=str(payload["sub"]), organization_id=str(payload["org"]), role=role)


async def get_actor_context(
    request: Request,
    x_service_assertion: Annotated[str | None, Header()] = None,
) -> ActorContext | None:
    org_context_settings: OrganizationContextSettings = request.app.state.organization_context_settings
    if not org_context_settings.enabled:
        return None

    if not x_service_assertion:
        raise HTTPException(status_code=401, detail="unauthorized")

    token = x_service_assertion
    assertion_settings: ServiceAssertionSettings = request.app.state.service_assertion_settings
    try:
        return verify_service_assertion(token, assertion_settings)
    except InvalidServiceAssertionError as exc:
        logger.warning("rejected an invalid service assertion: %s", exc)
        raise HTTPException(status_code=401, detail="unauthorized") from exc


def require_same_organization(actor: ActorContext | None, resource_organization_id: str) -> None:
    """Same 404-not-403 discipline as control-plane's own
    require_same_organization -- see that module's docstring."""
    if actor is None:
        return
    if actor.organization_id != str(resource_organization_id):
        raise HTTPException(status_code=404, detail="agent run not found")


# ---------------------------------------------------------------------
# BLOCKER 1: derived-assertion signing + request-scoped actor binding
# ---------------------------------------------------------------------

_current_actor: ContextVar["ActorContext | None"] = ContextVar("current_actor", default=None)


class bind_actor(contextlib.AbstractContextManager):
    """Makes `actor` (the one this service's own API boundary already
    verified for the current request, or None in legacy/local-dev
    mode) available to `current_actor()` for the duration of the
    `with` block -- including to ControlPlaneClient/InvestigatorClient
    calls made from deep inside graph/nodes.py's own node functions,
    since those run as awaits within the SAME request's asyncio task."""

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
    """Mints a NEW, short-lived assertion for `audience`, carrying
    `actor`'s IDENTICAL verified sub/org/role, signed with the same
    shared secret but `iss="agent-runtime-service"` -- never
    `iss="web-console"` (this service is not web-console and must
    never impersonate it). The receiving service's own
    `trusted_issuers` allowlist is what decides whether this relay is
    accepted; the signature alone is never sufficient on its own."""
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
