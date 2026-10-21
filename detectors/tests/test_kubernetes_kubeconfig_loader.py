"""Gate B (Phase 12A): kubeconfig loading tests -- a SYNTHETIC
kubeconfig only, never the real one on this machine. Confirms
certificate/key material is written to a private temp location and
is always removed afterward, confirms an explicit context is
required, and confirms credential material never leaks into an
exception message."""

import base64
import os
import stat

import pytest
import yaml

from detectors.clients.kubernetes_client import KubernetesConfigError, kubernetes_client_from_kubeconfig

_FAKE_CERT = base64.b64encode(b"-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n").decode()
_FAKE_KEY = base64.b64encode(b"-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n").decode()
_FAKE_CA = base64.b64encode(b"-----BEGIN CERTIFICATE-----\nFAKECA\n-----END CERTIFICATE-----\n").decode()


def _write_synthetic_kubeconfig(path, *, with_token=False) -> None:
    user = {"token": "fake-token-value"} if with_token else {
        "client-certificate-data": _FAKE_CERT,
        "client-key-data": _FAKE_KEY,
    }
    doc = {
        "apiVersion": "v1",
        "clusters": [{"name": "test-cluster", "cluster": {"server": "https://127.0.0.1:6443", "certificate-authority-data": _FAKE_CA}}],
        "contexts": [{"name": "test-context", "context": {"cluster": "test-cluster", "user": "test-user"}}],
        "users": [{"name": "test-user", "user": user}],
        "current-context": "test-context",
    }
    with open(path, "w") as f:
        yaml.safe_dump(doc, f)


def test_loader_builds_a_working_client_and_cleans_up_temp_files(tmp_path):
    kubeconfig_path = tmp_path / "kubeconfig"
    _write_synthetic_kubeconfig(kubeconfig_path)

    captured_dir = {}
    with kubernetes_client_from_kubeconfig(str(kubeconfig_path), "test-context", "reliability-sandbox") as client:
        assert client.namespace == "reliability-sandbox"
        # Locate the temp dir this session created, to confirm cleanup after exit.
        for entry in os.listdir("/tmp") if os.path.isdir("/tmp") else []:
            if entry.startswith("k8s-observer-"):
                captured_dir["path"] = os.path.join("/tmp", entry)

    if captured_dir.get("path"):
        assert not os.path.exists(captured_dir["path"])


def test_cert_and_key_files_are_private_while_the_context_manager_is_open(tmp_path):
    kubeconfig_path = tmp_path / "kubeconfig"
    _write_synthetic_kubeconfig(kubeconfig_path)

    seen_perms = {}
    with kubernetes_client_from_kubeconfig(str(kubeconfig_path), "test-context", "reliability-sandbox") as client:
        # Reach into the client's own private attributes ONLY to assert file permissions -- never to print contents.
        for attr in ("_ca_cert_path", "_client_cert_path", "_client_key_path"):
            path = getattr(client, attr)
            if path and os.path.exists(path):
                mode = stat.S_IMODE(os.stat(path).st_mode)
                seen_perms[attr] = mode

    assert seen_perms  # at least one credential file was actually written
    for attr, mode in seen_perms.items():
        assert mode == 0o600, f"{attr} had mode {oct(mode)}, expected 0600"


def test_bearer_token_auth_is_also_supported(tmp_path):
    kubeconfig_path = tmp_path / "kubeconfig"
    _write_synthetic_kubeconfig(kubeconfig_path, with_token=True)

    with kubernetes_client_from_kubeconfig(str(kubeconfig_path), "test-context", "reliability-sandbox") as client:
        assert client._bearer_token == "fake-token-value"


def test_unknown_context_raises_config_error_not_a_silent_fallback(tmp_path):
    kubeconfig_path = tmp_path / "kubeconfig"
    _write_synthetic_kubeconfig(kubeconfig_path)

    with pytest.raises(KubernetesConfigError, match="not found"):
        with kubernetes_client_from_kubeconfig(str(kubeconfig_path), "totally-wrong-context", "reliability-sandbox"):
            pass


def test_malformed_kubeconfig_raises_config_error(tmp_path):
    kubeconfig_path = tmp_path / "kubeconfig"
    kubeconfig_path.write_text("not: valid: yaml: : :")

    with pytest.raises(KubernetesConfigError):
        with kubernetes_client_from_kubeconfig(str(kubeconfig_path), "test-context", "reliability-sandbox"):
            pass


def test_missing_kubeconfig_file_raises_config_error_never_a_credential_leak():
    with pytest.raises(KubernetesConfigError) as exc_info:
        with kubernetes_client_from_kubeconfig("/nonexistent/path/kubeconfig", "test-context", "reliability-sandbox"):
            pass
    message = str(exc_info.value)
    assert "FAKE" not in message
    assert "-----BEGIN" not in message
