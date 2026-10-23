"""Phase 14 correction round, Issue 2/3: real-request-level proof that
POST /api/v1/investigations rejects a direct, unauthenticated call
once secure mode is enabled -- the "a direct HTTP call bypasses the
frontend/agent-runtime-service" gap the independent review flagged.

Phase 14 correction round, Blocker 1 (additive section at the bottom
of this file): proof that a relayed X-Service-Assertion, if PRESENT,
is independently verified -- never silently trusted alongside a
correct static token, and never silently dropped if invalid.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from investigator_service.config import (
    InternalServiceTokenSettings,
    OrganizationContextSettings,
    ServiceAssertionSettings,
)
from investigator_service.main import app
from tests.conftest import SAMPLE_INCIDENT_ID

AGENT_RUNTIME_TOKEN = "test-investigator-caller-token"
ASSERTION_SECRET = "test-investigator-relay-secret"


@pytest.fixture
def secure_client():
    with TestClient(app) as client:
        previous_org_settings = app.state.organization_context_settings
        previous_tokens = app.state.internal_service_tokens
        previous_assertion_settings = app.state.service_assertion_settings
        app.state.organization_context_settings = OrganizationContextSettings(enabled=True)
        app.state.internal_service_tokens = InternalServiceTokenSettings(
            agent_runtime_caller_token=AGENT_RUNTIME_TOKEN,
            control_plane_token="unused",
            retrieval_token="unused",
        )
        new_assertion_settings = ServiceAssertionSettings(
            secret=ASSERTION_SECRET,
            trusted_issuers=frozenset({"agent-runtime-service"}),
            audience="investigator-service",
            max_clock_skew_seconds=5,
            control_plane_audience="control-plane",
        retrieval_audience="retrieval-service",
        )
        app.state.service_assertion_settings = new_assertion_settings
        # The control-plane client captured its OWN copy of settings at
        # app-startup construction time (a frozen dataclass VALUE, not
        # a live app.state reference) -- must be updated too, or a test
        # that reaches investigate()'s real downstream get_incident()
        # call would sign with the startup-time (unconfigured) secret
        # instead of this test's.
        previous_client_assertion_settings = app.state.control_plane_client._service_assertion_settings
        app.state.control_plane_client._service_assertion_settings = new_assertion_settings
        yield client
        app.state.organization_context_settings = previous_org_settings
        app.state.internal_service_tokens = previous_tokens
        app.state.service_assertion_settings = previous_assertion_settings
        app.state.control_plane_client._service_assertion_settings = previous_client_assertion_settings


def _relayed_assertion(*, iss: str = "agent-runtime-service", aud: str = "investigator-service", **overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "org": "11111111-1111-1111-1111-111111111111",
        "role": "ENGINEER",
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + timedelta(seconds=15),
    }
    payload.update(overrides)
    return jwt.encode(payload, ASSERTION_SECRET, algorithm="HS256")


def test_direct_unauthenticated_call_is_rejected_when_secure_mode_is_on(secure_client):
    response = secure_client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
    assert response.status_code == 401


def test_wrong_internal_token_is_rejected(secure_client):
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": "not-the-real-token"},
    )
    assert response.status_code == 401


def test_agent_runtimes_own_token_is_accepted(secure_client):
    # The request still reaches the real investigator/provider
    # pipeline past the auth gate -- a 503 here (no LLM configured in
    # this test env) PROVES the auth check itself passed, as opposed
    # to a 401 which would mean it didn't.
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN},
    )
    assert response.status_code != 401


def test_unconfigured_caller_token_fails_closed_even_with_enforcement_on():
    with TestClient(app) as client:
        previous_org_settings = app.state.organization_context_settings
        previous_tokens = app.state.internal_service_tokens
        app.state.organization_context_settings = OrganizationContextSettings(enabled=True)
        app.state.internal_service_tokens = InternalServiceTokenSettings(
            agent_runtime_caller_token=None, control_plane_token="unused", retrieval_token="unused"
        )
        try:
            response = client.post(
                "/api/v1/investigations",
                json={"incident_id": str(SAMPLE_INCIDENT_ID)},
                headers={"X-Internal-Service-Token": "anything"},
            )
            assert response.status_code == 401
        finally:
            app.state.organization_context_settings = previous_org_settings
            app.state.internal_service_tokens = previous_tokens


def test_disabled_enforcement_preserves_pre_phase14_unauthenticated_behavior():
    # The default (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT unset) --
    # must behave EXACTLY as before this correction round: no token
    # required at all, never a 401 from this gate.
    with TestClient(app) as client:
        response = client.post("/api/v1/investigations", json={"incident_id": str(SAMPLE_INCIDENT_ID)})
        assert response.status_code != 401


# ---------------------------------------------------------------------
# Phase 14 correction round, BLOCKER 1: the relayed X-Service-Assertion
# is additive -- require_internal_caller's own static-token gate above
# is completely unaffected either way -- but an assertion that IS
# presented is independently, cryptographically verified, and a
# present-but-invalid one is always rejected, never silently dropped.
# ---------------------------------------------------------------------


def test_a_relayed_assertion_from_an_untrusted_issuer_is_rejected_even_with_the_correct_static_token(secure_client):
    forged = _relayed_assertion(iss="some-random-service-nobody-configured")
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN, "X-Service-Assertion": forged},
    )
    assert response.status_code == 401


def test_a_relayed_assertion_with_the_wrong_audience_is_rejected_even_with_the_correct_static_token(secure_client):
    wrong_audience = _relayed_assertion(aud="control-plane")
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN, "X-Service-Assertion": wrong_audience},
    )
    assert response.status_code == 401


def test_a_forged_relayed_assertion_signature_is_rejected_even_with_the_correct_static_token(secure_client):
    tampered = _relayed_assertion() + "tampered"
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN, "X-Service-Assertion": tampered},
    )
    assert response.status_code == 401


def test_a_valid_relayed_assertion_alongside_the_correct_static_token_passes_the_auth_gate(secure_client):
    # Reaches the real investigator pipeline past BOTH checks -- a 503
    # here (no LLM configured in this test env) proves auth passed,
    # same discipline as test_agent_runtimes_own_token_is_accepted.
    valid = _relayed_assertion()
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN, "X-Service-Assertion": valid},
    )
    assert response.status_code != 401


def test_no_relayed_assertion_at_all_still_passes_with_just_the_static_token(secure_client):
    # The assertion is additive, never required by require_internal_caller
    # itself -- a legacy/local-dev caller presenting only the static
    # token (no assertion) is unaffected.
    response = secure_client.post(
        "/api/v1/investigations",
        json={"incident_id": str(SAMPLE_INCIDENT_ID)},
        headers={"X-Internal-Service-Token": AGENT_RUNTIME_TOKEN},
    )
    assert response.status_code != 401
