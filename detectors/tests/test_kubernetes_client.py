"""Gate B (Phase 12A): bounded Kubernetes REST client + collector
tests -- outcome discrimination (success/empty/malformed/unavailable/
forbidden/not_found), namespace validation, bounded item count, and a
structural confirmation that no write/exec/secrets method exists."""

import inspect
import ssl

import httpx
import pytest

from detectors.clients.kubernetes_client import (
    KubernetesClient,
    KubernetesConfigError,
    KubernetesUnavailableError,
    MAX_ITEMS,
)
from detectors.kubernetes.collector import collect_deployments, collect_events, collect_pods, collect_replicasets
from detectors.schemas.kubernetes import CollectionOutcome

# A throwaway, locally-generated, self-signed test certificate/key
# pair -- used ONLY to prove `load_cert_chain` parses real PEM content
# without raising; never a credential for any real system, and not
# the real cluster's own certificate (see kubernetes_client.py's own
# comment on why this code path exists: httpx's `cert=` convenience
# parameter was confirmed, against the real kind cluster, to NOT
# reliably present the client certificate during the TLS handshake).
_TEST_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIC7DCCAdSgAwIBAgIUbyWN7MxyCPh0gerzHFbPXDOtGk4wDQYJKoZIhvcNAQEL
BQAwFjEUMBIGA1UEAwwLdGVzdC1jbGllbnQwHhcNMjYxMDIxMTUyMjA5WhcNMjYx
MDIyMTUyMjA5WjAWMRQwEgYDVQQDDAt0ZXN0LWNsaWVudDCCASIwDQYJKoZIhvcN
AQEBBQADggEPADCCAQoCggEBAKxcu3IyAYxfTltnMBbSbMf7phcRyYs6++Cp7Njw
sVVFv3eNZXwU1pVJp19k+OdBgibBAY6lU3ajtAHC2cZAwFsGvqLLr+yH95pu87U3
XpEr3UQnMG+Xzhe+tLPdJtmFoSyeId4PEldB1xaIM4HeNM/cJZEGlKApS905CnWb
4WJlmNlLBs56Mn8Mp/vyeTCzpcQHYVLNuJbTtky0rGcggzIKYl1YW7RZ/GZtAO+N
6Gwr9jFVCyiQcy8/3PPth0Dmz+P7GNu6xwTMxU5p2lFu25gZn6Tztx4gzA/piLki
y3zBuOjYvWUcJS77x1UPv3VMOCnMymvu8aAgfOsi6sxOMY8CAwEAAaMyMDAwHQYD
VR0OBBYEFFKDF/3XFDiAF7LdWHuVkCuX2S6rMA8GA1UdEwEB/wQFMAMBAf8wDQYJ
KoZIhvcNAQELBQADggEBAHUNLv9LoSd2Rrt5UP3/l63IFR8mOniczWSogUu6urko
RYvO22oSZ7KQwgn81aZzbL5czSCgCAkwHZl9sh40Y1CmeS3a4SbgKrM1+Sv/4yx+
WSgMUupKkjDa8daNYiw4VCKZBN7gZb5whaBM4EAh4k057sCQjHuidlJtiIYXn4GT
6mOiSFa/m+leDH6Wu7h+UhTuknPEjrzzRALM3JHkKiBcsz29OzHd5iEr0wtu5iRa
vkyknzH7UbQZE3vW9tgGozwnIa9PS0l9gnRv+OL4C3I2PHYfsawMoBUmT4ofGt6g
lTEHKwI4FO4v3/x169iYMuP6f5ts45qvoBF9EcAXaVM=
-----END CERTIFICATE-----
"""
_TEST_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCsXLtyMgGMX05b
ZzAW0mzH+6YXEcmLOvvgqezY8LFVRb93jWV8FNaVSadfZPjnQYImwQGOpVN2o7QB
wtnGQMBbBr6iy6/sh/eabvO1N16RK91EJzBvl84XvrSz3SbZhaEsniHeDxJXQdcW
iDOB3jTP3CWRBpSgKUvdOQp1m+FiZZjZSwbOejJ/DKf78nkws6XEB2FSzbiW07ZM
tKxnIIMyCmJdWFu0WfxmbQDvjehsK/YxVQsokHMvP9zz7YdA5s/j+xjbuscEzMVO
adpRbtuYGZ+k87ceIMwP6Yi5Ist8wbjo2L1lHCUu+8dVD791TDgpzMpr7vGgIHzr
IurMTjGPAgMBAAECggEAULSZBmb4x6AGohDGeSEtU1R3GB05iCplrvQR1SCagCmI
9fMsnjVppnxW1PmD/FB1nyzHTGIIGyiazCpO6x/9kYGueK60IKYnn1WtYmBbNNFb
qSJKcS4dD4w5s3BtVPPXnHsss3vOJDJNgpzitT/07ZEQu//fTsEXZy3iwl/rYDUa
Nc/dn2eKh6eKn0OmZDKroD27kOxypIxru9CNRuEXUtBzTyf5EY8D8kloxJ44Vd86
QxOKaUH9lKieSa5DizmRT/QuvEJABgoLi4iG96cmtZH7eocf+kaG1J11giuV0+9T
AHbM7DzYqS9xuW4ILHYnP7TW/w0JdbO3t4d+wlZ4xQKBgQDcOltVuWjLRwm8moQO
3uSRnDTB260er8I8+IbgRfIbW893sygFYm8TazHx6IlkXHtTwAB2LrixLtixqzlx
yvY8x5Am5MirShVP9NGIZUK9PaQntaS4INwU5eyPx1kq/IdJIxkmPY+s12/Rvoxi
0IasYyX68lMaXC+Umkt/p6vxNQKBgQDIW/75wVASdDKAm4E/PqRDPsHcQ4AGiJoq
nsU2NEYmkQK961YwaFVBUz+r7n7DFmv6uVPExozZKtGE0iC86gtqhmAAo7Nu9qs/
oNSV8fpJROaCDdhd3Dt708mfrezh0Ej+o2qx1D9OwCKIWVpGSTX0TsyhESckh+8+
bJ64kQEUMwKBgQDAG8PqzrckhA5xUNSb6EG452t6JDgrSaSF7UIyx7E/vmIHh+gE
cm50oRDLdk7LloUadKWycmU4YqYyriuJIUSVlnwgAXkvOovG2MgjVDnYvLnCzggn
erqhHES002/sOKeG3DAnFJKNcs0fSTpLRJ4GKONLujFWEE6NMd9kNw6ddQKBgBcI
bGFt1bSpYvzh45PPsbaBSmv13ovhvEdWBTnb/IyGcxg+K6RY+iQOW+1591yaAUPL
dlPSt3Jnt7pbJaRSC4ntdK/eIcyJ0tn3tTifnrQ5lX4x9UOlA7mSeUVAC1FSTnHn
e2aCDd0RvWaLTxNxayBwxplljWhnsBsvBXgWQ1d9AoGARQHdNJ/p3rVFPbNucaZ9
SR0DVVTTJlZhWx1QS7uqk7lCRy9m5jxA1rcRTQ/9naGPOY68JWIl0GtwhY/IoWCO
4JCi70B7pNzHKmezRIpjgxQb8sCoe6rdUtw8MNaz3IeRPoyjGp/Gfk9lpk8r2t72
TcPoORdKSz4jKDPKGKd7AAE=
-----END PRIVATE KEY-----
"""


def _client(handler) -> KubernetesClient:
    return KubernetesClient(
        "https://k8s.invalid:6443", "reliability-sandbox", transport=httpx.MockTransport(handler)
    )


def _pods_body(items: list) -> dict:
    return {"kind": "PodList", "items": items}


def _minimal_pod(name: str, phase: str = "Running") -> dict:
    return {
        "metadata": {"name": name, "namespace": "reliability-sandbox", "uid": "u-1"},
        "spec": {"nodeName": "node-1"},
        "status": {"phase": phase, "containerStatuses": []},
    }


# ---------------------------------------------------------------------
# namespace validation / structural safety
# ---------------------------------------------------------------------


def test_invalid_namespace_is_rejected_at_construction():
    with pytest.raises(KubernetesConfigError):
        KubernetesClient("https://k8s.invalid", "Not_A_Valid_Namespace!")


def test_client_has_no_write_exec_or_secrets_methods():
    public_methods = {name for name, _ in inspect.getmembers(KubernetesClient, predicate=inspect.isfunction) if not name.startswith("_")}
    assert public_methods == {"list_pods", "list_deployments", "list_replicasets", "list_events"}
    for forbidden in ("post", "put", "patch", "delete", "exec", "attach", "portforward", "secret"):
        assert not any(forbidden in m.lower() for m in public_methods)


# ---------------------------------------------------------------------
# outcome discrimination
# ---------------------------------------------------------------------


async def test_successful_collection_with_items():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pods_body([_minimal_pod("pod-a"), _minimal_pod("pod-b")]))

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.SUCCESS
    assert result.items_count == 2
    assert len(items) == 2


async def test_successful_collection_with_zero_items_is_empty_not_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pods_body([]))

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.EMPTY
    assert items == []


async def test_forbidden_403_is_distinguished_from_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.FORBIDDEN
    assert items == []


async def test_not_found_404_is_distinguished_from_forbidden_and_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.NOT_FOUND


async def test_connection_failure_is_unavailable_never_a_false_healthy_result():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.UNAVAILABLE
    assert items == []


async def test_non_json_body_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json {{{")

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.UNAVAILABLE


async def test_malformed_shape_missing_items_key_is_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"kind": "PodList"})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.MALFORMED


async def test_malformed_body_not_an_object_is_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.MALFORMED


async def test_unexpected_status_code_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.UNAVAILABLE


async def test_items_are_bounded_even_if_server_returns_more():
    huge = [_minimal_pod(f"pod-{i}") for i in range(MAX_ITEMS + 50)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pods_body(huge))

    result, items = await collect_pods(_client(handler))
    assert result.items_count <= MAX_ITEMS
    assert len(items) <= MAX_ITEMS


async def test_only_get_requests_are_ever_issued():
    methods_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods_seen.append(request.method)
        return httpx.Response(200, json=_pods_body([]))

    client = _client(handler)
    await collect_pods(client)
    await collect_deployments(client)
    await collect_replicasets(client)
    await collect_events(client)
    assert methods_seen
    assert all(m == "GET" for m in methods_seen)


# ---------------------------------------------------------------------
# mutual-TLS client-cert construction (regression: httpx's `cert=`
# convenience parameter was confirmed, against the real kind cluster,
# to NOT reliably present the client certificate -- the API server
# saw "system:anonymous" instead of the configured identity. Fixed by
# building an `ssl.SSLContext` via `load_cert_chain` directly.)
# ---------------------------------------------------------------------


async def test_client_cert_is_loaded_into_a_real_ssl_context_not_passed_as_a_bare_tuple(tmp_path, monkeypatch):
    cert_path = tmp_path / "client.crt"
    key_path = tmp_path / "client.key"
    cert_path.write_text(_TEST_CERT_PEM)
    key_path.write_text(_TEST_KEY_PEM)

    calls = []
    real_load_cert_chain = ssl.SSLContext.load_cert_chain

    def recording_load_cert_chain(self, certfile=None, keyfile=None, password=None):
        calls.append((certfile, keyfile))
        return real_load_cert_chain(self, certfile=certfile, keyfile=keyfile, password=password)

    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", recording_load_cert_chain)

    client = KubernetesClient(
        "https://k8s.invalid:6443",
        "reliability-sandbox",
        client_cert_path=str(cert_path),
        client_key_path=str(key_path),
    )
    async with client._build_client():
        pass

    assert calls == [(str(cert_path), str(key_path))]


async def test_requests_only_ever_target_the_configured_namespace_path():
    paths_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths_seen.append(request.url.path)
        return httpx.Response(200, json=_pods_body([]))

    client = _client(handler)
    await collect_pods(client)
    await collect_deployments(client)
    await collect_replicasets(client)
    await collect_events(client)
    assert all("/reliability-sandbox/" in p for p in paths_seen)
    assert not any("secret" in p.lower() for p in paths_seen)
