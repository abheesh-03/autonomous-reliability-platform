"""Database access for reliability.incidents.

Deliberately NOT an ORM-mapped declarative model: `sa.table()`/
`sa.column()` build a bare, metadata-free Core table expression usable
only for constructing SELECT statements — there is no `Table.create()`,
no `metadata.create_all()`, and no schema-management capability
attached to it at all. The schema is owned exclusively by Flyway
(database/migrations/); this module only ever reads it, with real
parameter binding throughout (every `.where(...)` comparison below is
bound, not string-interpolated), so there is no SQL injection surface.

Route handlers (control_plane/api/incidents.py) call this repository
rather than building their own queries or SQLAlchemy engines.
"""

import uuid
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# Column list matches database/migrations/V1__create_incident_schema.sql
# exactly.
incidents_table = sa.table(
    "incidents",
    sa.column("id"),
    sa.column("source"),
    sa.column("source_fingerprint"),
    sa.column("title"),
    sa.column("description"),
    sa.column("severity"),
    sa.column("status"),
    sa.column("first_seen_at"),
    sa.column("last_seen_at"),
    sa.column("resolved_at"),
    sa.column("created_at"),
    sa.column("updated_at"),
    schema="reliability",
)


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_incidents(
        self,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Mapping], int]:
        filters = []
        if status is not None:
            filters.append(incidents_table.c.status == status)
        if severity is not None:
            filters.append(incidents_table.c.severity == severity)
        if source is not None:
            filters.append(incidents_table.c.source == source)

        base = sa.select(incidents_table)
        if filters:
            base = base.where(sa.and_(*filters))

        # total reflects every matching row BEFORE pagination is
        # applied — a separate COUNT over the same filtered base query,
        # not the length of the (already limited) page of rows.
        total_stmt = sa.select(sa.func.count()).select_from(base.subquery())
        total = (await self._session.execute(total_stmt)).scalar_one()

        # Deterministic ordering, as required: ties on last_seen_at
        # (plausible with coarse timestamps or bulk-inserted test data)
        # are broken by id, so the same query always returns the same
        # order/page boundaries.
        page_stmt = (
            base.order_by(incidents_table.c.last_seen_at.desc(), incidents_table.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(page_stmt)
        rows = result.mappings().all()
        return rows, total

    async def get_by_id(self, incident_id: uuid.UUID) -> Mapping | None:
        stmt = sa.select(incidents_table).where(incidents_table.c.id == incident_id)
        result = await self._session.execute(stmt)
        return result.mappings().first()
