"""Phase 17A item 2: the ONE place this service decides whether to
trust an inbound `X-Forwarded-For` header for rate-limit-relevant
client-IP resolution.

THREAT MODEL: this service is never directly reachable from outside
Docker in a deployment (deploy/docker-compose.override.yml publishes
no port for it) -- the only path in is through Caddy
(deploy/caddy/Caddyfile), which OVERWRITES (never appends to)
`X-Forwarded-For` with the real connecting client's address on every
request it proxies. That means `X-Forwarded-For` is only ever
trustworthy on a connection whose own, real, observed TCP peer is
Caddy itself -- never on a connection from anywhere else (another
container on the same network could still forge the header, or an
operator could misconfigure the proxy boundary). This module checks
that precondition explicitly before trusting the header at all; it
never trusts a wildcard, "all private addresses," or the header's mere
presence.

Local development (TRUSTED_PROXY_ENABLED unset/false, the default --
the base docker-compose.yml never sets this) is completely unaffected:
`resolve_client_ip` simply returns the real, direct TCP peer address
every time, exactly as every pre-Phase-17A caller of
`request.client.host` already did.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from dataclasses import dataclass

from fastapi import Request

logger = logging.getLogger("control_plane.trusted_proxy")

# CORRECTION ROUND: this used to be `@lru_cache(maxsize=8)` -- cached
# for the entire lifetime of the process, with no expiry at all. If
# the trusted-proxy container (caddy) is ever recreated -- a restart,
# a health-check-triggered recreation, an image update -- Docker can
# hand it a NEW internal IP while this process keeps running with the
# OLD one memoized forever. Not just stale: Docker's internal network
# can later assign that SAME now-free address to a DIFFERENT
# container, which this process would then keep wrongly trusting to
# supply `X-Forwarded-For` indefinitely. A short, bounded TTL means a
# changed address is picked up within one window instead of requiring
# a process restart, while still avoiding a real DNS lookup on every
# single request.
_TRUSTED_IPS_TTL_SECONDS = 30.0
_trusted_ips_cache: dict[tuple[str, ...], tuple[float, frozenset[str]]] = {}


@dataclass(frozen=True)
class TrustedProxySettings:
    enabled: bool
    trusted_hosts: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "TrustedProxySettings":
        raw_enabled = os.environ.get("TRUSTED_PROXY_ENABLED", "false")
        enabled = raw_enabled.strip().lower() in ("1", "true", "yes", "on")
        raw_hosts = os.environ.get("TRUSTED_PROXY_HOSTS", "")
        hosts = tuple(h.strip() for h in raw_hosts.split(",") if h.strip())
        return cls(enabled=enabled, trusted_hosts=hosts)


def _resolve_trusted_ips(trusted_hosts: tuple[str, ...]) -> frozenset[str]:
    """Resolves each configured trusted-proxy hostname (a Compose
    service name, e.g. "caddy") to its CURRENT container IP(s) on the
    internal Docker network. Cached for at most
    `_TRUSTED_IPS_TTL_SECONDS` (see module docstring for why this is
    bounded, not permanent) -- re-resolving on every single request
    would still be wasteful DNS traffic for no real benefit. Never
    falls back to "trust everything" if resolution fails: an
    unresolvable trusted host simply contributes no trusted IPs for
    this refresh, which fails CLOSED (nothing from it is trusted,
    self-healing on the next refresh) rather than open, and never
    falls back to a previous, possibly-stale successful result
    either."""
    now = time.monotonic()
    cached = _trusted_ips_cache.get(trusted_hosts)
    if cached is not None and now - cached[0] < _TRUSTED_IPS_TTL_SECONDS:
        return cached[1]

    resolved: set[str] = set()
    for host in trusted_hosts:
        try:
            # A literal IP (useful in a non-Compose deployment) is
            # returned as-is; a hostname is resolved via the
            # container's own DNS (Docker's embedded resolver).
            ipaddress.ip_address(host)
            resolved.add(host)
            continue
        except ValueError:
            pass
        try:
            for info in socket.getaddrinfo(host, None):
                resolved.add(info[4][0])
        except socket.gaierror as exc:
            logger.warning("trusted proxy host %r could not be resolved: %s", host, exc)

    result = frozenset(resolved)
    _trusted_ips_cache[trusted_hosts] = (now, result)
    return result


def resolve_client_ip(request: Request, settings: TrustedProxySettings | None = None) -> str:
    """Returns the IP address rate-limit keys should use for this
    request. Trusts `X-Forwarded-For` ONLY when BOTH: (1)
    `TRUSTED_PROXY_ENABLED=true`, and (2) the request's own real,
    direct TCP peer (`request.client.host` -- never itself read from a
    header) resolves to one of `TRUSTED_PROXY_HOSTS`'s current IPs.
    Otherwise -- including a direct connection from anywhere else, a
    missing client address, or a resolution failure -- returns the
    real direct peer address itself, exactly as every pre-Phase-17A
    caller already did, and the header (whatever it contains, forged
    or not) is never consulted."""
    settings = settings or TrustedProxySettings.from_env()
    direct_peer = request.client.host if request.client else None

    if settings.enabled and direct_peer is not None:
        trusted_ips = _resolve_trusted_ips(settings.trusted_hosts)
        if direct_peer in trusted_ips:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                # Caddy overwrites this header with exactly one value
                # (the real client address) on every proxied request
                # -- never a client-suppliable, comma-separated chain
                # of prior hops. Taking the value verbatim (not "the
                # last entry of a chain") is intentional: a chain
                # would imply trusting multiple hops, which this
                # single-proxy deployment never does.
                candidate = forwarded.split(",")[0].strip()
                if candidate:
                    return candidate

    return direct_peer or "unknown"
