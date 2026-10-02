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
from sqlalchemy.dialects.postgresql import JSONB
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

# Phase 3E: see database/migrations/V3__create_incident_audit.sql.
# `metadata` is the one column given an explicit type (JSONB) rather
# than left bare like every other column above — SQLAlchemy/asyncpg
# need that type information to serialize a Python dict into the
# column correctly; every other column's type is inferred fine from
# untyped bind parameters.
incident_events_table = sa.table(
    "incident_events",
    sa.column("id"),
    sa.column("incident_id"),
    sa.column("event_type"),
    sa.column("actor_type"),
    sa.column("previous_status"),
    sa.column("new_status"),
    sa.column("occurred_at"),
    sa.column("metadata", JSONB),
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

        Phase 3E: also records the matching audit event — 'created'
        (previous_status=NULL, new_status='open') for a genuine new
        row, or 'observed' (previous_status == new_status, the row's
        own actual current status) for an accepted update to an
        already-active incident — in the SAME statement's own
        transaction, using `status` straight from this UPSERT's own
        RETURNING clause. This is safe without any extra read/lock:
        this statement's SET clause never touches `status` at all
        (on conflict, see above), so the value RETURNING reports is
        simultaneously correct as both "previous" and "new" status —
        there is no window in which it could be stale.
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
        ).returning(
            incidents_table.c.id,
            incidents_table.c.status,
            sa.literal_column("(xmax = 0)").label("created"),
        )

        result = await self._session.execute(upsert_stmt)
        row = result.mappings().one()
        incident_id = row["id"]
        created = bool(row["created"])
        status = row["status"]

        # Allowlisted, structured metadata only — the alert's own
        # fingerprint and the observation's own startsAt. Never the
        # Authorization header, the Bearer token, or the raw webhook
        # payload — see docs/architecture/phase-3e-incident-audit.md.
        metadata = {
            "source_fingerprint": source_fingerprint,
            "observed_starts_at": occurrence_starts_at.isoformat(),
        }
        await self._record_event(
            incident_id,
            event_type="created" if created else "observed",
            actor_type="alertmanager",
            previous_status=None if created else status,
            new_status=status,
            metadata=metadata,
        )

        return incident_id, created

    async def commit(self) -> None:
        await self._session.commit()

    # ------------------------------------------------------------------
    # Phase 3E: incident audit trail. `_record_event` is deliberately
    # private — every audit record is written as a direct consequence
    # of an accepted mutation this repository itself already performs
    # (upsert_firing_incident, transition_incident_status,
    # resolve_active_incident_for_fingerprint below), using the exact
    # same `self._session` and therefore the exact same transaction as
    # that mutation. There is no separate public write path for audit
    # events — see docs/architecture/phase-3e-incident-audit.md: no
    # audit-creation endpoint exists, and none is planned. If this
    # INSERT raises for any reason, it propagates to the caller exactly
    # like any other repository exception; neither this repository nor
    # its callers ever swallow it or call commit() afterward — the
    # whole transaction (the mutation AND this record) rolls back
    # together when the session closes without a commit.
    # ------------------------------------------------------------------

    async def _record_event(
        self,
        incident_id: uuid.UUID,
        *,
        event_type: str,
        actor_type: str,
        previous_status: str | None,
        new_status: str,
        metadata: Mapping[str, object],
    ) -> None:
        stmt = sa.insert(incident_events_table).values(
            incident_id=incident_id,
            event_type=event_type,
            actor_type=actor_type,
            previous_status=previous_status,
            new_status=new_status,
            metadata=dict(metadata),
        )
        await self._session.execute(stmt)

    async def get_incident_events(
        self,
        incident_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Mapping], int]:
        """GET /api/v1/incidents/{id}/events's own query: this
        incident's full timeline, oldest first, with a deterministic
        tie-breaker (occurred_at is not guaranteed unique — two events
        for the same incident can share a timestamp, e.g. within the
        same transaction). Returns an empty page (and total=0) for an
        incident that genuinely has no recorded history yet — a
        pre-Phase-3E incident, or one that has only ever been read, not
        mutated — which is valid, expected behavior, not an error. This
        method itself never checks whether `incident_id` exists at
        all; the caller (api/incidents.py) does that separately via
        get_by_id() to distinguish 404 from a real, empty timeline.
        """
        total_stmt = (
            sa.select(sa.func.count())
            .select_from(incident_events_table)
            .where(incident_events_table.c.incident_id == incident_id)
        )
        total = (await self._session.execute(total_stmt)).scalar_one()

        page_stmt = (
            sa.select(incident_events_table)
            .where(incident_events_table.c.incident_id == incident_id)
            .order_by(incident_events_table.c.occurred_at.asc(), incident_events_table.c.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(page_stmt)
        rows = result.mappings().all()
        return rows, total

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

        Phase 3E: on a genuine (non-zero-row) transition, also records
        the matching 'status_transition' audit event, actor_type
        'operator', in this exact same statement's transaction.
        `expected_status` is already the ACTUAL previous status with
        no staleness risk at all — not because of any extra locking
        here, but because this UPDATE's own WHERE clause is what
        guarantees it: zero rows would have been affected (and this
        branch never reached) if the row's real status had been
        anything else at the moment this statement ran. No event is
        recorded when zero rows are affected (api/incidents.py then
        reports 404 or a stale-expected_status 409, neither of which
        is a real mutation).
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
        row = result.mappings().first()
        if row is not None:
            await self._record_event(
                incident_id,
                event_type="status_transition",
                actor_type="operator",
                previous_status=expected_status,
                new_status=target_status,
                metadata={},
            )
        return row

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
        check). Race-free against a concurrent operator PATCH resolving
        or otherwise transitioning the very same row: whichever commits
        first wins, the other affects zero rows. The caller treats zero
        rows as an idempotent no-op (the incident was already resolved/
        closed by the time this ran), never an error — see
        ingestion/service.py.

        Phase 3E: this method also records the matching
        'status_transition' audit event, actor_type 'alertmanager'.
        Unlike transition_incident_status above, the caller here
        (ingestion/service.py) does NOT already know which specific
        active status (open/acknowledged/investigating/remediating)
        this incident currently holds -- only that get_active_incident
        found some active row, moments earlier. Reading that earlier
        snapshot's status here would risk recording a STALE previous
        status if a concurrent operator PATCH changed it in the
        meantime (e.g. open -> acknowledged) between that read and this
        resolution -- exactly the staleness this phase must avoid. So
        this is deliberately TWO statements, not one, both inside this
        same method/session/transaction: first, SELECT ... FOR UPDATE
        takes a real row lock and reads the status as of THIS moment;
        then the UPDATE (guaranteed to match, since the lock prevents
        any other writer from having changed it in between) applies the
        resolution, and this method records the event using that
        just-locked, genuinely current value. The advisory fingerprint
        lock (acquire_fingerprint_lock) already serializes concurrent
        *webhook* deliveries for this fingerprint before any of this
        runs, but it does nothing against a concurrent *operator* PATCH
        racing on the same row by id -- this row-level FOR UPDATE lock
        is what closes that specific gap.
        """
        lock_stmt = (
            sa.select(incidents_table.c.status)
            .where(
                incidents_table.c.id == incident_id,
                incidents_table.c.status.not_in(["resolved", "closed"]),
            )
            .with_for_update()
        )
        locked = (await self._session.execute(lock_stmt)).mappings().first()
        if locked is None:
            return None
        previous_status = locked["status"]

        update_stmt = (
            sa.update(incidents_table)
            .where(incidents_table.c.id == incident_id, incidents_table.c.status == previous_status)
            .values(status="resolved", resolved_at=resolved_at)
            .returning(incidents_table)
        )
        result = await self._session.execute(update_stmt)
        row = result.mappings().first()
        if row is None:
            # Not expected to be reachable -- the row lock held since
            # the SELECT above should make this WHERE clause always
            # match -- but handled defensively rather than assumed
            # impossible.
            return None

        await self._record_event(
            incident_id,
            event_type="status_transition",
            actor_type="alertmanager",
            previous_status=previous_status,
            new_status="resolved",
            metadata={"resolution_source": "alertmanager_webhook"},
        )
        return row
