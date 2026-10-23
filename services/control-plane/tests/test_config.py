"""Unit tests for the Phase 3D post-review correction (extended in
Phase 8 to all five write-endpoint tokens): identical tokens must never
authorize two different write endpoints.

Two layers are tested:

- `resolve_write_tokens` (core/config.py) as a pure function — no
  FastAPI app, no HTTP, no repository at all. Phase 8 widened this
  from a 2-token to a 5-token pairwise check (webhook, lifecycle,
  remediation proposal/approver/executor).
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


def test_resolve_write_tokens_returns_all_unchanged_when_distinct():
    assert resolve_write_tokens(
        "webhook-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value", "k8s-value", "aws-value"
    ) == (
        "webhook-value",
        "lifecycle-value",
        "proposal-value",
        "approver-value",
        "executor-value",
        "k8s-value",
        "aws-value",
        None,
        None,
        None,
    )


def test_resolve_write_tokens_returns_both_none_when_identical():
    assert resolve_write_tokens("same-value", "same-value") == (None, None, None, None, None, None, None, None, None, None)


def test_resolve_write_tokens_preserves_one_unconfigured_token():
    # Exactly one token being unconfigured (None) must be unaffected —
    # it continues to fail closed only for its own endpoint, same as
    # before this guard existed.
    assert resolve_write_tokens(None, "lifecycle-value") == (
        None, "lifecycle-value", None, None, None, None, None, None, None, None,
    )
    assert resolve_write_tokens("webhook-value", None) == (
        "webhook-value", None, None, None, None, None, None, None, None, None,
    )


def test_resolve_write_tokens_both_unconfigured_stays_both_none():
    assert resolve_write_tokens(None, None) == (None, None, None, None, None, None, None, None, None, None)


def test_resolve_write_tokens_clears_only_the_colliding_pair():
    # Phase 8: the pairwise check must clear ONLY the two tokens that
    # actually collide, leaving every other distinct token untouched —
    # never a blanket "any collision anywhere clears everything".
    result = resolve_write_tokens("webhook-value", "lifecycle-value", "same-value", "same-value", "executor-value")
    assert result == ("webhook-value", "lifecycle-value", None, None, "executor-value", None, None, None, None, None)


def test_resolve_write_tokens_remediation_tokens_cannot_collide_with_webhook_or_lifecycle():
    # A remediation token accidentally set equal to the EXISTING
    # webhook/lifecycle token must also fail closed — not just
    # collisions among the three new tokens themselves.
    result = resolve_write_tokens("same-value", "lifecycle-value", "same-value", "approver-value", "executor-value")
    assert result == (None, "lifecycle-value", None, "approver-value", "executor-value", None, None, None, None, None)


def test_resolve_write_tokens_kubernetes_ingestion_token_cannot_collide_with_any_other():
    # Phase 12B-D: the sixth token (Kubernetes finding ingestion) must
    # be caught by the exact same pairwise guard as every other one —
    # colliding with the webhook token here, but the guard is pairwise
    # over all six, not special-cased.
    result = resolve_write_tokens(
        "same-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value", "same-value"
    )
    assert result == (
        None, "lifecycle-value", "proposal-value", "approver-value", "executor-value", None, None, None, None, None,
    )


def test_resolve_write_tokens_aws_ingestion_token_cannot_collide_with_any_other():
    # Phase 13: the seventh token (AWS finding ingestion) must be
    # caught by the exact same pairwise guard as every other one --
    # including the Kubernetes ingestion token specifically (Gate 4's
    # own explicit "do not reuse the Kubernetes ingestion token"
    # requirement -- this proves that even an ACCIDENTAL collision
    # between the two is still caught, not merely that they default to
    # different literal values).
    result = resolve_write_tokens(
        "webhook-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value",
        "same-value", "same-value",
    )
    assert result == (
        "webhook-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value",
        None, None, None, None, None,
    )


def test_resolve_write_tokens_internal_read_tokens_cannot_collide_with_each_other():
    # Phase 14 correction round, Issue 3: the three NEW internal
    # read-only service identities join the same pairwise guard.
    result = resolve_write_tokens(
        "webhook-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value",
        "k8s-value", "aws-value",
        "same-internal-value", "same-internal-value", "tool-gateway-value",
    )
    assert result == (
        "webhook-value", "lifecycle-value", "proposal-value", "approver-value", "executor-value",
        "k8s-value", "aws-value",
        None, None, "tool-gateway-value",
    )


def test_resolve_write_tokens_internal_read_token_cannot_collide_with_an_existing_write_token():
    # An internal read-only credential must never silently double as
    # the human remediation-approver token (or any other existing
    # write-capable token) if misconfigured to the same value.
    result = resolve_write_tokens(
        "webhook-value", "lifecycle-value", "proposal-value", "same-value", "executor-value",
        "k8s-value", "aws-value",
        "same-value", "investigator-value", "tool-gateway-value",
    )
    assert result == (
        "webhook-value", "lifecycle-value", "proposal-value", None, "executor-value",
        "k8s-value", "aws-value",
        None, "investigator-value", "tool-gateway-value",
    )


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
