"""Phase 14: verification of the signed service assertion web-console's
BFF mints on behalf of a real, authenticated browser session, plus the
small, explicit permission matrix every tenant-aware route consults.

This module answers exactly one question for each request: "which
real human (user_id), in which real organization (org_id), with which
real role, is this?" -- never "which organization did the browser/URL
ask to act as" (Gate 5's core prohibition). The assertion itself is
verified with PyJWT against a pinned audience/algorithm, a trusted
issuer allowlist, and a bounded expiry/clock-skew -- an unsigned,
expired, wrong-issuer, wrong-audience, or wrong-algorithm token is
indistinguishable from no token at all, from this module's point of
view.

Deliberately NOT used unless
`OrganizationContextSettings.enabled` (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT)
is true -- see core/config.py's own docstring for why this is a single
global, fail-closed toggle rather than a per-route opt-in.

Phase 14 correction round, BLOCKER 1 (security-critical): the prior
version of this module let ANY of three static internal-service-read
tokens unconditionally bypass `require_same_organization` for every
incident/evidence/remediation-proposal GET -- meaning a single leaked
token granted cross-tenant read access to every organization's data.
That bypass is REMOVED. Internal services now authorize a tenant-
scoped read the SAME way a human request does: by presenting a
verified, signed assertion that carries the REAL actor's org/role --
either the original one web-console minted, or a DERIVED one an
internal service mints for the EXACT actor it itself already
independently verified (see `sign_derivative_assertion`). A static
internal-service token now only ever identifies a TRANSPORT-level
caller (never an authorization decision by itself), and is accepted
ONLY on the one remaining endpoint that cannot practically carry a
forwarded human actor (tool-gateway's own independent remediation-
proposal status re-check) -- and even there, ONLY for a proposal that
has already been decided (see `require_tool_gateway_proposal_access`).
"""

import hmac
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Header, HTTPException, Request

# Phase 14 Gate 5: a SEPARATE header from `Authorization` -- several
# routes this module protects (e.g. the remediation decision endpoint)
# ALSO require one of this service's existing static Bearer tokens
# (api/auth.py) in `Authorization` itself; reusing that same header for
# the service assertion would make the two mechanisms collide on a
# single request. Never read by anything else in this service.
SERVICE_ASSERTION_HEADER = "x-service-assertion"

# Phase 14 correction round, Issue 3 / Blocker 1: ANOTHER separate,
# dedicated header -- distinct from BOTH `Authorization` and
# `X-Service-Assertion` -- for the internal-service TRANSPORT
# identity (see core/config.py::InternalServiceReadTokenSettings).
# Carries NO authorization weight of its own anymore (Blocker 1) --
# see `require_tool_gateway_proposal_access` for its one remaining use.
INTERNAL_SERVICE_TOKEN_HEADER = "x-internal-service-token"

from control_plane.core.config import (
    InternalServiceReadTokenSettings,
    LegacyIngestionSettings,
    OrganizationContextSettings,
    ServiceAssertionSettings,
)

logger = logging.getLogger("control_plane.authz")

Role = Literal["OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"]

# Gate 3's explicit permission matrix, expressed as the one concrete
# thing this service enforces: which roles may approve/reject a
# remediation proposal. Every role may read (Gate 5 protects reads by
# organization membership alone, not by role) -- VIEWER included,
# per Gate 3's own semantics ("VIEWER reads authorized incidents").
# OWNER/ADMIN do NOT implicitly gain approval rights merely by being
# org administrators (Gate 3: "ADMIN... does NOT implicitly bypass
# remediation approval policy") -- only OWNER and INCIDENT_APPROVER may
# decide a proposal. ENGINEER may read and start/resume investigations
# (enforced by agent-runtime-service, not this module) but may not
# decide remediation.
ROLES_THAT_MAY_DECIDE_REMEDIATION: frozenset[str] = frozenset({"OWNER", "INCIDENT_APPROVER"})

# Phase 15 independent-review correction round, BLOCKER 2: registering a
# service is an organization-scoped MUTATION (a new catalog entry every
# member will subsequently see), not a read -- VIEWER (a real role, but
# read-only by design) must not be able to create one. INCIDENT_APPROVER
# is deliberately excluded too: that role's entire purpose is deciding
# remediation proposals (see ROLES_THAT_MAY_DECIDE_REMEDIATION above),
# not general organization/catalog administration -- granting it here
# would be an undocumented scope creep, not a considered product
# decision. OWNER, ADMIN, and ENGINEER may register a service: ENGINEER
# is included deliberately (an engineer who owns a service's on-call
# rotation is exactly who should be able to add it to the catalog),
# mirroring Gate 3's own description of ENGINEER as able to "read and
# start/resume investigations" -- registering the systems they operate
# is the same class of operational, non-administrative action.
ROLES_THAT_MAY_REGISTER_SERVICES: frozenset[str] = frozenset({"OWNER", "ADMIN", "ENGINEER"})

# Phase 14 correction round, Blocker 1: tool-gateway's own internal
# token may NEVER be used to read a proposal that has not yet been
# decided -- a "pending_approval" proposal's reason/target/action_type
# are exactly the sensitive, pre-decision details Blocker 1 is about.
# Reaching any of these statuses is only possible via decide_remediation_proposal's
# OWN, already-enforced human-actor + tenant + role check, so reading
# a proposal already in one of these statuses does not disclose
# anything that wasn't already authorized for release at decision time.
PROPOSAL_STATUSES_READABLE_BY_TOOL_GATEWAY_TOKEN: frozenset[str] = frozenset(
    {"approved", "rejected", "executing", "succeeded", "failed"}
)


@dataclass(frozen=True)
class ActorContext:
    """The real, verified identity of the human behind this request --
    never trusted from any header/query parameter the browser itself
    could set; always derived from a verified assertion signature.

    `issued_by` (Phase 14 correction round, Blocker 1) records WHICH
    trusted party signed this specific assertion -- "web-console" for
    one minted directly from a real browser session, or the name of
    whichever internal service RELAYED it (e.g.
    "agent-runtime-service") after independently verifying an
    assertion of its own for the identical actor. Every value here is
    cryptographically verified via the shared signing secret
    regardless of which trusted issuer it is -- `issued_by` is
    informational/audit metadata, never itself a widened grant of
    authority."""

    user_id: str
    organization_id: str
    role: Role
    issued_by: str


@dataclass(frozen=True)
class InternalServiceContext:
    """Phase 14 correction round: a trusted INTERNAL caller
    (currently only tool-gateway), verified via its own dedicated,
    bounded-scope credential -- never a human, never carrying an
    organization/role, and (Blocker 1) NEVER sufficient by itself to
    read a tenant-scoped resource. The only route that still accepts
    this type (`get_actor_or_tool_gateway_reader`) additionally
    requires `require_tool_gateway_proposal_access` to pass before any
    data is returned."""

    service_name: str


class InvalidServiceAssertionError(Exception):
    pass


def verify_service_assertion(token: str, settings: ServiceAssertionSettings) -> ActorContext:
    if settings.secret is None:
        raise InvalidServiceAssertionError("SERVICE_ASSERTION_SIGNING_SECRET is not configured")

    try:
        payload = jwt.decode(
            token,
            settings.secret,
            algorithms=["HS256"],  # pinned -- never read "alg" from the token's own header
            audience=settings.audience,
            leeway=settings.max_clock_skew_seconds,
            options={"require": ["exp", "iat", "sub", "org", "role", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidServiceAssertionError(str(exc)) from exc

    # Phase 14 correction round, Blocker 1: a trusted-issuer ALLOWLIST,
    # never a single fixed string -- checked manually (not via
    # jwt.decode's own `issuer=`, which only supports one value) so
    # BOTH web-console's own original assertions AND a relaying
    # internal service's derived ones (for the SAME, already-verified
    # actor) are accepted, and nothing else is.
    issuer = payload.get("iss")
    if issuer not in settings.trusted_issuers:
        raise InvalidServiceAssertionError(f"untrusted issuer: {issuer!r}")

    role = payload.get("role")
    if role not in ("OWNER", "ADMIN", "ENGINEER", "VIEWER", "INCIDENT_APPROVER"):
        raise InvalidServiceAssertionError(f"unrecognized role in service assertion: {role!r}")

    # Phase 14 correction round, Issue 1: the organization claim MUST
    # be a syntactically valid UUID -- `reliability.incidents.organization_id`
    # is a native Postgres UUID column (database/migrations/V10), and
    # web-console's own `generateId: "uuid"` Better Auth configuration
    # (services/web-console/lib/auth/auth.ts) guarantees every real
    # organization id already is one; rejecting anything else here is
    # defense in depth, not a workaround for a real, expected value
    # shape.
    raw_org = str(payload["org"])
    try:
        organization_id = str(uuid.UUID(raw_org))
    except ValueError as exc:
        raise InvalidServiceAssertionError(f"organization claim is not a valid UUID: {raw_org!r}") from exc

    return ActorContext(
        user_id=str(payload["sub"]), organization_id=organization_id, role=role, issued_by=str(issuer)
    )


def verify_internal_service_token(
    token: str | None, settings: InternalServiceReadTokenSettings
) -> InternalServiceContext | None:
    """Constant-time comparison against every CONFIGURED internal
    read token (mirrors api/auth.py's own `_require_token` discipline)
    -- returns the matching service's identity, or None if the token
    is absent/doesn't match any of them.

    Phase 14 correction round, Blocker 1: this function's result is no
    longer, by itself, an authorization decision for anything -- see
    the module docstring. It is used in exactly ONE place now
    (`get_actor_or_tool_gateway_reader`, restricted to tool-gateway's
    own token specifically)."""
    if not token:
        return None
    for service_name, expected in settings.configured_tokens():
        if hmac.compare_digest(token, expected):
            return InternalServiceContext(service_name=service_name)
    return None


async def get_actor_context(
    request: Request,
    x_service_assertion: Annotated[str | None, Header()] = None,
) -> ActorContext | None:
    """Returns the verified actor, or None if organization-context
    enforcement is disabled (the pre-Phase-14 default).

    Reads the assertion from its OWN dedicated header
    (`X-Service-Assertion`), never `Authorization` -- several routes
    this is used on (e.g. the remediation decision endpoint) also
    require one of this service's existing static Bearer tokens in
    `Authorization` itself (see api/auth.py); these are two
    independent, additive checks on the SAME request, not alternatives
    for the same header.

    This is the ONLY dependency incident/evidence routes use as of the
    Phase 14 correction round (Blocker 1) -- there is no longer an
    internal-service-token bypass for any of them. A real human
    actor's assertion, or a derived one an internal service minted for
    that SAME already-verified actor, is REQUIRED.
    """
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


async def require_actor_context(
    request: Request,
    x_service_assertion: Annotated[str | None, Header()] = None,
) -> ActorContext:
    """Phase 15: for brand-new, organization-scoped resources (the
    services registry) that have no pre-Phase-14 legacy/unscoped
    precedent to preserve -- unlike incidents/remediation, there is no
    "fall back to the one shared legacy organization" behavior that
    would ever be correct for data a real user is registering today.

    Deliberately does NOT depend on get_actor_context: that
    dependency's own first line (`if not
    org_context_settings.enabled: return None`) skips assertion
    verification ENTIRELY whenever CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
    is disabled (the pre-Phase-14 default, and this platform's own
    normal local-development default) -- wrapping it would make this
    dependency ALSO silently skip verification in that default
    configuration, 401-ing on every real, validly-signed request the
    web console ever sends. This function instead independently runs
    the SAME real cryptographic verification
    (verify_service_assertion) unconditionally, regardless of that
    flag, so a genuinely authenticated web-console request succeeds
    in both legacy and secure mode alike, and an unauthenticated one
    is rejected in both alike.
    """
    if not x_service_assertion:
        raise HTTPException(status_code=401, detail="unauthorized")

    assertion_settings: ServiceAssertionSettings = request.app.state.service_assertion_settings
    try:
        return verify_service_assertion(x_service_assertion, assertion_settings)
    except InvalidServiceAssertionError as exc:
        logger.warning("rejected an invalid service assertion: %s", exc)
        raise HTTPException(status_code=401, detail="unauthorized") from exc


def require_role(actor: ActorContext, allowed_roles: frozenset[str], *, action: str) -> None:
    """A small, explicit, reusable role-gate -- raises 403 (never 404;
    the actor IS a real, verified, same-organization member, so there is
    no tenant-isolation reason to hide that this resource/action
    exists) when the actor's own real, verified role is not in
    `allowed_roles`. `action` is a short, human-readable description
    used only in the log line, never echoed back to the caller."""
    if actor.role not in allowed_roles:
        logger.info(
            "denied %s for role %s (user_id=%s, org=%s)", action, actor.role, actor.user_id, actor.organization_id
        )
        raise HTTPException(status_code=403, detail="you do not have permission to perform this action")


async def require_legacy_ingestion_allowed(request: Request) -> None:
    """Phase 14 correction round, Issue 4: applied to EVERY ingestion
    endpoint (webhook/Kubernetes/AWS finding ingestion) ALONGSIDE
    their existing static-token dependency -- never a replacement for
    it. A no-op whenever organization-context enforcement is disabled
    (the pre-Phase-14 default: every existing local-dev/CI ingestion
    script keeps working unchanged). Once enforcement IS enabled,
    fails closed (503, not a silent accept-and-discard) if the
    operator has explicitly set
    CONTROL_PLANE_ALLOW_LEGACY_INGESTION=false -- see
    LegacyIngestionSettings's own docstring for why this is the
    explicit, honest boundary
    between legacy demo ingestion and a genuinely multi-tenant
    deployment, rather than silently claiming the latter is done.
    """
    org_context_settings: OrganizationContextSettings = request.app.state.organization_context_settings
    if not org_context_settings.enabled:
        return

    legacy_ingestion_settings: LegacyIngestionSettings = request.app.state.legacy_ingestion_settings
    if not legacy_ingestion_settings.allow_legacy_ingestion:
        raise HTTPException(
            status_code=503,
            detail=(
                "legacy, non-tenant-aware ingestion is disabled in this deployment "
                "(CONTROL_PLANE_ALLOW_LEGACY_INGESTION=false) -- real per-tenant ingestion "
                "association is not implemented; see docs/architecture/phase-14-security-multitenancy.md"
            ),
        )


async def get_actor_or_tool_gateway_reader(
    request: Request,
    x_service_assertion: Annotated[str | None, Header()] = None,
    x_internal_service_token: Annotated[str | None, Header()] = None,  # noqa: ARG001 -- see Issue B note below
) -> ActorContext | InternalServiceContext | None:
    """Phase 14 correction round, Blocker 1: the dependency for the
    THREE remediation-proposal GET routes only (get_remediation_proposal,
    list_remediation_proposals_for_incident, list_remediation_events) --
    NEVER used on incident/evidence routes (those use `get_actor_context`
    alone) and NEVER on the decision/write endpoint.

    Tries a real actor assertion FIRST (covers agent-runtime-service,
    which now forwards the real human actor's identity for its own
    reads -- see its `authz.py::sign_derivative_assertion`).

    Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B: the
    previous fallback -- tool-gateway's bare static internal-service
    token ALONE, with no relayed actor assertion at all, treated as
    sufficient to read ANY already-decided proposal regardless of
    which organization owns it -- is REMOVED. Resolving a proposal's
    real status (decided vs. pending) proved WHEN it became readable;
    it never proved WHO is asking is entitled to that specific
    tenant's data ("a global static internal token alone must not
    permit arbitrary proposal discovery by known UUID"). Tool-gateway
    now relays, unverified by itself (it holds no copy of the shared
    signing secret), the EXACT SAME `X-Service-Assertion` agent-
    runtime-service forwards to it when telling it to execute a
    specific proposal (services/tool-gateway/internal/api/execute.go
    passes the header straight through to every one of its own calls
    to this service) -- this function verifies it exactly like any
    other relayed assertion, and the resulting `ActorContext`'s real
    organization is then checked against the proposal's actual owning
    incident by `require_tool_gateway_proposal_access`, below, exactly
    as it already does for a human actor. Presenting the bare
    static token with NO assertion in secure mode is now a 401 --
    tool-gateway's own `InternalServiceContext` identity is no longer
    constructible via this dependency at all (the type and
    `require_tool_gateway_proposal_access`'s own branch for it remain,
    defensively, but are no longer reachable from any real caller).
    """
    org_context_settings: OrganizationContextSettings = request.app.state.organization_context_settings
    if not org_context_settings.enabled:
        return None

    if x_service_assertion:
        assertion_settings: ServiceAssertionSettings = request.app.state.service_assertion_settings
        try:
            return verify_service_assertion(x_service_assertion, assertion_settings)
        except InvalidServiceAssertionError as exc:
            logger.warning("rejected an invalid service assertion: %s", exc)
            raise HTTPException(status_code=401, detail="unauthorized") from exc

    raise HTTPException(status_code=401, detail="unauthorized")


def require_same_organization(actor: ActorContext | None, resource_organization_id: str) -> None:
    """Gate 5's object-specific check, step 3: "validate tenant
    membership" against the RESOURCE's actual, already-loaded
    organization_id -- never against a client-supplied org id. A
    mismatch raises 404 (not 403): this service must not reveal that a
    resource exists at all to an organization that cannot see it (Gate
    5: "without leaking another tenant's resource contents").

    `actor is None` only reaches here when organization-context
    enforcement is disabled -- the caller is responsible for only
    calling this once an actor is known to be required (see
    api/incidents.py / api/remediation.py).

    Phase 14 correction round, Blocker 1: this function NO LONGER
    accepts `InternalServiceContext` at all -- the type signature is
    `ActorContext | None` deliberately narrower than before. A caller
    with an `InternalServiceContext` must use
    `require_tool_gateway_proposal_access` instead; passing one here
    would be a programming error, not a security boundary, so it
    raises `TypeError` rather than silently granting or denying
    access.
    """
    if actor is None:
        return
    if not isinstance(actor, ActorContext):
        raise TypeError(
            f"require_same_organization received {type(actor).__name__}, not ActorContext -- "
            "an InternalServiceContext must use require_tool_gateway_proposal_access instead"
        )
    if actor.organization_id != str(resource_organization_id):
        raise HTTPException(status_code=404, detail="incident not found")


def require_tool_gateway_proposal_access(
    actor: ActorContext | InternalServiceContext | None,
    *,
    resource_organization_id: str,
    proposal_status: str,
) -> None:
    """Phase 14 correction round, Blocker 1: the proposal-specific
    counterpart to `require_same_organization`, used by the three
    remediation-proposal GET routes.

    - `actor is None`: organization-context enforcement is disabled --
      no-op, same as every other route.
    - `ActorContext`: a real human, or an internal service (agent-
      runtime-service, or tool-gateway relaying the SAME assertion
      agent-runtime-service gave it -- Issue B) forwarding a real,
      already-verified human actor's identity -- enforced by ordinary
      tenant membership, identical to `require_same_organization`.
      Deliberately NOT ALSO gated on `proposal_status`: a real,
      tenant-matched actor reading their own organization's still-
      pending proposal is an ordinary, authorized read, not a leak.
    - `InternalServiceContext`: Phase 14 FINAL MACHINE-IDENTITY
      TENANT-BOUNDARY FIX, Issue B: `get_actor_or_tool_gateway_reader`
      no longer ever returns this type (the bare static tool-gateway
      token is no longer sufficient alone -- see that function's own,
      updated docstring). This branch is kept only as an explicit,
      defensive fallback should some future caller ever construct one
      directly -- not reachable from any real request today.
    """
    if actor is None:
        return
    if isinstance(actor, ActorContext):
        if actor.organization_id != str(resource_organization_id):
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        return
    if isinstance(actor, InternalServiceContext):
        if proposal_status not in PROPOSAL_STATUSES_READABLE_BY_TOOL_GATEWAY_TOKEN:
            raise HTTPException(status_code=404, detail="remediation proposal not found")
        return
    raise TypeError(f"unexpected actor type: {type(actor).__name__}")
