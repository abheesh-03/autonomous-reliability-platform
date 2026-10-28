"""Database access for reliability.telemetry_samples (Phase 16 Gate
4/5). Same bare `sa.table()`/`sa.column()` Core-table convention every
other repository in this service already uses.

Every query below is organization-scoped AND bounded by a time window
-- there is no method here that returns an unbounded scan, and no
method that omits the organization_id filter. This is the entire
real isolation mechanism for externally submitted telemetry (see
V14's own migration docstring and docs/architecture/phase-16-secure-
telemetry-onboarding.md's "Gate 1" audit) -- never a Prometheus/Tempo/
Loki label.

CORRECTION ROUND (independent review):
  - item 5: `insert_batch` now durably deduplicates retried DELTA
    observations via a real PostgreSQL `ON CONFLICT ... DO NOTHING`,
    matching the unique index V16 adds
    (database/migrations/V16__add_telemetry_sample_dedup_key.sql) on
    the data point's own stable timeseries identity (service, the
    accepted interval's own end timestamp, and its attribute set).
    Retrying the EXACT same export is now a true no-op (the retried
    rows are silently skipped, not stored twice); a genuinely distinct
    interval (a different `observed_at`) is unaffected.
  - item 4: `get_window_aggregate` no longer computes `percentile_cont`
    over each row's own per-interval MEAN duration (that was a
    percentile of batch averages, not a request-level percentile --
    see domain/telemetry.py's own `TelemetrySummary` docstring for the
    full reasoning). It now returns one correctly-weighted
    `mean_latency_seconds = SUM(duration_sum_seconds) / SUM(request_count)`
    across the window instead.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

telemetry_samples_table = sa.table(
    "telemetry_samples",
    sa.column("id"),
    sa.column("organization_id", PG_UUID(as_uuid=True)),
    sa.column("service_id", PG_UUID(as_uuid=True)),
    sa.column("integration_credential_id", PG_UUID(as_uuid=True)),
    sa.column("observed_at"),
    sa.column("received_at"),
    sa.column("http_method"),
    sa.column("http_route"),
    sa.column("http_status_code"),
    sa.column("request_count"),
    sa.column("duration_sum_seconds"),
    sa.column("is_error"),
    schema="reliability",
)


class TelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_batch(
        self,
        *,
        organization_id: uuid.UUID | str,
        service_id: uuid.UUID | str,
        integration_credential_id: uuid.UUID | str,
        points: Sequence[Mapping],
    ) -> int:
        """Inserts every point in ONE statement/transaction --
        all-or-nothing (Gate 4: a partially-malformed batch never
        leaves a partial write; ingestion/telemetry_service.py already
        filtered out individually-invalid points before this is ever
        called) -- EXCEPT that a point which exactly matches an
        already-stored point's stable timeseries identity (item 5) is
        silently skipped as a duplicate, never stored twice. Returns
        the number of rows actually, newly inserted (never counting a
        deduplicated retry)."""
        if not points:
            return 0
        rows = [
            {
                "organization_id": str(organization_id),
                "service_id": str(service_id),
                "integration_credential_id": str(integration_credential_id),
                **point,
            }
            for point in points
        ]
        # The stable timeseries identity a retried DELTA export must
        # collide on: which service, which exact accepted interval
        # (the data point's own `observed_at` end timestamp), and which
        # attribute set -- COALESCE normalizes NULL attributes to a
        # fixed sentinel so two "no attributes" points are correctly
        # treated as the same timeseries (plain SQL NULL would
        # otherwise never equal itself for uniqueness purposes, letting
        # that one combination bypass dedup entirely).
        #
        # Must match V16's own unique index expressions EXACTLY, at the
        # literal SQL text level, not merely in effect -- Postgres's
        # `ON CONFLICT` inference requires the given expressions to be
        # byte-for-byte identical to an existing index's own
        # expressions. `sa.text("''")`/`sa.text("-1")` (not a plain
        # Python `""`/`-1`) are required here: SQLAlchemy would
        # otherwise compile a bare Python literal as a BOUND PARAMETER
        # (`coalesce(http_method, $11)`), which Postgres does NOT
        # recognize as matching V16's own `COALESCE(http_method, '')`
        # (a literal constant) -- a real bug this round's own
        # real-PostgreSQL verification found: every ingestion request
        # failed with "there is no unique or exclusion constraint
        # matching the ON CONFLICT specification" / HTTP 503 before
        # this fix, despite 463 unit tests (which use an in-memory
        # fake with no real SQL compilation) passing throughout.
        dedup_index_elements = [
            telemetry_samples_table.c.service_id,
            telemetry_samples_table.c.observed_at,
            sa.func.coalesce(telemetry_samples_table.c.http_method, sa.text("''")),
            sa.func.coalesce(telemetry_samples_table.c.http_route, sa.text("''")),
            sa.func.coalesce(telemetry_samples_table.c.http_status_code, sa.text("-1")),
        ]
        stmt = (
            pg_insert(telemetry_samples_table)
            .values(rows)
            .on_conflict_do_nothing(index_elements=dedup_index_elements)
            .returning(telemetry_samples_table.c.id)
        )
        result = await self._session.execute(stmt)
        inserted_count = len(result.fetchall())
        await self._session.commit()
        return inserted_count

    async def get_window_aggregate(
        self,
        *,
        organization_id: uuid.UUID | str,
        service_id: uuid.UUID | str,
        since: datetime,
        until: datetime,
    ) -> Mapping:
        """ONE bounded, indexed, organization-and-service-scoped
        aggregate query -- request/error counts and mean latency are
        computed here, server-side, never fetched as raw rows and
        aggregated in Python (Phase 15 Gate 10's own "server-side
        aggregates" convention, extended to this new signal).

        `mean_latency_seconds` (item 4) is a single, correctly-weighted
        mean -- `SUM(duration_sum_seconds) / SUM(request_count)` over
        every real request in the window -- never a percentile. See
        domain/telemetry.py's `TelemetrySummary` docstring for why a
        percentile over this table's own per-row MEANS would
        misrepresent what it measures."""
        total_request_count = sa.func.sum(telemetry_samples_table.c.request_count)
        total_duration_sum = sa.func.sum(telemetry_samples_table.c.duration_sum_seconds)
        mean_latency_seconds = sa.case(
            (total_request_count > 0, total_duration_sum / total_request_count),
            else_=None,
        )
        stmt = sa.select(
            sa.func.coalesce(total_request_count, 0).label("request_count"),
            sa.func.coalesce(
                sa.func.sum(
                    sa.case((telemetry_samples_table.c.is_error.is_(True), telemetry_samples_table.c.request_count), else_=0)
                ),
                0,
            ).label("error_count"),
            sa.func.max(telemetry_samples_table.c.observed_at).label("last_observed_at"),
            mean_latency_seconds.label("mean_latency_seconds"),
        ).where(
            telemetry_samples_table.c.organization_id == str(organization_id),
            telemetry_samples_table.c.service_id == str(service_id),
            telemetry_samples_table.c.observed_at >= since,
            telemetry_samples_table.c.observed_at < until,
        )
        row = (await self._session.execute(stmt)).mappings().first()
        assert row is not None
        return row

    async def get_last_observed_at(
        self, *, organization_id: uuid.UUID | str, service_id: uuid.UUID | str
    ) -> datetime | None:
        """Unbounded-by-time but still organization/service-scoped and
        a single MAX() over an indexed column -- used only to
        distinguish CONFIGURED_AWAITING_DATA (never received anything,
        ever) from STALE_DATA (received something, just not recently)
        when the bounded window above is empty."""
        stmt = sa.select(sa.func.max(telemetry_samples_table.c.observed_at)).where(
            telemetry_samples_table.c.organization_id == str(organization_id),
            telemetry_samples_table.c.service_id == str(service_id),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
