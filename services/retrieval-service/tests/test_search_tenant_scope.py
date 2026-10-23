"""Phase 14 correction round, Blocker 2, extended by the FINAL
MACHINE-IDENTITY TENANT-BOUNDARY FIX (Issue A): unit tests for
search._resolve_historical_organization_scope -- the function that
decides what tenant scope (if any) governs historical-incident
retrieval. Real-PostgreSQL positive/negative proof against the
actual `reliability.incidents`/`reliability.retrieval_chunks` tables
lives in scripts/retrieval_tenant_isolation_check.py (run via
`make verify-retrieval-tenant-isolation`, against the real Compose
stack) -- these tests cover the pure decision logic with a fake
`db.get_incident_organization_id`, same fake-double convention as the
rest of this suite (never a real database connection here).

Issue A's core finding: resolving `exclude_incident_id`'s real owning
organization proves which tenant owns the incident -- it does NOT
prove the CALLER is authorized for it. A valid internal credential
alone could previously name ANY existing incident id and receive that
incident's owning organization's historical results. The fix requires
a relayed, verified actor whose OWN organization_id must match the
incident's real owning organization -- never the static credential
alone, never an unauthenticated/mismatched actor."""

import uuid

import pytest

from retrieval_service import search as search_module
from retrieval_service.authz import ActorContext
from retrieval_service.config import OrganizationContextSettings
from retrieval_service.domain.search import SearchRequest

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
INCIDENT_A = uuid.uuid4()

SECURE = OrganizationContextSettings(enabled=True)
LEGACY = OrganizationContextSettings(enabled=False)

ACTOR_ORG_A = ActorContext(user_id="user-1", organization_id=str(ORG_A), role="ENGINEER")
ACTOR_ORG_B = ActorContext(user_id="user-2", organization_id=str(ORG_B), role="ENGINEER")


@pytest.fixture
def fake_pool(monkeypatch):
    """A fake `db.get_incident_organization_id`: INCIDENT_A resolves
    to ORG_A; anything else is an unknown incident."""

    async def fake_get_incident_organization_id(pool, incident_id):
        return str(ORG_A) if incident_id == str(INCIDENT_A) else None

    monkeypatch.setattr(search_module.db, "get_incident_organization_id", fake_get_incident_organization_id)
    return object()  # the function above ignores its `pool` argument entirely


async def test_legacy_mode_honors_a_client_supplied_organization_id(fake_pool):
    # Legacy mode never looks at `actor` at all -- explicitly isolated
    # from secure mode's authorization requirement.
    request = SearchRequest(query="x", organization_id=ORG_B)
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, LEGACY, request, None
    )
    assert may_search is True
    assert org_id == str(ORG_B)


async def test_legacy_mode_preserves_fully_unscoped_search_when_omitted(fake_pool):
    request = SearchRequest(query="x")
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, LEGACY, request, None
    )
    assert may_search is True
    assert org_id is None


async def test_secure_mode_derives_scope_from_the_real_incident_never_the_client_claim(fake_pool):
    # The core Blocker 2 guarantee, still intact: a crafted request
    # naming ORG_B directly is ignored -- the real owner of INCIDENT_A
    # (ORG_A) wins. A matching, verified actor is ALSO required now
    # (Issue A) -- this is the legitimate A-to-A case.
    request = SearchRequest(query="x", exclude_incident_id=INCIDENT_A, organization_id=ORG_B)
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, ACTOR_ORG_A
    )
    assert may_search is True
    assert org_id == str(ORG_A)


async def test_secure_mode_fails_closed_with_no_resource_to_bind_to(fake_pool):
    request = SearchRequest(query="x", organization_id=ORG_A)
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, ACTOR_ORG_A
    )
    assert may_search is False
    assert org_id is None


async def test_secure_mode_fails_closed_for_an_unresolvable_incident(fake_pool):
    request = SearchRequest(query="x", exclude_incident_id=uuid.uuid4())
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, ACTOR_ORG_A
    )
    assert may_search is False
    assert org_id is None


# ---------------------------------------------------------------------
# Issue A: a trusted, actor-bound AND resource-bound authorization
# context is required -- neither fact alone is sufficient.
# ---------------------------------------------------------------------


async def test_secure_mode_denies_a_valid_credential_naming_another_tenants_incident(fake_pool):
    # The exact scenario the independent review reproduced: a real,
    # authenticated Organization A actor, with an otherwise-valid
    # internal-service relay, names Organization B's incident (B's
    # own org never appears anywhere in the request -- only the real
    # resource id A already, legitimately knows). Must be denied, not
    # merely re-scoped to A.
    request = SearchRequest(query="x", exclude_incident_id=INCIDENT_A)  # INCIDENT_A belongs to ORG_A, not B
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, ACTOR_ORG_B
    )
    assert may_search is False
    assert org_id is None


async def test_secure_mode_denies_when_no_actor_assertion_was_relayed_at_all(fake_pool):
    # "Do not authorize by the static internal credential alone": even
    # though exclude_incident_id correctly resolves to a real incident,
    # NO relayed actor at all must still deny historical search.
    request = SearchRequest(query="x", exclude_incident_id=INCIDENT_A)
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, None
    )
    assert may_search is False
    assert org_id is None


async def test_secure_mode_allows_legitimate_same_tenant_retrieval(fake_pool):
    # The positive control the independent review explicitly asked
    # for: a real Organization A actor retrieving historical evidence
    # for Organization A's own incident.
    request = SearchRequest(query="x", exclude_incident_id=INCIDENT_A)
    org_id, may_search = await search_module._resolve_historical_organization_scope(
        fake_pool, SECURE, request, ACTOR_ORG_A
    )
    assert may_search is True
    assert org_id == str(ORG_A)
