"""Database access for reliability.incidents.

Deliberately NOT an ORM-mapped declarative model: `sa.table()`/
`sa.column()` build a bare, metadata-free Core table expression usable
only for constructing SELECT/INSERT statements — there is no
`Table.create()`, no `metadata.create_all()`, and no schema-management
capability attached to it at all. The schema is owned exclusively by
Flyway (database/migrations/); this module only ever reads or upserts
individual rows into it, with real parameter binding throughout (every
`.where(...)`/`.values(...)` below is bound, not string-interpolated),
so there is no SQL injection surface.

Route handlers (control_plane/api/incidents.py,
control_plane/api/webhook.py) call this repository rather than
building their own queries or SQLAlchemy engines.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    async def upsert_firing_incident(
        self,
        *,
        source: str,
        source_fingerprint: str,
        title: str,
        description: str | None,
        severity: str,
        first_seen_at: datetime,
        last_seen_at: datetime,
    ) -> tuple[uuid.UUID, bool]:
        """Atomically create-or-update the single ACTIVE incident for
        (source, source_fingerprint) — Phase 3C's real, database-level
        deduplication, not an application-level SELECT-then-INSERT
        race. The ON CONFLICT inference target below
        (index_elements + index_where) deliberately mirrors
        incidents_active_fingerprint_uniq's own partial-index predicate
        from V1__create_incident_schema.sql verbatim
        (`status NOT IN ('resolved', 'closed')`) — PostgreSQL only
        accepts an ON CONFLICT ... WHERE clause as a valid inference
        specification if it matches an existing unique index's
        predicate, so this is not a stylistic choice; it is what makes
        the UPSERT target that specific partial index rather than
        failing with "no unique or exclusion constraint matching the
        ON CONFLICT specification". Expressed via sa.text(...) (a
        literal predicate), not a bound comparison, since Postgres's
        own index-inference matching is on the literal WHERE text.

        On conflict (an active incident already exists for this
        fingerprint): id, first_seen_at, and status are left
        completely untouched; title/description/severity are
        refreshed to this delivery's values (Alertmanager's own
        annotation text can change between deliveries of the same
        firing alert, e.g. if a $value template interpolation
        changes); last_seen_at only ever advances (GREATEST), tolerant
        of any out-of-order delivery. updated_at is maintained by the
        existing incidents_set_updated_at trigger (Phase 3A) on every
        UPDATE, not set here. A resolved/closed historical row for the
        same fingerprint is invisible to this predicate and is never
        touched by this statement at all — a brand new active row is
        inserted instead (also handled by this same statement, since a
        resolved row does not participate in the partial index), which
        is exactly how incident history is preserved rather than
        overwritten.

        Returns (incident_id, created) where created=True only for a
        genuine new INSERT — determined via Postgres's own real
        `xmax = 0` tuple-visibility idiom (true only for a row's own
        inserting transaction), not an application-level flag.
        """
        insert_stmt = pg_insert(incidents_table).values(
            source=source,
            source_fingerprint=source_fingerprint,
            title=title,
            description=description,
            severity=severity,
            status="open",
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[incidents_table.c.source, incidents_table.c.source_fingerprint],
            index_where=sa.text("status NOT IN ('resolved', 'closed')"),
            set_={
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "severity": insert_stmt.excluded.severity,
                "last_seen_at": sa.func.greatest(incidents_table.c.last_seen_at, insert_stmt.excluded.last_seen_at),
            },
        ).returning(incidents_table.c.id, sa.literal_column("(xmax = 0)").label("created"))

        result = await self._session.execute(upsert_stmt)
        row = result.mappings().one()
        return row["id"], bool(row["created"])

    async def commit(self) -> None:
        await self._session.commit()
