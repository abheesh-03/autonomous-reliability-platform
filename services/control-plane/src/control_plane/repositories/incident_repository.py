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
    # Phase 3D (post-review correction): see
    # database/migrations/V2__add_occurrence_watermark.sql and
    # docs/architecture/phase-3d-incident-lifecycle.md. Deliberately
    # NOT exposed on the public Incident response model (domain/incident.py)
    # — this is internal occurrence-identity bookkeeping, not part of
    # the incident resource itself.
    sa.column("occurrence_starts_at"),
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
        occurrence_starts_at: datetime,
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

        `occurrence_starts_at` (Phase 3D post-review correction — see
        database/migrations/V2__add_occurrence_watermark.sql): the
        occurrence-identity watermark. On a genuine new INSERT it
        equals first_seen_at (the same alert's startsAt). On conflict
        it only ever advances (GREATEST against the existing value),
        same tolerance-of-out-of-order-delivery rationale as
        last_seen_at — ingestion/service.py's own decision logic is
        what guarantees this call is only ever made with an
        occurrence_starts_at that is already >= the active row's
        current watermark, but GREATEST here is a defensive second
        layer, not the primary correctness mechanism.

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
            occurrence_starts_at=occurrence_starts_at,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[incidents_table.c.source, incidents_table.c.source_fingerprint],
            index_where=sa.text("status NOT IN ('resolved', 'closed')"),
            set_={
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "severity": insert_stmt.excluded.severity,
                "last_seen_at": sa.func.greatest(incidents_table.c.last_seen_at, insert_stmt.excluded.last_seen_at),
                "occurrence_starts_at": sa.func.greatest(
                    incidents_table.c.occurrence_starts_at, insert_stmt.excluded.occurrence_starts_at
                ),
            },
        ).returning(incidents_table.c.id, sa.literal_column("(xmax = 0)").label("created"))

        result = await self._session.execute(upsert_stmt)
        row = result.mappings().one()
        return row["id"], bool(row["created"])

    async def commit(self) -> None:
        await self._session.commit()

    # ------------------------------------------------------------------
    # Phase 3D: incident lifecycle (manual transitions + Alertmanager-
    # driven automatic resolution).
    # ------------------------------------------------------------------

    async def get_active_incident(self, *, source: str, source_fingerprint: str) -> Mapping | None:
        """At most one row can ever match (incidents_active_fingerprint_uniq,
        Phase 3A) — used by ingestion/service.py to decide whether an
        incoming alert occurrence matches the currently active
        incident for this fingerprint."""
        stmt = sa.select(incidents_table).where(
            incidents_table.c.source == source,
            incidents_table.c.source_fingerprint == source_fingerprint,
            incidents_table.c.status.not_in(["resolved", "closed"]),
        )
        result = await self._session.execute(stmt)
        return result.mappings().first()

    async def get_most_recent_incident(self, *, source: str, source_fingerprint: str) -> Mapping | None:
        """The single most recent incident (by occurrence_starts_at —
        the occurrence watermark, NOT first_seen_at; see
        database/migrations/V2__add_occurrence_watermark.sql — any
        status) for this fingerprint — used to detect a stale/delayed
        firing replay of an occurrence that has already been resolved
        (its occurrence_starts_at will be >= the incoming alert's
        startsAt) versus a genuinely new occurrence (the incoming
        startsAt will be strictly newer). Ordering by the immutable
        first_seen_at here instead would be wrong: a resolved row's
        first_seen_at only reflects when THAT row was first created,
        not the latest occurrence it actually accepted while still
        active, which is exactly the distinction that matters for this
        check — see ingestion/service.py and
        docs/architecture/phase-3d-incident-lifecycle.md."""
        stmt = (
            sa.select(incidents_table)
            .where(
                incidents_table.c.source == source,
                incidents_table.c.source_fingerprint == source_fingerprint,
            )
            .order_by(incidents_table.c.occurrence_starts_at.desc(), incidents_table.c.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.mappings().first()

    async def acquire_fingerprint_lock(self, *, source: str, source_fingerprint: str) -> None:
        """PostgreSQL transaction-scoped advisory lock
        (pg_advisory_xact_lock), automatically released at this
        transaction's COMMIT/ROLLBACK — never needs an explicit unlock.
        Serializes ingestion/service.py's SELECT-then-decide-then-write
        sequence for this exact (source, source_fingerprint) against
        any other concurrent transaction processing the same
        fingerprint (another webhook delivery, a retried delivery, or
        an overlapping batch), which a single atomic UPDATE statement
        alone cannot do for the stale/recurrence DECISION logic (as
        opposed to the decision's resulting write, which — see
        upsert_firing_incident/resolve_active_incident_for_fingerprint
        — is itself always a single atomic statement).

        Keyed by `hashtextextended(...)` of the composite string,
        collapsing (source, source_fingerprint) into the single bigint
        key pg_advisory_xact_lock(key) accepts. Callers processing a
        batch with multiple distinct fingerprints MUST acquire every
        lock they will need up front, in a stable sorted order, before
        doing any work — see ingestion/service.py — to avoid a
        deadlock against another transaction locking the same set of
        fingerprints in a different order.
        """
        key = f"{source}:{source_fingerprint}"
        await self._session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(key, 0))))

    async def transition_incident_status(
        self,
        incident_id: uuid.UUID,
        *,
        expected_status: str,
        target_status: str,
        resolved_at: datetime | None,
    ) -> Mapping | None:
        """The human/operator lifecycle transition (PATCH
        /api/v1/incidents/{id}/status): a single atomic conditional
        UPDATE — `WHERE id = :id AND status = :expected_status` — which
        is PostgreSQL's standard, race-free compare-and-swap pattern,
        not an application-level SELECT-then-UPDATE. Two concurrent
        requests racing from the same expected_status cannot both
        succeed: whichever commits first wins; Postgres takes a
        row-level lock on the first UPDATE, blocking the second until
        the first commits, after which the second's WHERE clause is
        re-evaluated against the now-current row and no longer matches
        (status has already changed) — it affects zero rows rather
        than silently overwriting the first transition. Zero rows
        returned here is ambiguous by design (the id may not exist at
        all, or may exist with a different actual status) — the caller
        (api/incidents.py) resolves that ambiguity with a follow-up
        get_by_id() to choose between 404 and 409.

        `resolved_at`: pass a concrete tz-aware datetime to set it as
        part of this UPDATE (meaningful only when target_status ==
        "resolved"); pass None to leave the column completely
        untouched — every other transition, including resolved ->
        closed, which must preserve the ORIGINAL resolution time, not
        overwrite it with the closure time.
        """
        values: dict[str, object] = {"status": target_status}
        if resolved_at is not None:
            values["resolved_at"] = resolved_at
        stmt = (
            sa.update(incidents_table)
            .where(incidents_table.c.id == incident_id, incidents_table.c.status == expected_status)
            .values(**values)
            .returning(incidents_table)
        )
        result = await self._session.execute(stmt)
        return result.mappings().first()

    async def resolve_active_incident_for_fingerprint(
        self,
        incident_id: uuid.UUID,
        *,
        resolved_at: datetime,
    ) -> Mapping | None:
        """Alertmanager-driven automatic resolution
        (ingestion/service.py): resolves `incident_id` directly to
        'resolved' from WHATEVER active status it currently holds
        (open/acknowledged/investigating/remediating all legally
        transition straight to resolved per the state machine, so no
        separate ALLOWED_TRANSITIONS lookup is needed here — the WHERE
        clause's `status NOT IN ('resolved', 'closed')` already is that
        check). Also a single atomic conditional UPDATE, so it is
        race-free against a concurrent operator PATCH resolving or
        otherwise transitioning the very same row: whichever commits
        first wins, the other affects zero rows. The caller treats zero
        rows as an idempotent no-op (the incident was already resolved/
        closed by the time this ran), never an error — see
        ingestion/service.py.
        """
        stmt = (
            sa.update(incidents_table)
            .where(
                incidents_table.c.id == incident_id,
                incidents_table.c.status.not_in(["resolved", "closed"]),
            )
            .values(status="resolved", resolved_at=resolved_at)
            .returning(incidents_table)
        )
        result = await self._session.execute(stmt)
        return result.mappings().first()
