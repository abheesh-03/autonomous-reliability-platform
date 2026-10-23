"""Phase 14 Gate 10: real-request-level tenant-isolation and RBAC
negative controls for the incident/remediation-decision endpoints,
with CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT explicitly enabled for
every test in this module (the pre-Phase-14 default, disabled, is
exercised by every OTHER existing test file unchanged).

Uses TWO distinct organizations and crafted, correctly-signed service
assertions for each -- never mocked authorization helpers -- so these
tests exercise the exact same `core/authz.py` verification path a real
web-console-minted assertion would go through.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from control_plane.api.dependencies import (
    get_auth_membership_repository,
    get_incident_repository,
    get_remediation_repository,
)
from control_plane.core.config import (
    InternalServiceReadTokenSettings,
    OrganizationContextSettings,
    ServiceAssertionSettings,
)
from control_plane.main import app
from tests.conftest import (
    REMEDIATION_EXECUTOR_TOKEN,
    REMEDIATION_PROPOSAL_TOKEN,
    FakeIncidentRepository,
    make_incident_row,
)

ASSERTION_SECRET = "test-org-scoping-assertion-secret"
ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"
AGENT_RUNTIME_INTERNAL_TOKEN = "test-internal-read-token-agent-runtime"
INVESTIGATOR_INTERNAL_TOKEN = "test-internal-read-token-investigator"
TOOL_GATEWAY_INTERNAL_TOKEN = "test-internal-read-token-tool-gateway"


def _assertion(
    *, org: str, role: str = "VIEWER", sub: str = "user-1", aud: str = "control-plane", iss: str = "web-console"
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sub,
            "org": org,
            "role": role,
            "iss": iss,
            "aud": aud,
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        ASSERTION_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def org_client(client):
    """Enables organization-context enforcement for the duration of a
    test, with a known, deterministic assertion-signing secret -- then
    restores the prior (disabled-by-default) settings afterward so no
    other test in the suite is affected."""
    previous_org_settings = app.state.organization_context_settings
    previous_assertion_settings = app.state.service_assertion_settings
    previous_internal_tokens = app.state.internal_service_read_tokens
    app.state.organization_context_settings = OrganizationContextSettings(enabled=True)
    app.state.service_assertion_settings = ServiceAssertionSettings(
        secret=ASSERTION_SECRET,
        trusted_issuers=frozenset({"web-console", "agent-runtime-service", "investigator-service"}),
        audience="control-plane",
        max_clock_skew_seconds=5,
    )
    app.state.internal_service_read_tokens = InternalServiceReadTokenSettings(
        agent_runtime_token=AGENT_RUNTIME_INTERNAL_TOKEN,
        investigator_token=INVESTIGATOR_INTERNAL_TOKEN,
        tool_gateway_token=TOOL_GATEWAY_INTERNAL_TOKEN,
    )
    yield client
    app.state.organization_context_settings = previous_org_settings
    app.state.service_assertion_settings = previous_assertion_settings
    app.state.internal_service_read_tokens = previous_internal_tokens


@pytest.fixture
def two_tenant_incidents(org_client):
    incident_a = make_incident_row(organization_id=ORG_A, title="Org A incident")
    incident_b = make_incident_row(organization_id=ORG_B, title="Org B incident")
    fake = FakeIncidentRepository([incident_a, incident_b])
    app.dependency_overrides[get_incident_repository] = lambda: fake
    yield incident_a, incident_b
    app.dependency_overrides.pop(get_incident_repository, None)


# ---------------------------------------------------------------------
# AUTHENTICATION: missing/forged assertions fail closed
# ---------------------------------------------------------------------


def test_missing_assertion_is_rejected_when_enforcement_is_on(org_client, two_tenant_incidents):
    response = org_client.get("/api/v1/incidents")
    assert response.status_code == 401


def test_forged_assertion_signature_is_rejected(org_client, two_tenant_incidents):
    forged = _assertion(org=ORG_A) + "tampered"
    response = org_client.get("/api/v1/incidents", headers={"X-Service-Assertion": forged})
    assert response.status_code == 401


def test_assertion_with_wrong_audience_is_rejected(org_client, two_tenant_incidents):
    token = _assertion(org=ORG_A, aud="agent-runtime-service")
    response = org_client.get("/api/v1/incidents", headers={"X-Service-Assertion": token})
    assert response.status_code == 401


# ---------------------------------------------------------------------
# TENANT ISOLATION
# ---------------------------------------------------------------------


def test_org_a_cannot_list_org_bs_incidents(org_client, two_tenant_incidents):
    _incident_a, incident_b = two_tenant_incidents
    token = _assertion(org=ORG_A)
    response = org_client.get("/api/v1/incidents", headers={"X-Service-Assertion": token})
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert str(incident_b["id"]) not in ids


def test_org_a_cannot_retrieve_org_bs_incident_by_known_uuid(org_client, two_tenant_incidents):
    _incident_a, incident_b = two_tenant_incidents
    token = _assertion(org=ORG_A)
    response = org_client.get(f"/api/v1/incidents/{incident_b['id']}", headers={"X-Service-Assertion": token})
    # A real cross-tenant 404 -- never 403 (Gate 5: never confirm the
    # resource exists in another organization).
    assert response.status_code == 404


def test_org_a_cannot_retrieve_org_bs_incident_event_history(org_client, two_tenant_incidents):
    _incident_a, incident_b = two_tenant_incidents
    token = _assertion(org=ORG_A)
    response = org_client.get(
        f"/api/v1/incidents/{incident_b['id']}/events", headers={"X-Service-Assertion": token}
    )
    assert response.status_code == 404


def test_org_b_can_retrieve_its_own_incident(org_client, two_tenant_incidents):
    _incident_a, incident_b = two_tenant_incidents
    token = _assertion(org=ORG_B)
    response = org_client.get(f"/api/v1/incidents/{incident_b['id']}", headers={"X-Service-Assertion": token})
    assert response.status_code == 200
    assert response.json()["id"] == str(incident_b["id"])


def test_a_lookup_for_an_entirely_unknown_id_is_also_404_identically(org_client, two_tenant_incidents):
    # Cross-tenant denial and genuine nonexistence must be
    # indistinguishable from the outside.
    token = _assertion(org=ORG_A)
    response = org_client.get(f"/api/v1/incidents/{uuid.uuid4()}", headers={"X-Service-Assertion": token})
    assert response.status_code == 404


def test_same_fingerprint_in_two_organizations_remains_isolated(org_client):
    shared_fingerprint_a = make_incident_row(
        organization_id=ORG_A, source="alertmanager", source_fingerprint="shared-fp", title="A's alert"
    )
    shared_fingerprint_b = make_incident_row(
        organization_id=ORG_B, source="alertmanager", source_fingerprint="shared-fp", title="B's alert"
    )
    fake = FakeIncidentRepository([shared_fingerprint_a, shared_fingerprint_b])
    app.dependency_overrides[get_incident_repository] = lambda: fake
    try:
        token_a = _assertion(org=ORG_A)
        response = org_client.get("/api/v1/incidents", headers={"X-Service-Assertion": token_a})
        assert response.status_code == 200
        titles = {item["title"] for item in response.json()["items"]}
        assert titles == {"A's alert"}
    finally:
        app.dependency_overrides.pop(get_incident_repository, None)


# ---------------------------------------------------------------------
# RBAC: remediation-decision role check (Gate 7)
# ---------------------------------------------------------------------


class _SingleProposalRemediationRepository:
    def __init__(self, proposal: dict) -> None:
        self.proposal = proposal
        self.decide_called = False
        self.decide_kwargs: dict | None = None
        # Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C:
        # call-tracking for the three machine write-side endpoints,
        # mirroring decide_called's own convention exactly.
        self.create_proposal_called = False
        self.start_execution_called = False
        self.record_execution_result_called = False

    async def get_by_id(self, proposal_id):
        if proposal_id == self.proposal["id"]:
            return self.proposal
        return None

    async def decide(self, *args, **kwargs):  # pragma: no cover -- must never be reached when role-denied
        self.decide_called = True
        self.decide_kwargs = kwargs
        return self.proposal

    async def create_proposal(self, **kwargs):  # pragma: no cover -- must never be reached when tenant-denied
        self.create_proposal_called = True
        return self.proposal, True

    async def start_execution(self, proposal_id):  # pragma: no cover -- must never be reached when tenant-denied
        self.start_execution_called = True
        return self.proposal

    async def record_execution_result(
        self, proposal_id, *, outcome, detail=None
    ):  # pragma: no cover -- must never be reached when tenant-denied
        self.record_execution_result_called = True
        return self.proposal

    async def commit(self):  # pragma: no cover
        pass


class _FakeAuthMembershipRepository:
    """Phase 14 correction round, Blocker 4: stands in for a live
    `auth.member` lookup -- tests set `.role` to whatever this
    organization's CURRENT, authoritative role for the actor is,
    independent of whatever role the (possibly stale) signed assertion
    itself claims. `None` simulates a revoked/removed membership."""

    def __init__(self, role: str | None = None) -> None:
        self.role = role

    async def get_current_role(self, *, user_id: str, organization_id: str) -> str | None:
        return self.role


@pytest.fixture
def proposal_for_org_a(org_client):
    incident_a = make_incident_row(organization_id=ORG_A)
    now = datetime.now(UTC)
    proposal = {
        "id": uuid.uuid4(),
        "incident_id": incident_a["id"],
        "agent_run_id": uuid.uuid4(),
        "idempotency_key": "test-idempotency-key",
        "action_type": "clear_payment_authorization_fault",
        "target": "payment-service",
        "reason": "test",
        "supporting_evidence_ids": [],
        "supporting_context_ids": [],
        "status": "pending_approval",
        "proposed_at": now,
        "updated_at": now,
        "decided_at": None,
        "decision_comment": None,
        "execution_started_at": None,
        "execution_completed_at": None,
    }
    incident_fake = FakeIncidentRepository([incident_a])
    remediation_fake = _SingleProposalRemediationRepository(proposal)
    membership_fake = _FakeAuthMembershipRepository()
    app.dependency_overrides[get_incident_repository] = lambda: incident_fake
    app.dependency_overrides[get_remediation_repository] = lambda: remediation_fake
    app.dependency_overrides[get_auth_membership_repository] = lambda: membership_fake
    yield proposal, remediation_fake, membership_fake
    app.dependency_overrides.pop(get_incident_repository, None)
    app.dependency_overrides.pop(get_remediation_repository, None)
    app.dependency_overrides.pop(get_auth_membership_repository, None)


def test_viewer_cannot_decide_a_remediation_proposal_and_nothing_is_mutated(org_client, proposal_for_org_a):
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "VIEWER"  # Blocker 4: the LIVE role is what's actually checked
    token = _assertion(org=ORG_A, role="VIEWER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 403
    assert remediation_fake.decide_called is False


def test_engineer_cannot_decide_a_remediation_proposal(org_client, proposal_for_org_a):
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "ENGINEER"
    token = _assertion(org=ORG_A, role="ENGINEER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 403
    assert remediation_fake.decide_called is False


def test_admin_does_not_implicitly_bypass_remediation_approval_policy(org_client, proposal_for_org_a):
    # Gate 3: "ADMIN manages members/settings but does NOT implicitly
    # bypass remediation approval policy."
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "ADMIN"
    token = _assertion(org=ORG_A, role="ADMIN")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 403
    assert remediation_fake.decide_called is False


def test_incident_approver_in_a_different_organization_cannot_decide_org_as_proposal(org_client, proposal_for_org_a):
    # "Approval for Organization A must never authorize an action
    # involving Organization B."
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    # No membership_fake.role set here on purpose: require_same_organization
    # must reject this BEFORE the live-membership lookup is ever reached.
    token = _assertion(org=ORG_B, role="INCIDENT_APPROVER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 404  # tenant-isolation 404, never a 403 confirming existence
    assert remediation_fake.decide_called is False


def test_incident_approver_in_the_same_organization_may_decide(org_client, proposal_for_org_a):
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "INCIDENT_APPROVER"
    token = _assertion(org=ORG_A, role="INCIDENT_APPROVER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 200
    assert remediation_fake.decide_called is True


# ---------------------------------------------------------------------
# BLOCKER 4: live membership re-check at the decision boundary, and a
# durable audit trail that identifies the REAL human actor.
# ---------------------------------------------------------------------


def test_a_revoked_approver_is_denied_even_with_a_still_valid_unexpired_assertion(org_client, proposal_for_org_a):
    # The user's own required negative control: "a valid internal
    # credential attempting..." -- no, specifically: "Test
    # removal/demotion immediately before decision. The approval must
    # fail without mutation." The signed assertion still claims
    # INCIDENT_APPROVER (as if minted moments before the actor was
    # removed from the organization) -- the JWT's own role claim alone
    # must never be trusted as proof of CURRENT membership.
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = None  # removed from the organization entirely, right before this request
    token = _assertion(org=ORG_A, role="INCIDENT_APPROVER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 403
    assert remediation_fake.decide_called is False
    assert proposal["status"] == "pending_approval"  # genuinely never mutated


def test_a_demoted_approver_is_denied_even_with_a_still_valid_unexpired_assertion(org_client, proposal_for_org_a):
    # Same guarantee, the OTHER revocation shape: still a member, but
    # demoted to a role that may not decide (e.g. INCIDENT_APPROVER ->
    # VIEWER) since the assertion was minted.
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "VIEWER"
    token = _assertion(org=ORG_A, role="INCIDENT_APPROVER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 403
    assert remediation_fake.decide_called is False
    assert proposal["status"] == "pending_approval"


def test_a_successful_approval_records_the_real_human_actor_in_the_durable_audit(org_client, proposal_for_org_a):
    # The user's other required positive control: "verify that the
    # durable audit identifies the actual human actor."
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "INCIDENT_APPROVER"
    token = _assertion(org=ORG_A, role="INCIDENT_APPROVER", sub="real-human-user-42")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token, "Authorization": "Bearer test-remediation-approver-token"},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 200
    assert remediation_fake.decide_called is True
    assert remediation_fake.decide_kwargs["decided_by_user_id"] == "real-human-user-42"
    assert str(remediation_fake.decide_kwargs["decided_by_organization_id"]) == ORG_A


def test_decision_without_the_static_approver_token_still_fails_even_with_a_valid_actor(org_client, proposal_for_org_a):
    # Defense in depth (Gate 7): the actor check is ADDITIVE, never a
    # replacement for CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN.
    proposal, remediation_fake, membership_fake = proposal_for_org_a
    membership_fake.role = "OWNER"
    token = _assertion(org=ORG_A, role="OWNER")
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={"X-Service-Assertion": token},
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 401
    assert remediation_fake.decide_called is False


# ---------------------------------------------------------------------
# INTERNAL SERVICE IDENTITY (Phase 14 correction round, Blocker 1)
#
# A bare internal-service credential is NOT a tenant-scoped grant on
# its own. Required negative control: "a valid internal credential
# attempting to read a known incident belonging to another
# organization. It must be denied."
# ---------------------------------------------------------------------


def test_agent_runtimes_bare_internal_token_alone_can_no_longer_read_any_incident(org_client, two_tenant_incidents):
    # Blocker 1's core fix: possession of a distinct internal-service
    # token is no longer sufficient, by itself, to read ANY tenant's
    # incident -- not even the token-holder's own. Incident/evidence
    # routes now accept ONLY a verified X-Service-Assertion (either
    # web-console's original one, or one agent-runtime-service/
    # investigator-service relay for the exact human actor they
    # themselves already verified). Presenting the bare internal token
    # alone, with no assertion at all, must be denied identically to
    # presenting no credential.
    _incident_a, incident_b = two_tenant_incidents
    response = org_client.get(
        f"/api/v1/incidents/{incident_b['id']}", headers={"X-Internal-Service-Token": AGENT_RUNTIME_INTERNAL_TOKEN}
    )
    assert response.status_code == 401


def test_a_relayed_assertion_for_the_wrong_tenant_is_still_denied_even_with_a_valid_internal_token(
    org_client, two_tenant_incidents
):
    # The specific scenario the user's Blocker 1 report requires a test
    # for: a valid internal credential attempting to read a KNOWN
    # incident belonging to ANOTHER organization. Simulates
    # agent-runtime-service relaying a real, verified actor's assertion
    # (iss="agent-runtime-service", a trusted issuer) for org A, while
    # also presenting its own valid static internal token -- the
    # assertion's own organization claim still governs, and still
    # fails closed for org B's incident.
    _incident_a, incident_b = two_tenant_incidents
    relayed = _assertion(org=ORG_A, role="OWNER")
    response = org_client.get(
        f"/api/v1/incidents/{incident_b['id']}",
        headers={
            "X-Service-Assertion": relayed,
            "X-Internal-Service-Token": AGENT_RUNTIME_INTERNAL_TOKEN,
        },
    )
    assert response.status_code == 404  # tenant-isolation 404, never a 403 confirming existence


def test_investigators_own_internal_token_is_rejected_by_a_different_services_check(org_client, two_tenant_incidents):
    # An unconfigured/invalid internal token must still be rejected
    # identically (401) even though, post-Blocker-1, no bare internal
    # token grants a read on this route at all any more.
    _incident_a, incident_b = two_tenant_incidents
    response = org_client.get(
        f"/api/v1/incidents/{incident_b['id']}", headers={"X-Internal-Service-Token": "not-a-real-token"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------
# Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B:
# tool-gateway's bare static internal-service token, PRESENTED ALONE
# with no relayed actor assertion, is no longer sufficient in secure
# mode for ANY proposal -- "a global static internal token alone must
# not permit arbitrary proposal discovery by known UUID." Real
# tool-gateway traffic now relays the SAME assertion agent-runtime-
# service gave it for this exact execution (simulated here with
# iss="agent-runtime-service", a trusted relaying issuer).
# ---------------------------------------------------------------------


def test_tool_gateways_bare_internal_token_alone_can_no_longer_read_any_proposal(org_client, proposal_for_org_a):
    proposal, _remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "approved"  # even a decided, same-org proposal -- the bare token alone is still 401
    response = org_client.get(
        f"/api/v1/remediation-proposals/{proposal['id']}",
        headers={"X-Internal-Service-Token": TOOL_GATEWAY_INTERNAL_TOKEN},
    )
    assert response.status_code == 401


def test_authorized_gateway_relaying_a_matching_org_assertion_reads_the_intended_approved_proposal(
    org_client, proposal_for_org_a
):
    # The required positive control: tool-gateway, relaying agent-
    # runtime-service's real assertion for the SAME organization that
    # owns the proposal it was told to execute, reads it successfully
    # -- "preserve the legitimate tool-gateway ability to independently
    # verify an approved proposal before executing."
    proposal, _remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "approved"
    relayed = _assertion(org=ORG_A, role="OWNER", iss="agent-runtime-service")
    response = org_client.get(
        f"/api/v1/remediation-proposals/{proposal['id']}",
        headers={"X-Internal-Service-Token": TOOL_GATEWAY_INTERNAL_TOKEN, "X-Service-Assertion": relayed},
    )
    assert response.status_code == 200


def test_the_same_credential_cannot_enumerate_or_read_an_unrelated_tenants_approved_proposal(
    org_client, proposal_for_org_a
):
    # The required negative control: the EXACT SAME valid internal
    # token, alongside a relayed assertion for a DIFFERENT
    # organization, still cannot read Org A's proposal by its known
    # UUID -- resolving the proposal is not the same as being
    # authorized for its real tenant.
    proposal, _remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "approved"
    wrong_org_relay = _assertion(org=ORG_B, role="OWNER", iss="agent-runtime-service")
    response = org_client.get(
        f"/api/v1/remediation-proposals/{proposal['id']}",
        headers={"X-Internal-Service-Token": TOOL_GATEWAY_INTERNAL_TOKEN, "X-Service-Assertion": wrong_org_relay},
    )
    assert response.status_code == 404  # tenant-isolation 404, never a 403 confirming existence


def test_a_real_actor_may_still_read_their_own_orgs_still_pending_proposal_via_the_relay(
    org_client, proposal_for_org_a
):
    # A real, tenant-matched actor reading their OWN organization's
    # still-pending proposal is an ordinary, authorized read, not a
    # leak -- status-gating was only ever a proxy for tenant
    # legitimacy on the OLD bare-token path, never a requirement for a
    # real, tenant-matched actor.
    proposal, _remediation_fake, _membership_fake = proposal_for_org_a
    assert proposal["status"] == "pending_approval"
    relayed = _assertion(org=ORG_A, role="OWNER", iss="agent-runtime-service")
    response = org_client.get(
        f"/api/v1/remediation-proposals/{proposal['id']}",
        headers={"X-Internal-Service-Token": TOOL_GATEWAY_INTERNAL_TOKEN, "X-Service-Assertion": relayed},
    )
    assert response.status_code == 200


def test_an_internal_service_token_can_never_decide_a_remediation_proposal(org_client, proposal_for_org_a):
    # The security-critical guarantee (Gate 7 / Issue 3): "A machine
    # credential must not impersonate an arbitrary human approver."
    # decide_remediation_proposal uses get_actor_context exclusively --
    # an internal-service token is not even a recognized credential for
    # it, so this must 401 (missing X-Service-Assertion), identically
    # to presenting no credential at all, regardless of which valid
    # internal token is presented in the WRONG header.
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    response = org_client.post(
        f"/api/v1/remediation-proposals/{proposal['id']}/decision",
        headers={
            "X-Internal-Service-Token": AGENT_RUNTIME_INTERNAL_TOKEN,
            "Authorization": "Bearer test-remediation-approver-token",
        },
        json={"expected_status": "pending_approval", "decision": "approve"},
    )
    assert response.status_code == 401
    assert remediation_fake.decide_called is False


# ---------------------------------------------------------------------
# Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C: the
# three machine write-side endpoints (create proposal, execution
# start, execution result) now additionally require -- when a relayed
# actor assertion is present (secure mode) -- that the actor's own
# organization match the real, resource-bound incident/proposal's
# organization, BEFORE any mutation. The existing, separate static
# Bearer tokens (REMEDIATION_PROPOSAL_TOKEN/REMEDIATION_EXECUTOR_TOKEN)
# remain required, unchanged -- additive, never a replacement.
# ---------------------------------------------------------------------


def test_create_remediation_proposal_denies_an_unrelated_tenants_machine_credential(org_client, proposal_for_org_a):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    wrong_org_relay = _assertion(org=ORG_B, role="OWNER", iss="agent-runtime-service")
    body = {
        "incident_id": str(proposal["incident_id"]),
        "agent_run_id": str(proposal["agent_run_id"]),
        "idempotency_key": "issue-c-cross-tenant-create",
        "action_type": "clear_payment_authorization_fault",
        "target": "payment-service",
        "reason": "test",
    }
    response = org_client.post(
        "/internal/v1/remediation-proposals",
        headers={"Authorization": f"Bearer {REMEDIATION_PROPOSAL_TOKEN}", "X-Service-Assertion": wrong_org_relay},
        json=body,
    )
    assert response.status_code == 404  # tenant-isolation 404, never a 403 confirming existence
    assert remediation_fake.create_proposal_called is False


def test_create_remediation_proposal_succeeds_for_the_legitimate_same_tenant_relay(org_client, proposal_for_org_a):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    matching_relay = _assertion(org=ORG_A, role="OWNER", iss="agent-runtime-service")
    body = {
        "incident_id": str(proposal["incident_id"]),
        "agent_run_id": str(proposal["agent_run_id"]),
        "idempotency_key": "issue-c-legitimate-create",
        "action_type": "clear_payment_authorization_fault",
        "target": "payment-service",
        "reason": "test",
    }
    response = org_client.post(
        "/internal/v1/remediation-proposals",
        headers={"Authorization": f"Bearer {REMEDIATION_PROPOSAL_TOKEN}", "X-Service-Assertion": matching_relay},
        json=body,
    )
    assert response.status_code == 201
    assert remediation_fake.create_proposal_called is True


def test_start_execution_denies_an_unrelated_tenants_machine_credential_and_preserves_idempotency_state(
    org_client, proposal_for_org_a
):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "approved"
    wrong_org_relay = _assertion(org=ORG_B, role="OWNER", iss="agent-runtime-service")
    response = org_client.post(
        f"/internal/v1/remediation-proposals/{proposal['id']}/execution/start",
        headers={"Authorization": f"Bearer {REMEDIATION_EXECUTOR_TOKEN}", "X-Service-Assertion": wrong_org_relay},
        json={},
    )
    assert response.status_code == 404
    assert remediation_fake.start_execution_called is False
    assert proposal["status"] == "approved"  # genuinely never advanced -- existing idempotent state preserved


def test_start_execution_succeeds_for_the_legitimate_same_tenant_relay(org_client, proposal_for_org_a):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "approved"
    matching_relay = _assertion(org=ORG_A, role="OWNER", iss="agent-runtime-service")
    response = org_client.post(
        f"/internal/v1/remediation-proposals/{proposal['id']}/execution/start",
        headers={"Authorization": f"Bearer {REMEDIATION_EXECUTOR_TOKEN}", "X-Service-Assertion": matching_relay},
        json={},
    )
    assert response.status_code == 200
    assert remediation_fake.start_execution_called is True


def test_record_execution_result_denies_an_unrelated_tenants_machine_credential_and_mutates_nothing(
    org_client, proposal_for_org_a
):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "executing"
    wrong_org_relay = _assertion(org=ORG_B, role="OWNER", iss="agent-runtime-service")
    response = org_client.post(
        f"/internal/v1/remediation-proposals/{proposal['id']}/execution/result",
        headers={"Authorization": f"Bearer {REMEDIATION_EXECUTOR_TOKEN}", "X-Service-Assertion": wrong_org_relay},
        json={"outcome": "succeeded"},
    )
    assert response.status_code == 404
    assert remediation_fake.record_execution_result_called is False
    assert proposal["status"] == "executing"


def test_record_execution_result_succeeds_for_the_legitimate_same_tenant_relay(org_client, proposal_for_org_a):
    proposal, remediation_fake, _membership_fake = proposal_for_org_a
    proposal["status"] = "executing"
    matching_relay = _assertion(org=ORG_A, role="OWNER", iss="agent-runtime-service")
    response = org_client.post(
        f"/internal/v1/remediation-proposals/{proposal['id']}/execution/result",
        headers={"Authorization": f"Bearer {REMEDIATION_EXECUTOR_TOKEN}", "X-Service-Assertion": matching_relay},
        json={"outcome": "succeeded"},
    )
    assert response.status_code == 200
    assert remediation_fake.record_execution_result_called is True
