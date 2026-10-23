"""Phase 14 correction round, Issue 2/3: real-request-level proof that
POST /api/v1/retrieval/search rejects a direct, unauthenticated call
once secure mode is enabled -- the "a direct HTTP call bypasses
investigator-service" gap the independent review flagged. Mirrors
investigator-service's own tests/test_internal_service_auth.py.

Builds a minimal bare FastAPI app (same convention
agent-runtime-service's tests/test_api_agent_runs.py already uses)
rather than running retrieval-service's own real `lifespan`, which
eagerly opens a REAL PostgreSQL connection pool at startup -- these
tests only exercise the `require_internal_caller` auth gate, which
runs BEFORE the route body ever touches the database.

Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A
(additive section at the bottom): proof that a relayed
X-Service-Assertion, if PRESENT, is independently, cryptographically
verified -- never silently trusted alongside a correct static token,
and never silently dropped if invalid. The actual tenant-scope
DECISION this assertion feeds into (search.py's own
_resolve_historical_organization_scope) is unit-tested directly in
tests/test_search_tenant_scope.py and proven against a real database
by scripts/retrieval_tenant_isolation_check.py -- this file only
proves the auth GATE's own pass/fail (these tests use a fake pool
that can never return real historical content either way).
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrieval_service.api.search import router as search_router
from retrieval_service.config import (
    InternalCallerTokenSettings,
    OrganizationContextSettings,
    SearchBounds,
    ServiceAssertionSettings,
)
from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider

INVESTIGATOR_TOKEN = "test-retrieval-caller-token"
ASSERTION_SECRET = "test-retrieval-relay-secret"

_UNCONFIGURED_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret=None, trusted_issuers=frozenset({"investigator-service"}), audience="retrieval-service", max_clock_skew_seconds=5
)
_REAL_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret=ASSERTION_SECRET,
    trusted_issuers=frozenset({"investigator-service"}),
    audience="retrieval-service",
    max_clock_skew_seconds=5,
)


class _FakePool:
    """A real query would need a real database; these tests only
    care whether the request got PAST the auth gate at all (never a
    full search result), so an empty result set is sufficient."""

    async def fetch(self, *args, **kwargs):
        return []


def _build_app(
    *, enabled: bool, caller_token: str | None, assertion_settings: ServiceAssertionSettings | None = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(search_router)
    app.state.pool = _FakePool()
    app.state.embedding_provider = LocalLexicalEmbeddingProvider()
    app.state.search_bounds = SearchBounds.from_env()
    app.state.organization_context_settings = OrganizationContextSettings(enabled=enabled)
    app.state.internal_caller_token_settings = InternalCallerTokenSettings(investigator_caller_token=caller_token)
    app.state.service_assertion_settings = assertion_settings or _UNCONFIGURED_ASSERTION_SETTINGS
    return app


def _relayed_assertion(*, iss: str = "investigator-service", aud: str = "retrieval-service", **overrides) -> str:
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


@pytest.fixture
def secure_client():
    return TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN))


def test_direct_unauthenticated_call_is_rejected_when_secure_mode_is_on(secure_client):
    response = secure_client.post("/api/v1/retrieval/search", json={"query": "checkout errors"})
    assert response.status_code == 401


def test_wrong_internal_token_is_rejected(secure_client):
    response = secure_client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": "not-the-real-token"},
    )
    assert response.status_code == 401


def test_investigators_own_token_is_accepted(secure_client):
    response = secure_client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN},
    )
    assert response.status_code == 200


def test_unconfigured_caller_token_fails_closed_even_with_enforcement_on():
    client = TestClient(_build_app(enabled=True, caller_token=None))
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": "anything"},
    )
    assert response.status_code == 401


def test_disabled_enforcement_preserves_pre_phase14_unauthenticated_behavior():
    client = TestClient(_build_app(enabled=False, caller_token=None))
    response = client.post("/api/v1/retrieval/search", json={"query": "checkout errors"})
    assert response.status_code == 200


# ---------------------------------------------------------------------
# Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A: the
# relayed assertion is additive at THIS gate (require_internal_caller
# is unaffected either way) -- but one that IS presented is always
# independently verified.
# ---------------------------------------------------------------------


def test_a_relayed_assertion_from_an_untrusted_issuer_is_rejected_even_with_the_correct_static_token():
    client = TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN, assertion_settings=_REAL_ASSERTION_SETTINGS))
    forged = _relayed_assertion(iss="some-random-service-nobody-configured")
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN, "X-Service-Assertion": forged},
    )
    assert response.status_code == 401


def test_a_relayed_assertion_with_the_wrong_audience_is_rejected_even_with_the_correct_static_token():
    client = TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN, assertion_settings=_REAL_ASSERTION_SETTINGS))
    wrong_audience = _relayed_assertion(aud="control-plane")
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN, "X-Service-Assertion": wrong_audience},
    )
    assert response.status_code == 401


def test_a_forged_relayed_assertion_signature_is_rejected_even_with_the_correct_static_token():
    client = TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN, assertion_settings=_REAL_ASSERTION_SETTINGS))
    tampered = _relayed_assertion() + "tampered"
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN, "X-Service-Assertion": tampered},
    )
    assert response.status_code == 401


def test_a_valid_relayed_assertion_alongside_the_correct_static_token_passes_the_auth_gate():
    client = TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN, assertion_settings=_REAL_ASSERTION_SETTINGS))
    valid = _relayed_assertion()
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN, "X-Service-Assertion": valid},
    )
    assert response.status_code == 200


def test_no_relayed_assertion_at_all_still_passes_this_gate_with_just_the_static_token():
    # Additive, never required by require_internal_caller itself --
    # the TENANT-SCOPE decision (tested separately) is what actually
    # requires the assertion for historical results specifically.
    client = TestClient(_build_app(enabled=True, caller_token=INVESTIGATOR_TOKEN, assertion_settings=_REAL_ASSERTION_SETTINGS))
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "checkout errors"},
        headers={"X-Internal-Service-Token": INVESTIGATOR_TOKEN},
    )
    assert response.status_code == 200
