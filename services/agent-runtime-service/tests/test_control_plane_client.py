"""HTTP-contract-level tests for clients/control_plane.py, using
httpx.MockTransport (never a real network call) -- same convention
every other service in this platform already establishes."""

import httpx
import jwt
import pytest

import uuid

from agent_runtime_service.authz import ActorContext, bind_actor
from agent_runtime_service.clients.control_plane import (
    ControlPlaneClient,
    ControlPlaneOutputError,
    ControlPlaneUnavailableError,
    IncidentNotFoundError,
    RemediationProposalConflictError,
    RemediationProposalCreateAmbiguousError,
)
from agent_runtime_service.config import ServiceAssertionSettings
from tests.conftest import SAMPLE_INCIDENT_ID, incident_json

_ASSERTION_SETTINGS = ServiceAssertionSettings(
    secret="test-shared-assertion-secret",
    issuer="web-console",
    audience="agent-runtime-service",
    max_clock_skew_seconds=5,
    control_plane_audience="control-plane",
    investigator_audience="investigator-service",
)


# ---------------------------------------------------------------------
# Phase 14 correction round, Blocker 1 / Task 2 audit: see the
# identical pair of tests in investigator-service's own
# tests/test_control_plane_client.py -- same guarantee, same client
# contract, now proven here too for agent-runtime-service's own
# control-plane client (this exact pairing was previously untested).
# ---------------------------------------------------------------------


async def test_a_bound_actor_is_relayed_as_a_derived_assertion_not_the_bare_token():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=incident_json())

    client = ControlPlaneClient(
        "http://control-plane",
        2.0,
        5.0,
        transport=httpx.MockTransport(handler),
        internal_read_token="bare-static-read-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="ENGINEER")

    with bind_actor(actor):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))

    assert "x-service-assertion" in seen_headers
    assert "x-internal-service-token" not in seen_headers
    payload = jwt.decode(
        seen_headers["x-service-assertion"],
        _ASSERTION_SETTINGS.secret,
        algorithms=["HS256"],
        audience="control-plane",
    )
    assert payload["iss"] == "agent-runtime-service"
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "ENGINEER"


async def test_with_no_bound_actor_the_bare_internal_token_is_sent_as_a_fallback():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=incident_json())

    client = ControlPlaneClient(
        "http://control-plane",
        2.0,
        5.0,
        transport=httpx.MockTransport(handler),
        internal_read_token="bare-static-read-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    await client.get_incident(str(SAMPLE_INCIDENT_ID))

    assert seen_headers.get("x-internal-service-token") == "bare-static-read-token"
    assert "x-service-assertion" not in seen_headers


# ---------------------------------------------------------------------
# Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C: a
# bound actor must ALSO be relayed on proposal creation, additive to
# the existing CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN Bearer auth --
# "prevent a machine credential from creating... an unrelated tenant's
# remediation proposal."
# ---------------------------------------------------------------------


def _proposal_response_json() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "incident_id": str(SAMPLE_INCIDENT_ID),
        "agent_run_id": str(uuid.uuid4()),
        "action_type": "clear_payment_authorization_fault",
        "target": "payment-service",
        "status": "pending_approval",
    }


async def test_create_remediation_proposal_relays_a_bound_actor_alongside_the_proposal_token():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(201, json=_proposal_response_json())

    client = ControlPlaneClient(
        "http://control-plane",
        2.0,
        5.0,
        transport=httpx.MockTransport(handler),
        remediation_proposal_token="test-proposal-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    actor = ActorContext(user_id="user-1", organization_id="11111111-1111-1111-1111-111111111111", role="OWNER")

    with bind_actor(actor):
        await client.create_remediation_proposal(**_create_kwargs("issue-c-relay-test"))

    assert seen_headers.get("authorization") == "Bearer test-proposal-token"
    assert "x-service-assertion" in seen_headers
    payload = jwt.decode(
        seen_headers["x-service-assertion"], _ASSERTION_SETTINGS.secret, algorithms=["HS256"], audience="control-plane"
    )
    assert payload["sub"] == "user-1"
    assert payload["org"] == "11111111-1111-1111-1111-111111111111"


async def test_create_remediation_proposal_with_no_bound_actor_sends_only_the_proposal_token():
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(201, json=_proposal_response_json())

    client = ControlPlaneClient(
        "http://control-plane",
        2.0,
        5.0,
        transport=httpx.MockTransport(handler),
        remediation_proposal_token="test-proposal-token",
        service_assertion_settings=_ASSERTION_SETTINGS,
    )
    await client.create_remediation_proposal(**_create_kwargs("issue-c-no-actor-test"))

    assert seen_headers.get("authorization") == "Bearer test-proposal-token"
    assert "x-service-assertion" not in seen_headers


def _create_kwargs(idempotency_key: str) -> dict:
    return dict(
        incident_id=SAMPLE_INCIDENT_ID,
        agent_run_id=uuid.uuid4(),
        idempotency_key=idempotency_key,
        action_type="clear_payment_authorization_fault",
        target="payment-service",
        reason="test",
        supporting_evidence_ids=[],
        supporting_context_ids=[],
    )


async def test_get_incident_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=incident_json())

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    incident = await client.get_incident(str(SAMPLE_INCIDENT_ID))
    assert incident.id == SAMPLE_INCIDENT_ID


async def test_get_incident_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "incident not found"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(IncidentNotFoundError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_get_incident_5xx_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneUnavailableError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_connection_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneUnavailableError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_malformed_shape_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totally": "wrong shape"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_non_json_response_raises_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError):
        await client.get_incident(str(SAMPLE_INCIDENT_ID))


async def test_output_error_never_leaks_the_raw_field_value():
    """Phase 7 correction round (finding #5): independent review
    reproduced a secret-shaped value from pydantic's own
    ValidationError string (which includes input_value verbatim)
    leaking through a raised exception's message. Proves the fix:
    a field whose value is a fake secret must never appear in the
    raised ControlPlaneOutputError's own str()."""

    def handler(request: httpx.Request) -> httpx.Response:
        # 'severity' fails its Literal validation -- pydantic's
        # ValidationError would normally quote this exact bad value in
        # its error string.
        body = incident_json()
        body["severity"] = "sk-THIS-SHOULD-NOT-BE-PERSISTED-OR-LEAKED"
        return httpx.Response(200, json=body)

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(ControlPlaneOutputError) as exc_info:
        await client.get_incident(str(SAMPLE_INCIDENT_ID))
    assert "sk-THIS-SHOULD-NOT-BE-PERSISTED-OR-LEAKED" not in str(exc_info.value)
    assert str(exc_info.value) == "control-plane response did not match the expected response contract"


def _proposal_json(proposal_id: uuid.UUID, incident_id: uuid.UUID, agent_run_id: uuid.UUID) -> dict:
    return {
        "id": str(proposal_id),
        "incident_id": str(incident_id),
        "agent_run_id": str(agent_run_id),
        "idempotency_key": "k",
        "action_type": "clear_payment_authorization_fault",
        "target": "payment-service",
        "reason": "test",
        "supporting_evidence_ids": [],
        "supporting_context_ids": [],
        "status": "pending_approval",
        "proposed_at": "2026-04-01T09:00:00+00:00",
        "updated_at": "2026-04-01T09:00:00+00:00",
        "decided_at": None,
        "decision_comment": None,
        "execution_started_at": None,
        "execution_completed_at": None,
    }


async def test_create_proposal_malformed_body_raises_ambiguous_not_output_error():
    """Phase 8 correction round (finding #2): control-plane's create
    endpoint already COMMITS the proposal before building its
    response, so a malformed 200 body must raise
    RemediationProposalCreateAmbiguousError -- a DISTINCT, retryable
    type -- never the terminal ControlPlaneOutputError this same
    client correctly still raises for read-only GETs."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await client.create_remediation_proposal(**_create_kwargs("phase8-proposal:test"))


async def test_create_proposal_5xx_raises_ambiguous_not_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await client.create_remediation_proposal(**_create_kwargs("phase8-proposal:test"))


async def test_create_proposal_shape_invalid_body_raises_ambiguous_not_output_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totally": "wrong shape"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await client.create_remediation_proposal(**_create_kwargs("phase8-proposal:test"))


async def test_create_proposal_409_still_raises_conflict_error_unchanged():
    """Point C of the correction's own test list: the 409 semantic-
    conflict path is untouched by this correction -- still terminal,
    still its own distinct type."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "idempotency conflict"})

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(RemediationProposalConflictError):
        await client.create_remediation_proposal(**_create_kwargs("phase8-proposal:test"))


async def test_create_proposal_retry_after_ambiguous_response_converges_to_a_clean_result():
    """Point B: models a retried create_remediation_proposal call (the
    SAME idempotency_key, as propose_remediation always derives
    deterministically from run_id) after an ambiguous first response.
    The first attempt's response is lost/malformed; the SECOND
    attempt -- control-plane's own real idempotent creation logic
    already proven for real in
    services/control-plane/tests/test_remediation_transactions.py --
    cleanly returns the existing proposal. This proves the CLIENT
    correctly raises on the first (ambiguous) attempt and correctly
    parses the clean result on the retried attempt; the underlying
    database-level convergence guarantee (same key -> same row,
    exactly one 'proposed' event) is what that real-PostgreSQL suite
    independently proves."""
    proposal_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json=_proposal_json(proposal_id, incident_id, agent_run_id))

    client = ControlPlaneClient("http://control-plane", 2.0, 5.0, transport=httpx.MockTransport(handler))
    kwargs = dict(
        incident_id=incident_id,
        agent_run_id=agent_run_id,
        idempotency_key="phase8-proposal:same-run",
        action_type="clear_payment_authorization_fault",
        target="payment-service",
        reason="test",
        supporting_evidence_ids=[],
        supporting_context_ids=[],
    )

    with pytest.raises(RemediationProposalCreateAmbiguousError):
        await client.create_remediation_proposal(**kwargs)

    retried = await client.create_remediation_proposal(**kwargs)
    assert retried.id == proposal_id
    assert calls["count"] == 2


async def test_client_never_calls_a_write_http_verb_other_than_the_one_proposal_post():
    """Belt-and-suspenders alongside test_read_only_guarantees.py's own
    module-wide AST check -- this client specifically. Phase 7: no
    write verb at all. Phase 8: exactly one legitimate POST (create a
    remediation proposal, authenticated with
    CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN) -- PUT/PATCH/DELETE must
    still never appear."""
    import ast
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src"
        / "agent_runtime_service"
        / "clients"
        / "control_plane.py"
    )
    tree = ast.parse(path.read_text())
    never_allowed = {"put", "patch", "delete"}
    found = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in never_allowed}
    assert not found, f"control_plane.py calls write HTTP verb(s) it must never use: {found}"
