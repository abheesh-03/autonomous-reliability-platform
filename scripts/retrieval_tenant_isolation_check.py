"""Phase 14 correction round, Blocker 2: a real-PostgreSQL positive/
negative proof for tenant-scoped historical retrieval, run against the
live Compose stack's actual database -- never mocks, never a fake
pool. Invoked by scripts/verify-retrieval-tenant-isolation.sh inside a
disposable container joined to the Compose network (so it exercises
retrieval-service's real source tree without needing to rebuild or
restart the already-running retrieval-service container).

Proves, against real rows in the real `reliability.incidents` /
`reliability.retrieval_chunks` tables:
  - db.get_incident_organization_id resolves an incident's REAL owning
    organization (and fails closed -- returns None, never raises --
    for an unknown or malformed id).
  - db.search_chunks's own tenant JOIN genuinely isolates two
    organizations' historical chunks from each other.
  - search._resolve_historical_organization_scope, in SECURE mode
    (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT), IGNORES a
    client-claimed `organization_id` entirely and instead derives the
    real tenant scope from `exclude_incident_id` -- i.e. "an internal
    credential cannot simply name another tenant to retrieve its
    private evidence" -- and fails closed (no historical search) when
    there is no real, resolvable incident to bind scope to.
  - In legacy/local-development mode (the flag disabled), the exact
    pre-Phase-14 behavior is preserved byte-for-byte: the
    caller-supplied organization_id (or its absence) is honored as-is.

Inserts two synthetic incidents (org A, org B) and their matching
retrieval_chunks rows under a distinctive, searchable marker
(source='phase14-blocker2-check' / embedding_space='blocker2-check'),
then deletes exactly those rows in a `finally` block -- never any
pre-existing row, and never resets or truncates either table.
"""

import asyncio
import hashlib
import os
import sys
import uuid

import asyncpg

sys.path.insert(0, "/app/src")

from retrieval_service import db  # noqa: E402
from retrieval_service.authz import ActorContext  # noqa: E402
from retrieval_service.config import OrganizationContextSettings  # noqa: E402
from retrieval_service.domain.search import SearchRequest  # noqa: E402
from retrieval_service.search import _resolve_historical_organization_scope  # noqa: E402

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

ACTOR_ORG_A = ActorContext(user_id="real-db-check-user-a", organization_id=str(ORG_A), role="ENGINEER")
ACTOR_ORG_B = ActorContext(user_id="real-db-check-user-b", organization_id=str(ORG_B), role="ENGINEER")


def _fake_embedding(seed: int) -> list[float]:
    vec = [0.0] * 1536
    vec[seed % 1536] = 1.0
    return vec


async def main() -> None:
    from retrieval_service.config import DatabaseSettings

    pool = await db.create_pool(
        DatabaseSettings(
            host="postgres",
            port=5432,
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"],
        )
    )

    incident_a = uuid.uuid4()
    incident_b = uuid.uuid4()
    failures: list[str] = []

    def check(label: str, condition: bool) -> None:
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}")
        if not condition:
            failures.append(label)

    try:
        async with pool.acquire() as conn:
            now = "now()"
            await conn.execute(
                f"""
                INSERT INTO reliability.incidents
                    (id, organization_id, source, source_fingerprint, title, severity, status,
                     first_seen_at, last_seen_at, occurrence_starts_at)
                VALUES
                    ($1, $2, 'phase14-blocker2-check', $3, 'Blocker 2 real-DB check: org A', 'info',
                     'open', {now}, {now}, {now})
                """,
                incident_a,
                ORG_A,
                f"blocker2-a-{incident_a}",
            )
            await conn.execute(
                f"""
                INSERT INTO reliability.incidents
                    (id, organization_id, source, source_fingerprint, title, severity, status,
                     first_seen_at, last_seen_at, occurrence_starts_at)
                VALUES
                    ($1, $2, 'phase14-blocker2-check', $3, 'Blocker 2 real-DB check: org B', 'info',
                     'open', {now}, {now}, {now})
                """,
                incident_b,
                ORG_B,
                f"blocker2-b-{incident_b}",
            )

            for incident_id, label in ((incident_a, "org-a"), (incident_b, "org-b")):
                content = f"real-db blocker2 historical chunk for {label}"
                await conn.execute(
                    """
                    INSERT INTO reliability.retrieval_chunks
                        (source_type, source_key, chunk_index, title, content, content_hash,
                         metadata, embedding_space, embedding)
                    VALUES
                        ('historical_incident', $1, 0, $2, $3, $4, '{}'::jsonb, 'blocker2-check',
                         $5::reliability.vector(1536))
                    """,
                    str(incident_id),
                    f"Blocker2 check chunk ({label})",
                    content,
                    hashlib.sha256(content.encode()).hexdigest(),
                    db._vector_literal(_fake_embedding(hash(label))),
                )

        # 1. get_incident_organization_id resolves the REAL owning org.
        resolved_a = await db.get_incident_organization_id(pool, str(incident_a))
        resolved_b = await db.get_incident_organization_id(pool, str(incident_b))
        check("get_incident_organization_id resolves incident A's real org", resolved_a == str(ORG_A))
        check("get_incident_organization_id resolves incident B's real org", resolved_b == str(ORG_B))
        unknown = await db.get_incident_organization_id(pool, str(uuid.uuid4()))
        check("get_incident_organization_id returns None for an unknown incident", unknown is None)
        malformed = await db.get_incident_organization_id(pool, "not-a-uuid")
        check("get_incident_organization_id returns None (never raises) for a malformed id", malformed is None)

        # 2. search_chunks's own tenant JOIN: org A's scope must never
        #    surface org B's historical chunk, and vice versa.
        rows_scoped_to_a = await db.search_chunks(
            pool,
            source_type="historical_incident",
            embedding_space="blocker2-check",
            query_embedding=_fake_embedding(0),
            limit=10,
            organization_id=str(ORG_A),
        )
        keys_a = {r.source_key for r in rows_scoped_to_a}
        check("org A's scoped search sees its own chunk", str(incident_a) in keys_a)
        check("org A's scoped search does NOT see org B's chunk", str(incident_b) not in keys_a)

        rows_scoped_to_b = await db.search_chunks(
            pool,
            source_type="historical_incident",
            embedding_space="blocker2-check",
            query_embedding=_fake_embedding(0),
            limit=10,
            organization_id=str(ORG_B),
        )
        keys_b = {r.source_key for r in rows_scoped_to_b}
        check("org B's scoped search sees its own chunk", str(incident_b) in keys_b)
        check("org B's scoped search does NOT see org A's chunk", str(incident_a) not in keys_b)

        # 3. The Blocker 2 fix itself: _resolve_historical_organization_scope
        #    in SECURE mode derives scope from exclude_incident_id,
        #    ignoring whatever organization_id the client claims.
        secure = OrganizationContextSettings(enabled=True)
        legacy = OrganizationContextSettings(enabled=False)

        # An internal credential "naming another tenant": client
        # claims org B's id directly, but the real, resource-bound
        # incident (exclude_incident_id) actually belongs to org A.
        # A real, correctly-matching org A actor is relayed too.
        malicious_request = SearchRequest(
            query="x", exclude_incident_id=incident_a, organization_id=ORG_B
        )
        org_id, may_search = await _resolve_historical_organization_scope(
            pool, secure, malicious_request, ACTOR_ORG_A
        )
        check(
            "secure mode IGNORES a client-claimed organization_id and derives the real owner instead",
            may_search and org_id == str(ORG_A),
        )

        honest_request = SearchRequest(query="x", exclude_incident_id=incident_b)
        org_id2, may_search2 = await _resolve_historical_organization_scope(
            pool, secure, honest_request, ACTOR_ORG_B
        )
        check(
            "secure mode derives the correct scope for a legitimate resource-bound request",
            may_search2 and org_id2 == str(ORG_B),
        )

        no_anchor_request = SearchRequest(query="x", organization_id=ORG_A)
        org_id3, may_search3 = await _resolve_historical_organization_scope(
            pool, secure, no_anchor_request, ACTOR_ORG_A
        )
        check(
            "secure mode fails closed (no historical search) with no exclude_incident_id anchor at all",
            may_search3 is False and org_id3 is None,
        )

        unknown_anchor_request = SearchRequest(query="x", exclude_incident_id=uuid.uuid4())
        org_id4, may_search4 = await _resolve_historical_organization_scope(
            pool, secure, unknown_anchor_request, ACTOR_ORG_A
        )
        check(
            "secure mode fails closed when exclude_incident_id does not resolve to a real incident",
            may_search4 is False and org_id4 is None,
        )

        # 3b. FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue A: the
        # EXACT scenario the independent review reproduced directly
        # from the current source -- a real, authenticated
        # Organization A actor, with an otherwise-valid internal-
        # service relay, names a REAL incident belonging to
        # Organization B by its known UUID. Resolving incident_b's
        # real owning organization (org B) must NOT be conflated with
        # authorizing org A's own actor to see it.
        cross_tenant_request = SearchRequest(query="x", exclude_incident_id=incident_b)
        org_id_cross, may_search_cross = await _resolve_historical_organization_scope(
            pool, secure, cross_tenant_request, ACTOR_ORG_A
        )
        check(
            "secure mode DENIES a real Org A actor (valid internal relay) retrieving Org B's "
            "incident's historical results by B's known incident id -- no B data returned",
            may_search_cross is False and org_id_cross is None,
        )

        # The explicit static-credential-alone negative control: no
        # relayed actor assertion at all, even though the incident
        # resolves to a real organization and the internal credential
        # itself would otherwise be perfectly valid.
        no_actor_request = SearchRequest(query="x", exclude_incident_id=incident_a)
        org_id_no_actor, may_search_no_actor = await _resolve_historical_organization_scope(
            pool, secure, no_actor_request, None
        )
        check(
            "secure mode DENIES historical search when no actor assertion was relayed at all, "
            "even with a resolvable incident and an otherwise-valid internal credential",
            may_search_no_actor is False and org_id_no_actor is None,
        )

        # The required positive control: legitimate A-to-A retrieval
        # still works end to end once the actor's own organization
        # genuinely matches the incident's real owning organization.
        legitimate_request = SearchRequest(query="x", exclude_incident_id=incident_a)
        org_id_legit, may_search_legit = await _resolve_historical_organization_scope(
            pool, secure, legitimate_request, ACTOR_ORG_A
        )
        check(
            "secure mode ALLOWS a real Org A actor to retrieve Org A's own incident's historical results",
            may_search_legit and org_id_legit == str(ORG_A),
        )

        # 4. Legacy/local-dev mode: exact pre-Phase-14 behavior preserved,
        #    explicitly isolated from secure mode's actor requirement
        #    above -- no actor is relayed here at all, by design.
        legacy_request = SearchRequest(query="x", organization_id=ORG_A)
        org_id5, may_search5 = await _resolve_historical_organization_scope(pool, legacy, legacy_request, None)
        check(
            "legacy mode preserves the client-supplied organization_id as-is",
            may_search5 and org_id5 == str(ORG_A),
        )
        legacy_unscoped_request = SearchRequest(query="x")
        org_id6, may_search6 = await _resolve_historical_organization_scope(
            pool, legacy, legacy_unscoped_request, None
        )
        check(
            "legacy mode preserves the pre-Phase-14 fully-unscoped search when organization_id is omitted",
            may_search6 and org_id6 is None,
        )

    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM reliability.retrieval_chunks WHERE embedding_space = 'blocker2-check'"
            )
            await conn.execute(
                "DELETE FROM reliability.incidents WHERE id = ANY($1::uuid[])", [incident_a, incident_b]
            )
        await pool.close()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s) did not pass: {failures}")
        sys.exit(1)
    print("ALL CHECKS PASSED (real PostgreSQL, live compose stack)")


asyncio.run(main())
