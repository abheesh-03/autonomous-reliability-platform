"""Gate B (Phase 12A): a bounded, read-only Kubernetes REST client --
same discipline as `prometheus_client.py`/`tempo_client.py`/
`control_plane_client.py`: a FIXED, small set of GET-only endpoints,
one namespace, bounded timeouts, bounded result size, and an explicit
outcome for every call (never a bare exception the caller must guess
the meaning of).

This client never uses the official `kubernetes` Python SDK -- it
talks to the same, stable, versioned Kubernetes REST API directly via
`httpx`, exactly mirroring this package's own established pattern of
building a minimal, dependency-light client rather than adopting a
heavy third-party SDK for a handful of GET calls.

Security, enforced structurally (not just by convention):
  - only 4 GET methods exist on this class at all (pods, deployments,
    replicasets, events) -- there is no write method to call, no
    exec, attach, or port forward method, and no secrets method;
  - every REST path is a FIXED template with exactly one
    caller-controlled substitution point (the namespace), which is
    validated against the real Kubernetes DNS-1123 label pattern
    before it is ever interpolated into a URL -- never an arbitrary
    caller-or-LLM-supplied path. The one other substitution point
    (`continue`, correction round Issue 1) is never caller-supplied:
    its value only ever comes from a prior response's own
    `metadata.continue` field (an opaque, server-issued pagination
    token), and is always percent-encoded before interpolation;
  - certificate/key material is written to a private (0700/0600)
    temporary directory ONLY for the duration of one `with` block and
    is always removed afterward, and is never included in any
    exception message, log line, or finding this module produces.
"""

import base64
import contextlib
import os
import re
import shutil
import ssl
import tempfile
import urllib.parse
from dataclasses import dataclass

import httpx
import yaml

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_ITEMS = 500  # a defensive cardinality cap -- never an unbounded list, regardless of what the API server returns
_NAMESPACE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class KubernetesConfigError(Exception):
    """A caller/configuration error (bad kubeconfig, unknown context,
    invalid namespace) -- never raised for a live API call failure."""


class KubernetesUnavailableError(Exception):
    """The API server could not be reached, or returned a response
    this client cannot interpret at all (never includes credential
    material)."""


class KubernetesForbiddenError(Exception):
    """The API server was reached and responded with HTTP 403 --
    distinct from `KubernetesUnavailableError` so a caller can tell
    'nothing answered' apart from 'something answered but refused
    this request' (RBAC)."""


def _validate_namespace(namespace: str) -> str:
    if not _NAMESPACE_RE.match(namespace):
        raise KubernetesConfigError(f"namespace {namespace!r} is not a valid Kubernetes namespace name")
    return namespace


class KubernetesClient:
    """Every method here is a GET against exactly one fixed,
    namespaced REST path. There is no method on this class that can
    perform a write, exec, attach, port-forward, or read Secrets."""

    def __init__(
        self,
        api_server_url: str,
        namespace: str,
        *,
        ca_cert_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
        bearer_token: str | None = None,
        request_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = api_server_url.rstrip("/")
        self._namespace = _validate_namespace(namespace)
        self._ca_cert_path = ca_cert_path
        self._client_cert_path = client_cert_path
        self._client_key_path = client_key_path
        self._bearer_token = bearer_token
        self._timeout = httpx.Timeout(request_timeout, connect=request_timeout)
        self._transport = transport

    @property
    def namespace(self) -> str:
        return self._namespace

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": self._timeout, "transport": self._transport}
        # httpx's `cert=` convenience parameter does not reliably
        # present the client certificate during the TLS handshake on
        # every httpx version this project may run under (confirmed
        # against the real kind cluster: the API server received the
        # request as "system:anonymous" rather than the configured
        # client identity). Building the `ssl.SSLContext` explicitly
        # via `load_cert_chain` is the same mechanism `kubectl`/the
        # stdlib `ssl` module use directly, and was confirmed against
        # the real cluster to correctly authenticate.
        if self._client_cert_path and self._client_key_path:
            ctx = ssl.create_default_context(cafile=self._ca_cert_path) if self._ca_cert_path else ssl.create_default_context()
            ctx.load_cert_chain(certfile=self._client_cert_path, keyfile=self._client_key_path)
            kwargs["verify"] = ctx
        elif self._ca_cert_path:
            kwargs["verify"] = self._ca_cert_path
        headers = {}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        if headers:
            kwargs["headers"] = headers
        return httpx.AsyncClient(**kwargs)

    async def _get(self, path: str) -> tuple[int, object]:
        """Returns (status_code, parsed_json_or_none). Never raises on
        a non-200 status -- the caller interprets 403/404/other
        explicitly. Raises `KubernetesUnavailableError` only for an
        actual connection/transport failure or a non-JSON body."""
        url = f"{self._base_url}{path}"
        try:
            async with self._build_client() as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise KubernetesUnavailableError(f"could not reach the Kubernetes API server: {type(exc).__name__}") from exc

        if resp.status_code == 403:
            return resp.status_code, None
        if resp.status_code == 404:
            return resp.status_code, None
        if resp.status_code != 200:
            raise KubernetesUnavailableError(f"Kubernetes API server returned unexpected HTTP {resp.status_code}")
        try:
            body = resp.json()
        except Exception as exc:
            raise KubernetesUnavailableError(f"malformed (non-JSON) response from the Kubernetes API server: {type(exc).__name__}") from exc
        return resp.status_code, body

    def _paged_path(self, base_path: str, continue_token: str | None) -> str:
        """Correction round (Issue 1): `continue_token` is NEVER
        caller/LLM-supplied free text -- every call site in
        `detectors/kubernetes/collector.py` only ever passes back a
        token it already read from a PRIOR response's own
        `metadata.continue` field (an opaque, server-issued string),
        and it is always percent-encoded here before interpolation."""
        path = f"{base_path}?limit={MAX_ITEMS}"
        if continue_token:
            path += f"&continue={urllib.parse.quote(continue_token, safe='')}"
        return path

    async def list_pods(self, *, continue_token: str | None = None) -> tuple[int, object]:
        return await self._get(self._paged_path(f"/api/v1/namespaces/{self._namespace}/pods", continue_token))

    async def list_deployments(self, *, continue_token: str | None = None) -> tuple[int, object]:
        return await self._get(self._paged_path(f"/apis/apps/v1/namespaces/{self._namespace}/deployments", continue_token))

    async def list_replicasets(self, *, continue_token: str | None = None) -> tuple[int, object]:
        return await self._get(self._paged_path(f"/apis/apps/v1/namespaces/{self._namespace}/replicasets", continue_token))

    async def list_events(self, *, continue_token: str | None = None) -> tuple[int, object]:
        return await self._get(self._paged_path(f"/api/v1/namespaces/{self._namespace}/events", continue_token))


@dataclass(frozen=True)
class _ParsedAuth:
    server: str
    ca_data: bytes | None
    ca_file: str | None
    client_cert_data: bytes | None
    client_cert_file: str | None
    client_key_data: bytes | None
    client_key_file: str | None
    token: str | None


def _b64(value: object) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None


def _parse_kubeconfig(kubeconfig_path: str, context_name: str) -> _ParsedAuth:
    try:
        with open(kubeconfig_path, "r") as f:
            doc = yaml.safe_load(f)
    except OSError as exc:
        raise KubernetesConfigError(f"could not read kubeconfig: {type(exc).__name__}") from exc
    except yaml.YAMLError as exc:
        raise KubernetesConfigError(f"kubeconfig is not valid YAML: {type(exc).__name__}") from exc

    if not isinstance(doc, dict):
        raise KubernetesConfigError("kubeconfig did not parse to a mapping")

    contexts = {c["name"]: c["context"] for c in doc.get("contexts", []) if isinstance(c, dict) and "name" in c}
    if context_name not in contexts:
        raise KubernetesConfigError(f"context {context_name!r} not found in kubeconfig")
    ctx = contexts[context_name]
    cluster_name = ctx.get("cluster")
    user_name = ctx.get("user")

    clusters = {c["name"]: c["cluster"] for c in doc.get("clusters", []) if isinstance(c, dict) and "name" in c}
    users = {u["name"]: u["user"] for u in doc.get("users", []) if isinstance(u, dict) and "name" in u}

    cluster = clusters.get(cluster_name, {})
    user = users.get(user_name, {})

    server = cluster.get("server")
    if not isinstance(server, str) or not server:
        raise KubernetesConfigError(f"cluster {cluster_name!r} has no server URL in kubeconfig")

    return _ParsedAuth(
        server=server,
        ca_data=_b64(cluster.get("certificate-authority-data")),
        ca_file=cluster.get("certificate-authority"),
        client_cert_data=_b64(user.get("client-certificate-data")),
        client_cert_file=user.get("client-certificate"),
        client_key_data=_b64(user.get("client-key-data")),
        client_key_file=user.get("client-key"),
        token=user.get("token") if isinstance(user.get("token"), str) else None,
    )


def _write_private_file(dir_path: str, filename: str, content: bytes) -> str:
    path = os.path.join(dir_path, filename)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:  # fdopen takes ownership of fd; closed on exit, even on exception
        f.write(content)
    return path


@contextlib.contextmanager
def kubernetes_client_from_kubeconfig(
    kubeconfig_path: str,
    context_name: str,
    namespace: str,
    *,
    request_timeout: float = DEFAULT_TIMEOUT_SECONDS,
):
    """A context manager: builds a `KubernetesClient` from a real
    kubeconfig file, writing any certificate/key material to a
    private (0700 directory, 0600 files) temporary location that is
    ALWAYS removed when the `with` block exits, even on error. Never
    logs or re-raises the kubeconfig path's contents; `context_name`
    is REQUIRED (never silently defaults to "whatever is currently
    active"), so this can never accidentally target a different real
    cluster than the one explicitly named."""
    auth = _parse_kubeconfig(kubeconfig_path, context_name)
    temp_dir = tempfile.mkdtemp(prefix="k8s-observer-")
    try:
        os.chmod(temp_dir, 0o700)
        ca_path = None
        if auth.ca_data is not None:
            ca_path = _write_private_file(temp_dir, "ca.crt", auth.ca_data)
        elif auth.ca_file:
            ca_path = auth.ca_file

        cert_path = key_path = None
        if auth.client_cert_data is not None and auth.client_key_data is not None:
            cert_path = _write_private_file(temp_dir, "client.crt", auth.client_cert_data)
            key_path = _write_private_file(temp_dir, "client.key", auth.client_key_data)
        elif auth.client_cert_file and auth.client_key_file:
            cert_path, key_path = auth.client_cert_file, auth.client_key_file

        client = KubernetesClient(
            api_server_url=auth.server,
            namespace=namespace,
            ca_cert_path=ca_path,
            client_cert_path=cert_path,
            client_key_path=key_path,
            bearer_token=auth.token,
            request_timeout=request_timeout,
        )
        yield client
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
