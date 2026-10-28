"""Database access for reliability.services (Phase 15 Gate 7).

Same bare `sa.table()`/`sa.column()` Core-table convention every other
repository in this service already uses -- real parameter binding
throughout, no SQL injection surface, schema owned exclusively by
Flyway.
"""

import uuid
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

services_table = sa.table(
    "services",
    sa.column("id", PG_UUID(as_uuid=True)),
    # Explicitly PG_UUID, matching the Phase 14 correction round
    # lesson documented on incidents_table.organization_id: a bare,
    # untyped column binds a Python str as ::VARCHAR, which a real
    # PostgreSQL uuid column then rejects with "operator does not
    # exist: uuid = character varying" -- caught here BEFORE a real-
    # database test ever had to find it, not after.
    sa.column("organization_id", PG_UUID(as_uuid=True)),
    sa.column("name"),
    sa.column("kind"),
    sa.column("language"),
    sa.column("description"),
    sa.column("created_by_user_id"),
    sa.column("created_at"),
    sa.column("updated_at"),
    schema="reliability",
)


class ServiceAlreadyExistsError(Exception):
    """Raised when (organization_id, name) collides with
    services_org_name_uniq -- the repository's own, named exception
    rather than letting a raw IntegrityError leak to the route layer,
    matching every other repository's own convention in this
    service."""


class ServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_services(
        self, organization_id: uuid.UUID | str, *, limit: int, offset: int
    ) -> tuple[Sequence[Mapping], int]:
        # Always organization-scoped -- Gate 7: "Respect organization
        # isolation in all service queries." Unlike incidents (which
        # tolerate an unscoped legacy-mode read), this brand-new
        # resource has no legacy precedent and is never listed
        # unscoped; api/services.py's own require_actor_context
        # dependency guarantees a real organization_id reaches here on
        # every call.
        #
        # Independent-review correction round, BLOCKER 4: real
        # server-side pagination -- mirrors incident_repository.py's own
        # list_incidents exactly. `total` is a SEPARATE COUNT over the
        # SAME filtered base query, never `len()` of the (already
        # limited) page of rows; ordering is deterministic (created_at
        # DESC, id DESC as a tiebreaker) so repeated/paged requests never
        # see a row skipped or duplicated across pages merely because
        # two rows share a created_at timestamp.
        base = sa.select(services_table).where(services_table.c.organization_id == str(organization_id))

        total_stmt = sa.select(sa.func.count()).select_from(base.subquery())
        total = (await self._session.execute(total_stmt)).scalar_one()

        page_stmt = (
            base.order_by(services_table.c.created_at.desc(), services_table.c.id.desc()).limit(limit).offset(offset)
        )
        rows = (await self._session.execute(page_stmt)).mappings().all()
        return rows, total

    async def get_by_id_for_organization(
        self, organization_id: uuid.UUID | str, service_id: uuid.UUID | str
    ) -> Mapping | None:
        """Phase 16 Gate 2: the one lookup every integration-credential
        and telemetry route uses to prove "this service belongs to the
        calling actor's own organization" BEFORE creating a credential
        or accepting/displaying telemetry for it -- scoped by BOTH
        columns, never service_id alone (a service_id belonging to a
        different organization must never resolve here)."""
        stmt = sa.select(services_table).where(
            services_table.c.id == str(service_id),
            services_table.c.organization_id == str(organization_id),
        )
        return (await self._session.execute(stmt)).mappings().first()

    async def create_service(
        self,
        *,
        organization_id: uuid.UUID | str,
        name: str,
        kind: str,
        language: str | None,
        description: str | None,
        created_by_user_id: str,
    ) -> Mapping:
        stmt = (
            sa.insert(services_table)
            .values(
                organization_id=str(organization_id),
                name=name,
                kind=kind,
                language=language,
                description=description,
                created_by_user_id=created_by_user_id,
            )
            .returning(services_table)
        )
        try:
            result = await self._session.execute(stmt)
        except sa.exc.IntegrityError as exc:
            # services_org_name_uniq -- the only UNIQUE constraint this
            # table has, so any IntegrityError here means that one.
            await self._session.rollback()
            raise ServiceAlreadyExistsError(name) from exc
        row = result.mappings().first()
        assert row is not None  # INSERT ... RETURNING always returns the inserted row on success.
        await self._session.commit()
        return row
