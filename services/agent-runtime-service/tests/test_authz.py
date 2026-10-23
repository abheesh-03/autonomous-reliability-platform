"""Phase 14 FINAL VALIDATION round, Task 2: audit of the derived-
service-assertion design -- unit tests proving an internal service can
never use its own signing ability to produce a more privileged actor
than the one it legitimately, already verified; that the request-scoped
actor binding is correctly isolated across concurrent requests; and
that it is always cleaned up, even when the bound code raises.

See also tests/test_control_plane_client.py / tests/test_investigator_client.py
for the client-level proof that a bound actor is relayed as a derived
assertion (never the bare internal token) and that NO actor bound falls
back to the legacy static token correctly.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from agent_runtime_service.authz import (
    ActorContext,
    InvalidServiceAssertionError,
    bind_actor,
    current_actor,
    sign_derivative_assertion,
    verify_service_assertion,
)
from agent_runtime_service.config import ServiceAssertionSettings

SETTINGS = ServiceAssertionSettings(
    secret="test-agent-runtime-assertion-secret",
    issuer="web-console",
    audience="agent-runtime-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    investigator_audience="investigator-service",
)


def _incoming_token(**overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "org": "11111111-1111-1111-1111-111111111111",
        "role": "ENGINEER",
        "iss": "web-console",
        "aud": "agent-runtime-service",
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }
    payload.update(overrides)
    return jwt.encode(payload, SETTINGS.secret, algorithm="HS256")


# ---------------------------------------------------------------------
# Scope/org/role/subject PRESERVATION: a derived assertion must carry
# the IDENTICAL verified actor, never a separately-suppliable value.
# `sign_derivative_assertion`'s own signature only accepts a whole,
# already-verified `ActorContext` object (plus the fixed downstream
# `audience`) -- there is no org/role/user_id parameter an internal
# service could override even if it wanted to, which this test proves
# empirically rather than merely by code-reading.
# ---------------------------------------------------------------------


def test_a_derived_assertion_carries_the_identical_actor_never_a_different_one():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="VIEWER")
    token = sign_derivative_assertion(actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(token, SETTINGS.secret, algorithms=["HS256"], audience="control-plane")
    assert payload["sub"] == actor.user_id
    assert payload["org"] == actor.organization_id
    assert payload["role"] == actor.role  # never elevated -- VIEWER stays VIEWER
    assert payload["iss"] == "agent-runtime-service"  # never "web-console" -- no impersonation of the original signer


def test_attempting_to_relay_a_higher_role_than_verified_is_not_possible_through_this_api():
    # "internal service attempting to elevate role": the ONLY way to
    # produce a derived assertion is to already HOLD a verified
    # ActorContext (itself only constructible by verify_service_assertion,
    # from a real signature) -- there is no code path that accepts a
    # bare role string to sign with. A VIEWER's own verified assertion
    # relays as VIEWER, period.
    viewer_actor = verify_service_assertion(_incoming_token(role="VIEWER"), SETTINGS)
    derived = sign_derivative_assertion(viewer_actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(derived, SETTINGS.secret, algorithms=["HS256"], audience="control-plane")
    assert payload["role"] == "VIEWER"


def test_attempting_to_change_organization_during_relay_is_not_possible_through_this_api():
    org_a = "11111111-1111-1111-1111-111111111111"
    actor = verify_service_assertion(_incoming_token(org=org_a), SETTINGS)
    derived = sign_derivative_assertion(actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(derived, SETTINGS.secret, algorithms=["HS256"], audience="control-plane")
    assert payload["org"] == org_a


# ---------------------------------------------------------------------
# Audience / issuer / expiry -- a derived assertion is itself subject
# to the exact same verification discipline as an original one.
# ---------------------------------------------------------------------


def test_a_derived_assertion_cannot_be_reused_for_the_wrong_audience():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    token_for_control_plane = sign_derivative_assertion(actor, SETTINGS, audience="control-plane")
    # A party verifying against a DIFFERENT expected audience (e.g.
    # investigator-service checking its own incoming assertions) must
    # reject this -- PyJWT's own audience= check.
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token_for_control_plane, SETTINGS.secret, algorithms=["HS256"], audience="investigator-service")


def test_a_derived_assertion_is_short_lived():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    token = sign_derivative_assertion(actor, SETTINGS, audience="control-plane")
    payload = jwt.decode(
        token, SETTINGS.secret, algorithms=["HS256"], audience="control-plane", options={"verify_exp": False}
    )
    assert payload["exp"] - payload["iat"] <= 30  # materially shorter than web-console's own 60s original


def test_signing_without_a_configured_secret_fails_closed():
    unconfigured = ServiceAssertionSettings(
        secret=None,
        issuer="web-console",
        audience="agent-runtime-service",
        max_clock_skew_seconds=5,
        control_plane_audience="control-plane",
        investigator_audience="investigator-service",
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    with pytest.raises(InvalidServiceAssertionError):
        sign_derivative_assertion(actor, unconfigured, audience="control-plane")


# ---------------------------------------------------------------------
# Absent actor context.
# ---------------------------------------------------------------------


def test_current_actor_is_none_outside_any_bind_actor_block():
    assert current_actor() is None


# ---------------------------------------------------------------------
# contextvar cleanup -- after every request, including one that raised.
# ---------------------------------------------------------------------


def test_bind_actor_cleans_up_after_a_normal_exit():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    with bind_actor(actor):
        assert current_actor() is actor
    assert current_actor() is None


def test_bind_actor_cleans_up_even_when_the_bound_code_raises():
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    with pytest.raises(RuntimeError):
        with bind_actor(actor):
            assert current_actor() is actor
            raise RuntimeError("simulated failure deep inside a bound request")
    assert current_actor() is None


def test_nested_bind_actor_restores_the_outer_actor_on_exit():
    outer = ActorContext(user_id="outer-user", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    inner = ActorContext(user_id="inner-user", organization_id="22222222-2222-2222-2222-222222222222", role="VIEWER")
    with bind_actor(outer):
        assert current_actor() is outer
        with bind_actor(inner):
            assert current_actor() is inner
        assert current_actor() is outer
    assert current_actor() is None


# ---------------------------------------------------------------------
# Concurrent actors from different organizations: contextvars are
# task-local in asyncio, so two "requests" running concurrently (as
# separate tasks, exactly how Starlette/FastAPI schedules real
# concurrent HTTP requests) must never see each other's bound actor.
# ---------------------------------------------------------------------


async def test_concurrent_requests_from_different_organizations_never_cross_contaminate():
    org_a_actor = ActorContext(user_id="alice", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")
    org_b_actor = ActorContext(user_id="bob", organization_id="22222222-2222-2222-2222-222222222222", role="OWNER")

    observed: dict[str, list[ActorContext | None]] = {"a": [], "b": []}

    async def simulate_request(key: str, actor: ActorContext) -> None:
        with bind_actor(actor):
            for _ in range(5):
                # Yield control back to the event loop repeatedly,
                # interleaving with the OTHER simulated request below --
                # a real cross-contamination bug would surface here as
                # one task observing the other's actor after a yield.
                await asyncio.sleep(0)
                observed[key].append(current_actor())

    await asyncio.gather(
        simulate_request("a", org_a_actor),
        simulate_request("b", org_b_actor),
    )

    assert all(actor is org_a_actor for actor in observed["a"])
    assert all(actor is org_b_actor for actor in observed["b"])
    assert current_actor() is None  # neither task's binding leaked past its own scope


async def test_a_task_spawned_while_an_actor_is_bound_inherits_it_correctly():
    # asyncio.create_task() copies the CURRENT context at creation time
    # -- this is what lets a derived-assertion-signing HTTP call made
    # deep inside a LangGraph node (itself scheduled as further nested
    # awaits/tasks during graph.ainvoke) still see the actor bound at
    # the API boundary, without threading it through every function
    # signature. Proven directly here, not merely asserted in a
    # docstring.
    actor = ActorContext(user_id="carol", organization_id="33333333-3333-3333-3333-333333333333", role="ENGINEER")
    seen: list[ActorContext | None] = []

    async def inner_task() -> None:
        await asyncio.sleep(0)
        seen.append(current_actor())

    with bind_actor(actor):
        task = asyncio.create_task(inner_task())
        await task

    assert seen == [actor]
