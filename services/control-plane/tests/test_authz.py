"""Phase 14 Gate 5/10: unit tests for core/authz.py's service-assertion
verification -- pure function tests, no FastAPI app/client needed at
all. See test_organization_scoping.py for the real-request-level
tenant-isolation/RBAC negative controls this module's verified
ActorContext feeds into.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from control_plane.core.authz import InvalidServiceAssertionError, verify_service_assertion
from control_plane.core.config import ServiceAssertionSettings

SETTINGS = ServiceAssertionSettings(
    secret="test-service-assertion-secret",
    trusted_issuers=frozenset({"web-console", "agent-runtime-service", "investigator-service"}),
    audience="control-plane",
    max_clock_skew_seconds=5,
)


SAMPLE_ORG_ID = "11111111-1111-1111-1111-111111111111"


def _make_token(**overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "org": SAMPLE_ORG_ID,
        "role": "OWNER",
        "iss": "web-console",
        "aud": "control-plane",
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }
    payload.update(overrides)
    return jwt.encode(payload, SETTINGS.secret, algorithm="HS256")


def test_a_validly_signed_assertion_is_accepted_and_fields_round_trip():
    token = _make_token()
    actor = verify_service_assertion(token, SETTINGS)
    assert actor.user_id == "user-1"
    assert actor.organization_id == SAMPLE_ORG_ID
    assert actor.role == "OWNER"


def test_no_secret_configured_is_rejected():
    unconfigured = ServiceAssertionSettings(
        secret=None, trusted_issuers=frozenset({"web-console"}), audience="control-plane", max_clock_skew_seconds=5
    )
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(_make_token(), unconfigured)


def test_wrong_signing_secret_is_rejected():
    token = jwt.encode(
        {
            "sub": "user-1",
            "org": "org-1",
            "role": "OWNER",
            "iss": "web-console",
            "aud": "control-plane",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(seconds=60),
        },
        "a-completely-different-secret",
        algorithm="HS256",
    )
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_wrong_audience_is_rejected():
    # Simulates an assertion minted for agent-runtime-service being
    # replayed against control-plane -- Gate 5/6: an assertion for one
    # backend must not be valid for a different one.
    token = _make_token(aud="agent-runtime-service")
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_wrong_issuer_is_rejected():
    token = _make_token(iss="some-other-service")
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_an_assertion_relayed_by_a_trusted_internal_service_is_accepted():
    # Phase 14 correction round, Blocker 1: agent-runtime-service and
    # investigator-service mint DERIVED assertions (for the exact
    # actor they themselves already verified) when forwarding a
    # tenant-scoped read -- this is a real, different issuer, but
    # still a TRUSTED one, and the cryptographic signature is
    # verified identically either way.
    token = _make_token(iss="agent-runtime-service")
    actor = verify_service_assertion(token, SETTINGS)
    assert actor.issued_by == "agent-runtime-service"


def test_an_assertion_from_an_untrusted_issuer_is_rejected_even_with_a_valid_signature():
    # The signature alone is never sufficient -- only a name in the
    # configured trusted-issuer allowlist may relay an assertion.
    token = _make_token(iss="some-random-service-nobody-configured")
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_expired_assertion_is_rejected():
    now = datetime.now(UTC)
    token = _make_token(iat=now - timedelta(seconds=120), exp=now - timedelta(seconds=60))
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_unrecognized_role_is_rejected():
    token = _make_token(role="SUPERUSER")
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_non_uuid_organization_claim_is_rejected():
    # Phase 14 correction round, Issue 1: Better Auth's organization
    # id is now a real UUID (generateId: "uuid"), and
    # reliability.incidents.organization_id is a native Postgres UUID
    # column -- a syntactically invalid value here must never reach a
    # SQL query at all.
    token = _make_token(org="not-a-uuid")
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_organization_claim_is_normalized_to_canonical_uuid_form():
    # Accepts an equivalent, differently-cased/formatted UUID string
    # and normalizes it -- so a comparison against a value read back
    # from Postgres (which always returns the canonical lowercase
    # hyphenated form) can never spuriously mismatch.
    token = _make_token(org=SAMPLE_ORG_ID.upper())
    actor = verify_service_assertion(token, SETTINGS)
    assert actor.organization_id == SAMPLE_ORG_ID


def test_missing_required_claim_is_rejected():
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "user-1", "iss": "web-console", "aud": "control-plane", "iat": now, "exp": now + timedelta(seconds=60)},
        SETTINGS.secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(token, SETTINGS)


def test_unsigned_none_algorithm_token_is_rejected():
    # A classic JWT attack: an attacker-crafted token using alg=none,
    # claiming to need no signature at all. PyJWT's own `algorithms=`
    # pin (never reading "alg" from the token's own header) is what
    # defeats this.
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "attacker",
            "org": "org-1",
            "role": "OWNER",
            "iss": "web-console",
            "aud": "control-plane",
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidServiceAssertionError):
        verify_service_assertion(forged, SETTINGS)
