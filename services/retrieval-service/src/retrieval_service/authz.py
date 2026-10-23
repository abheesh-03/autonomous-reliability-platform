"""Phase 14 correction round, Issue 2/3: see
investigator_service/authz.py for the identical rationale -- this
service has no human-actor concept at all; it closes the "direct HTTP
call bypasses investigator-service" gap with a single, bounded,
static caller credential, gated behind the shared
CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT toggle.

Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A
(additive): `require_internal_caller` above is UNCHANGED and remains
the one thing that proves "this is really investigator-service" --
but it is no longer, by itself, sufficient to authorize a read of
tenant-private historical-incident data. `get_relayed_actor` verifies
an OPTIONAL `X-Service-Assertion` investigator-service relays for the
real, already-verified actor it is acting on behalf of; search.py uses
the verified actor's organization_id, compared against the incident's
REAL owning organization, as the actual authorization decision --
never the static token alone, never a client-supplied
organization_id, and never bare incident-id possession alone."""

import hmac
import logging
from dataclasses import dataclass
from typing import Annotated, Literal

import jwt
from fastapi import Header, HTTPException, Request

from retrieval_service.config import ServiceAssertionSettings

logger = logging.getLogger("retrieval_service.authz")

Role = Literal["OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"]


async def require_internal_caller(
    request: Request,
    x_internal_service_token: Annotated[str | None, Header()] = None,
) -> None:
    org_context_settings = request.app.state.organization_context_settings
    if not org_context_settings.enabled:
        return

    expected = request.app.state.internal_caller_token_settings.investigator_caller_token
    if not expected:
        logger.warning("request rejected: RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR is not configured")
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
    """Opportunistic at the transport layer -- `require_internal_caller`
    remains the actual route-level auth gate, unaffected either way.
    Returns None when no assertion was relayed at all (nothing to
    authorize a tenant-scoped read with; search.py's own
    `_resolve_historical_organization_scope` then correctly runs NO
    historical search in secure mode, same fail-closed-to-empty
    discipline it already uses for a missing/unresolvable
    `exclude_incident_id`). Raises 401 when one WAS presented but fails
    verification -- a present-but-invalid assertion is never silently
    dropped."""
    if not x_service_assertion:
        return None
    settings: ServiceAssertionSettings = request.app.state.service_assertion_settings
    try:
        return verify_service_assertion(x_service_assertion, settings)
    except InvalidServiceAssertionError as exc:
        logger.warning("rejected an invalid relayed service assertion: %s", exc)
        raise HTTPException(status_code=401, detail="unauthorized") from exc
