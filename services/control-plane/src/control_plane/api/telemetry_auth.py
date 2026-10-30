"""Phase 16 Gate 3/4: authenticates ONE telemetry ingestion request
against a real integration credential.

Deliberately the ONLY place in this service that derives
organization_id/service_id from anything other than a Better-Auth-
backed human actor's own verified session -- and even here, the
derivation is from a credential this service itself issued and hashed
(core/credentials.py), verified with a constant-time comparison,
checked for revocation, and rate-limited -- never from any header,
query parameter, or request-body field the caller also controls (Gate
4: "Prevent an enrolled client from selecting its own arbitrary
organization identity... Derive organization/service identity from the
authenticated credential, not incoming labels.").

CORRECTION ROUND (independent review, item 6): the previous round's
AUTH_FAILURE_RATE_LIMITER keyed its budget by the credential id the
caller CLAIMED in the bearer token, falling back to the connecting
client's address only when the token was too malformed to extract an
id from at all. That key is entirely attacker-controlled -- a
credential id is just a public-looking string on the wire, so an
attacker could exhaust the 10-failures/5-minute budget for a
(fabricated) id, then simply use a different fabricated id on the very
next request and never be bounded at all, from the SAME source. The
limiter is now keyed EXCLUSIVELY by the request's resolved client
address (see `core/trusted_proxy.py::resolve_client_ip`), never a
value the request body/headers can set directly. In local development
(no reverse proxy, `TRUSTED_PROXY_ENABLED` unset) that resolved
address is always the real TCP peer ASGI/Starlette itself observed
opening the connection -- `X-Forwarded-For` is never read or trusted.

PHASE 17A: a real single-host deployment DOES sit behind a reverse
proxy (Caddy -- see deploy/caddy/Caddyfile and deploy/docker-compose.
override.yml), which is the only way to reach this service at all in
that deployment (no port is published for it directly). Trusting
`X-Forwarded-For` unconditionally in THAT topology would otherwise
collapse every distinct external client onto the proxy's own single
container IP, defeating this limiter's entire purpose -- so
`resolve_client_ip` trusts the header only when the request's own
direct TCP peer is independently confirmed to be that configured
proxy, and Caddy itself always OVERWRITES (never appends to) the
header with the real connecting client's address before forwarding --
see that module's own docstring for the full threat model.
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from control_plane.api.dependencies import get_integration_credential_repository
from control_plane.core.credentials import parse_bearer_token, verify_secret
from control_plane.core.rate_limit import AUTH_FAILURE_RATE_LIMITER, INGESTION_RATE_LIMITER
from control_plane.core.trusted_proxy import resolve_client_ip
from control_plane.repositories.integration_credential_repository import IntegrationCredentialRepository

logger = logging.getLogger("control_plane.telemetry_auth")


@dataclass(frozen=True)
class TelemetryCredentialContext:
    integration_id: str
    organization_id: str
    service_id: str
    credential_id: str


def _source_key(request: Request) -> str:
    """The AUTH-FAILURE limiter's only key: the request's resolved
    client address (see `core/trusted_proxy.py` for exactly when that
    is allowed to come from `X-Forwarded-For` instead of the direct
    TCP peer)."""
    return f"ip:{resolve_client_ip(request)}"


async def require_telemetry_credential(
    request: Request,
    repo: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    authorization: Annotated[str | None, Header()] = None,
) -> TelemetryCredentialContext:
    # Gate 3/item 6: rate-limit AUTH FAILURES before doing any further
    # work -- checked (and only checked, never bypassed) regardless of
    # which specific way this request is about to fail, INCLUDING a
    # missing header entirely (a client hammering with no
    # `Authorization` header at all is just as cheap a probe as a
    # malformed one, and must be bounded the same way).
    failure_key = _source_key(request)

    def _deny(reason: str) -> None:
        if not AUTH_FAILURE_RATE_LIMITER.check(failure_key):
            logger.warning("telemetry auth-failure rate limit exceeded for %s", failure_key)
            raise HTTPException(status_code=429, detail="too many authentication failures; slow down")
        logger.info("rejected telemetry ingestion credential: %s", reason)
        raise HTTPException(status_code=401, detail="invalid credential")

    if not authorization or not authorization.startswith("Bearer "):
        _deny("missing or malformed Authorization header")
        raise AssertionError("unreachable")  # _deny always raises
    token = authorization.removeprefix("Bearer ").strip()

    parsed = parse_bearer_token(token)
    if parsed is None:
        _deny("malformed bearer token")
        raise AssertionError("unreachable")  # _deny always raises

    credential_id, secret = parsed
    row = await repo.get_by_credential_id(credential_id)
    if row is None:
        _deny("unrecognized credential id")
        raise AssertionError("unreachable")

    if not verify_secret(secret, row["credential_secret_hash"]):
        _deny("secret did not match the stored hash")
        raise AssertionError("unreachable")

    if row["status"] != "active":
        # Gate 3/4: "Deny invalid/expired/revoked credentials" -- a
        # structurally-correct, hash-matching credential that has been
        # revoked is still an authentication failure, not merely an
        # authorization one (it proves nothing about who possesses it
        # now vs. when it was first issued), so it is still subject to
        # the SAME failure rate limit as a wrong secret.
        _deny(f"credential status is {row['status']!r}, not active")
        raise AssertionError("unreachable")

    # Gate 4: "Ingestion rate limits" -- checked only for a credential
    # that is otherwise genuinely valid; a request that never even
    # authenticates must never consume a legitimate credential's own
    # ingestion budget.
    if not INGESTION_RATE_LIMITER.check(f"cred:{credential_id}"):
        raise HTTPException(status_code=429, detail="ingestion rate limit exceeded")

    return TelemetryCredentialContext(
        integration_id=str(row["id"]),
        organization_id=str(row["organization_id"]),
        service_id=str(row["service_id"]),
        credential_id=credential_id,
    )
