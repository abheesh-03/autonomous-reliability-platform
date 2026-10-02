"""Unit tests for the Phase 3D post-review correction: identical
webhook/lifecycle tokens must never authorize either write endpoint.

Two layers are tested:

- `resolve_write_tokens` (core/config.py) as a pure function — no
  FastAPI app, no HTTP, no repository at all.
- The end-to-end guard actually wired into app startup (main.py's
  lifespan): a fresh TestClient, started with both tokens set
  identically via the real environment (simulating an operator
  hand-editing .env, or setting these variables directly, bypassing
  scripts/init-webhook-secret.sh's own refusal entirely), must fail
  closed on both write endpoints.
"""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from control_plane.api.dependencies import get_incident_repository
from control_plane.core.config import resolve_write_tokens
from control_plane.main import app
from tests.conftest import FakeIncidentRepository

# ---------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------


def test_resolve_write_tokens_returns_both_unchanged_when_distinct():
    assert resolve_write_tokens("webhook-value", "lifecycle-value") == ("webhook-value", "lifecycle-value")


def test_resolve_write_tokens_returns_both_none_when_identical():
    assert resolve_write_tokens("same-value", "same-value") == (None, None)


def test_resolve_write_tokens_preserves_one_unconfigured_token():
    # Exactly one token being unconfigured (None) must be unaffected —
    # it continues to fail closed only for its own endpoint, same as
    # before this guard existed.
    assert resolve_write_tokens(None, "lifecycle-value") == (None, "lifecycle-value")
    assert resolve_write_tokens("webhook-value", None) == ("webhook-value", None)


def test_resolve_write_tokens_both_unconfigured_stays_both_none():
    assert resolve_write_tokens(None, None) == (None, None)


# ---------------------------------------------------------------------
# End-to-end: the guard as actually wired into app startup
# ---------------------------------------------------------------------


def test_identical_tokens_configured_directly_fail_both_endpoints_closed(monkeypatch):
    # Simulates an operator configuring CONTROL_PLANE_WEBHOOK_TOKEN and
    # CONTROL_PLANE_LIFECYCLE_TOKEN to the SAME value directly (hand-
    # editing .env, or any other mechanism), bypassing
    # scripts/init-webhook-secret.sh's own refusal to ever produce this
    # combination entirely. The application-level guard
    # (resolve_write_tokens, called from main.py's lifespan) must still
    # catch it at startup — real "starting the service without the
    # initializer cannot bypass this protection", not merely the
    # initializer refusing to write such a .env in the first place.
    monkeypatch.setenv("CONTROL_PLANE_WEBHOOK_TOKEN", "identical-token-value")
    monkeypatch.setenv("CONTROL_PLANE_LIFECYCLE_TOKEN", "identical-token-value")

    with TestClient(app) as fresh_client:
        app.dependency_overrides[get_incident_repository] = lambda: FakeIncidentRepository([])
        try:
            patch_response = fresh_client.patch(
                f"/api/v1/incidents/{uuid.uuid4()}/status",
                headers={"Authorization": "Bearer identical-token-value"},
                json={"expected_status": "open", "target_status": "acknowledged"},
            )
            webhook_response = fresh_client.post(
                "/internal/v1/alertmanager/webhook",
                headers={"Authorization": "Bearer identical-token-value"},
                json={
                    "version": "4",
                    "groupKey": "x",
                    "status": "firing",
                    "receiver": "y",
                    "alerts": [
                        {
                            "status": "firing",
                            "labels": {"alertname": "X", "severity": "critical"},
                            "annotations": {},
                            "startsAt": datetime.now(UTC).isoformat(),
                            "fingerprint": "fp-identical-token-test",
                        }
                    ],
                },
            )
            # The read API must remain completely unaffected — this
            # guard must never "break the read API" per its own
            # requirement.
            read_response = fresh_client.get("/api/v1/incidents")
        finally:
            app.dependency_overrides.clear()

    assert patch_response.status_code == 401
    assert webhook_response.status_code == 401
    assert read_response.status_code == 200
    assert "identical-token-value" not in patch_response.text
    assert "identical-token-value" not in webhook_response.text
