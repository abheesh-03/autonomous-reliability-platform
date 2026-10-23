"""Phase 14 correction round, BLOCKER 4: a real, live, read-only check
of a user's CURRENT organization membership/role, straight from Better
Auth's own tables (`auth.member`) -- never a cache, never derived from
anything the signed service assertion itself claims.

Why this exists: a signed assertion's `role`/`org` claims are correct
at the moment web-console minted it (a FRESH check at that time), but
the assertion is valid for up to its own expiry window (60s) and could,
in principle, be replayed within that window by a request that arrives
AFTER the member was demoted or removed from the organization. The
human-approval decision boundary (api/remediation.py::decide_remediation_proposal)
is explicitly called out as security-critical (Gate 7) specifically
because an incorrect approval cannot be undone the way a stale read
can -- so it is the ONE place this platform does a SECOND, live lookup
at the moment of the actual mutation, rather than trusting the
assertion's claims alone.

This is a genuinely cross-schema read: `auth.member`/`auth."user"` are
owned and migrated exclusively by Better Auth (via the dedicated
`web_console` Postgres role -- scripts/init-web-console-db.sh), never
by Flyway, and this repository's own role (`POSTGRES_USER`) is granted
ONLY `SELECT` on them (see that script's own grant) -- this repository
has no INSERT/UPDATE/DELETE capability on either table, by construction,
not merely by convention. There is deliberately no literal foreign key
between `reliability.*` and `auth.*` (see
docs/architecture/phase-14-security-multitenancy.md's "schema
separation" note) -- this repository is the one place that
relationship is read, at the application layer, read-only.
"""

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("control_plane.auth_membership")

# Bare, metadata-free Core table expressions -- same convention
# repositories/incident_repository.py already establishes for
# Flyway-owned tables, used here for a schema this service does NOT
# own and must never attempt to create/alter/drop (there is no
# metadata.create_all() capability reachable from this object at all).
#
# organizationId/userId are explicitly typed PG_UUID -- Better Auth's
# `generateId: "uuid"` (Issue 1) makes every one of its own id columns,
# including these two foreign-key-shaped ones, a REAL native Postgres
# UUID column, confirmed directly against the regenerated
# auth-schema/schema.sql. Leaving them untyped here would reproduce
# the EXACT real bug Issue 1's own correction found (`operator does
# not exist: uuid = character varying`) the first time this query
# actually runs against a real database.
_member_table = sa.table(
    "member",
    sa.column("organizationId", PG_UUID(as_uuid=True)),
    sa.column("userId", PG_UUID(as_uuid=True)),
    sa.column("role"),
    schema="auth",
)


class AuthMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current_role(self, *, user_id: str, organization_id: str) -> str | None:
        """Returns the user's REAL, CURRENT role in this organization,
        read fresh from Better Auth's own `member` table -- or `None`
        if no such membership exists right now (removed, or never a
        member at all). Never raises for "not found" -- an absent
        membership is an ordinary, expected outcome for a revoked
        approver, not an error."""
        stmt = sa.select(_member_table.c.role).where(
            _member_table.c.userId == user_id,
            _member_table.c.organizationId == organization_id,
        )
        result = await self._session.execute(stmt)
        row = result.first()
        return row[0] if row is not None else None
