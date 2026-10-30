"""Phase 17A item 2: real proof that `core/trusted_proxy.py` only ever
trusts `X-Forwarded-For` on a connection whose own direct TCP peer
resolves to a configured trusted-proxy host -- never a wildcard, never
"all private addresses", and never merely because the header is
present."""

import socket
from unittest.mock import MagicMock

import control_plane.core.trusted_proxy as trusted_proxy_module
from control_plane.core.trusted_proxy import TrustedProxySettings, resolve_client_ip


def _request(*, peer: str | None, forwarded_for: str | None = None) -> MagicMock:
    request = MagicMock()
    request.client = MagicMock(host=peer) if peer is not None else None
    request.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    return request


def test_disabled_by_default_ignores_forwarded_header_even_from_the_trusted_host():
    settings = TrustedProxySettings(enabled=False, trusted_hosts=("127.0.0.1",))
    request = _request(peer="127.0.0.1", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request, settings) == "127.0.0.1"


def test_enabled_trusts_the_header_only_from_the_configured_proxy_address():
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    request = _request(peer="127.0.0.1", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request, settings) == "203.0.113.9"


def test_enabled_but_direct_peer_is_not_the_trusted_proxy_ignores_the_header():
    """A forged header from a NON-proxy source -- the exact bypass
    attempt item 2 exists to close. The direct connection is from
    some other address entirely; the header is never consulted."""
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    request = _request(peer="198.51.100.5", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request, settings) == "198.51.100.5"


def test_distinct_real_clients_behind_the_trusted_proxy_retain_distinct_identities():
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    client_a = _request(peer="127.0.0.1", forwarded_for="203.0.113.1")
    client_b = _request(peer="127.0.0.1", forwarded_for="203.0.113.2")
    assert resolve_client_ip(client_a, settings) != resolve_client_ip(client_b, settings)
    assert resolve_client_ip(client_a, settings) == "203.0.113.1"
    assert resolve_client_ip(client_b, settings) == "203.0.113.2"


def test_forged_header_cannot_impersonate_the_trusted_proxys_own_client_identity():
    """Even from the trusted hop, a SECOND, different real client
    sending its own forged X-Forwarded-For does not let it collide
    with -- or hijack -- another real client's rate-limit bucket: each
    request's own header value (which only Caddy, the trusted hop,
    ever sets) is trusted independently and correctly, never reset by
    a prior request."""
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    first = _request(peer="127.0.0.1", forwarded_for="203.0.113.1")
    second = _request(peer="127.0.0.1", forwarded_for="203.0.113.1")
    assert resolve_client_ip(first, settings) == resolve_client_ip(second, settings) == "203.0.113.1"


def test_missing_forwarded_header_from_the_trusted_proxy_falls_back_to_direct_peer():
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    request = _request(peer="127.0.0.1", forwarded_for=None)
    assert resolve_client_ip(request, settings) == "127.0.0.1"


def test_no_client_at_all_resolves_to_a_safe_unknown_sentinel():
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("127.0.0.1",))
    request = _request(peer=None)
    assert resolve_client_ip(request, settings) == "unknown"


def test_settings_from_env_defaults_disabled(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_ENABLED", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_HOSTS", raising=False)
    settings = TrustedProxySettings.from_env()
    assert settings.enabled is False
    assert settings.trusted_hosts == ()


def test_settings_from_env_parses_comma_separated_hosts(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_ENABLED", "true")
    monkeypatch.setenv("TRUSTED_PROXY_HOSTS", "caddy, 10.0.0.5")
    settings = TrustedProxySettings.from_env()
    assert settings.enabled is True
    assert settings.trusted_hosts == ("caddy", "10.0.0.5")


# --- CORRECTION ROUND: the trusted-host IP resolution cache used to
# be a plain `@lru_cache` with no expiry at all, so a trusted proxy
# container that was recreated with a new address (restart, health-
# check-triggered recreation, image update) stayed trusted at its OLD
# address forever, for the lifetime of this process -- and a later
# container that happened to receive that same freed address would be
# wrongly trusted too. These tests exercise the actual hostname-
# resolution/TTL path (every test above uses a literal IP, which
# short-circuits before ever touching this cache at all).


def _clear_resolution_cache():
    trusted_proxy_module._trusted_ips_cache.clear()


def test_address_change_is_picked_up_after_the_cache_ttl_expires(monkeypatch):
    _clear_resolution_cache()
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("caddy",))
    fake_time = [1000.0]
    monkeypatch.setattr(trusted_proxy_module.time, "monotonic", lambda: fake_time[0])

    monkeypatch.setattr(
        trusted_proxy_module.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.11", 0))],
    )
    request_old = _request(peer="10.0.0.11", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_old, settings) == "203.0.113.9"

    # The real container got recreated and now has a DIFFERENT
    # address -- still well within the TTL window, so the stale,
    # cached address must still be the one trusted (proves this is a
    # real cache, not a no-op).
    monkeypatch.setattr(
        trusted_proxy_module.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.22", 0))],
    )
    request_during_ttl = _request(peer="10.0.0.22", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_during_ttl, settings) == "10.0.0.22"  # header NOT trusted yet

    # Advance past the TTL -- the next request must re-resolve and
    # trust the NEW address instead of the stale one.
    fake_time[0] += trusted_proxy_module._TRUSTED_IPS_TTL_SECONDS + 1
    request_after_ttl = _request(peer="10.0.0.22", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_after_ttl, settings) == "203.0.113.9"

    # And the OLD address must no longer be trusted at all.
    request_old_after_ttl = _request(peer="10.0.0.11", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_old_after_ttl, settings) == "10.0.0.11"


def test_resolution_failure_fails_closed_and_does_not_retain_stale_trust(monkeypatch):
    _clear_resolution_cache()
    settings = TrustedProxySettings(enabled=True, trusted_hosts=("caddy",))
    fake_time = [2000.0]
    monkeypatch.setattr(trusted_proxy_module.time, "monotonic", lambda: fake_time[0])

    monkeypatch.setattr(
        trusted_proxy_module.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.33", 0))],
    )
    request_ok = _request(peer="10.0.0.33", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_ok, settings) == "203.0.113.9"

    # DNS now fails entirely (e.g. the trusted host is mid-recreation)
    # -- once the TTL expires, this must fail CLOSED: the previously
    # trusted address is no longer trusted, never silently kept.
    fake_time[0] += trusted_proxy_module._TRUSTED_IPS_TTL_SECONDS + 1

    def _raise_gaierror(host, port):
        raise socket.gaierror("temporary resolution failure")

    monkeypatch.setattr(trusted_proxy_module.socket, "getaddrinfo", _raise_gaierror)
    request_during_outage = _request(peer="10.0.0.33", forwarded_for="203.0.113.9")
    assert resolve_client_ip(request_during_outage, settings) == "10.0.0.33"  # header NOT trusted
