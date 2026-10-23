"""Phase 14 FINAL VALIDATION round, Task 2: audit of the derived-
service-assertion design on investigator-service's own side -- unit
tests proving this service can never use its own signing ability to
produce a more privileged actor than the one it legitimately, already
verified from agent-runtime-service's relay; that the request-scoped
actor binding is correctly isolated across concurrent requests; and
that it is always cleaned up, even when the bound code raises.

See also tests/test_internal_service_auth.py (route-level: a relayed
assertion from an untrusted issuer/wrong audience/forged signature is
rejected even alongside the correct static caller token) and
tests/test_control_plane_client.py (client-level: a bound actor is
relayed as a further-derived assertion; no actor falls back to the
legacy static token).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from investigator_service.authz import (
    ActorContext,
    InvalidServiceAssertionError,
    bind_actor,
    current_actor,
    sign_derivative_assertion,
    verify_service_assertion,
)
from investigator_service.config import ServiceAssertionSettings

SETTINGS = ServiceAssertionSettings(
    secret="test-investigator-assertion-secret",
    trusted_issuers=frozenset({"agent-runtime-service"}),
    audience="investigator-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    retrieval_audience="retrieval-service",
)


def _relayed_token(**overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "org": "11111111-1111-1111-1111-111111111111",
        "role": "ENGINEER",
        "iss": "agent-runtime-service",
        "aud": "investigator-service",
        "iat": now,
        "exp": now + timedelta(seconds=15),
    }
    payload.update(overrides)
    return jwt.encode(payload, SETTINGS.secret, algorithm="HS256")


# ---------------------------------------------------------------------
# Scope/org/role/subject preservation across a SECOND hop of relaying
# (agent-runtime-service -> investigator-service -> control-plane).
# ---------------------------------------------------------------------


def test_a_further_derived_assertion_carries_the_identical_relayed_actor():
    relayed_actor = verify_service_assertion(_relayed_token(role="VIEWER"), SETTINGS)
    further_derived = sign_derivative_assertion(relayed_actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(further_derived, SETTINGS.secret, algorithms=["HS256"], audience="control-plane")
    assert payload["sub"] == relayed_actor.user_id
    assert payload["org"] == relayed_actor.organization_id
    assert payload["role"] == "VIEWER"  # never elevated across the second hop either
    assert payload["iss"] == "investigator-service"  # never "agent-runtime-service" -- no impersonation


def test_attempting_to_change_organization_across_the_second_relay_hop_is_not_possible():
    org_a = "11111111-1111-1111-1111-111111111111"
    relayed_actor = verify_service_assertion(_relayed_token(org=org_a), SETTINGS)
    further_derived = sign_derivative_assertion(relayed_actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(further_derived, SETTINGS.secret, algorithms=["HS256"], audience="control-plane")
    assert payload["org"] == org_a


def test_a_further_derived_assertion_cannot_be_reused_for_the_wrong_audience():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    token = sign_derivative_assertion(actor, SETTINGS, audience="control-plane")
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token, SETTINGS.secret, algorithms=["HS256"], audience="some-other-service")


def test_signing_without_a_configured_secret_fails_closed():
    unconfigured = ServiceAssertionSettings(
        secret=None,
        trusted_issuers=frozenset({"agent-runtime-service"}),
        audience="investigator-service",
        max_clock_skew_seconds=5,
        control_plane_audience="control-plane",
        retrieval_audience="retrieval-service",
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    with pytest.raises(InvalidServiceAssertionError):
        sign_derivative_assertion(actor, unconfigured, audience="control-plane")


# ---------------------------------------------------------------------
# Absent actor context / contextvar cleanup.
# ---------------------------------------------------------------------


def test_current_actor_is_none_outside_any_bind_actor_block():
    assert current_actor() is None


def test_bind_actor_cleans_up_even_when_the_bound_code_raises():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    with pytest.raises(RuntimeError):
        with bind_actor(actor):
            assert current_actor() is actor
            raise RuntimeError("simulated failure deep inside a bound request")
    assert current_actor() is None


# ---------------------------------------------------------------------
# Concurrent actors from different organizations, relayed from two
# different upstream agent-runtime-service requests at the same time.
# ---------------------------------------------------------------------


async def test_concurrent_requests_from_different_organizations_never_cross_contaminate():
    org_a_actor = ActorContext(user_id="alice", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    org_b_actor = ActorContext(user_id="bob", organization_id="22222222-2222-2222-2222-222222222222", role="OWNER")
    observed: dict[str, list[ActorContext | None]] = {"a": [], "b": []}

    async def simulate_request(key: str, actor: ActorContext) -> None:
        with bind_actor(actor):
            for _ in range(5):
                await asyncio.sleep(0)
                observed[key].append(current_actor())

    await asyncio.gather(
        simulate_request("a", org_a_actor),
        simulate_request("b", org_b_actor),
    )

    assert all(actor is org_a_actor for actor in observed["a"])
    assert all(actor is org_b_actor for actor in observed["b"])
    assert current_actor() is None
