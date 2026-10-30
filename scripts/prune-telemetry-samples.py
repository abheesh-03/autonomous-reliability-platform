#!/usr/bin/env python3
"""prune-telemetry-samples.py — Phase 17A item 6: bounded, batched
retention for `reliability.telemetry_samples` ONLY.

Never touches `reliability.incidents`, the real, trigger-enforced
append-only `reliability.incident_events`/`reliability.remediation_events`,
`reliability.integration_credentials`, `reliability.services`,
`reliability.retrieval_chunks`, or anything in the `auth`/
`agent_runtime` schemas — this script issues exactly one DELETE
statement shape, against exactly one table, for its entire lifetime.

Connects with the same individual-environment-variable convention
every other Python service in this repository already uses (see
services/control-plane/src/control_plane/core/config.py's own
`DatabaseSettings.from_env`) — POSTGRES_HOST/POSTGRES_PORT (falls back
to POSTGRES_INTERNAL_PORT, matching that same file, then 5432)/
POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB. In a real deployment
(deploy/docker-compose.override.yml's `retention-scheduler` service)
POSTGRES_USER/POSTGRES_PASSWORD are the least-privileged
`control_plane_app` role (deploy/sql/01-create-runtime-roles.sql.template)
— this script needs, and that role grants, exactly SELECT+DELETE on
`reliability.telemetry_samples`, nothing broader.

Uses `asyncpg` directly (no SQLAlchemy/ORM) — this is a short,
single-purpose script with one real query shape; every other
Python service in this repository that talks to Postgres without an
ORM (retrieval-service) already uses asyncpg directly too, so this
introduces no new library choice, just reuses the existing one at its
existing pinned version (asyncpg==0.31.0).

Modes:
  (no flag)   dry run — reports what WOULD be deleted, deletes nothing.
  --execute   performs the real, batched deletion.

Batching/runtime bound: deletes at most TELEMETRY_RETENTION_BATCH_SIZE
rows per statement, looping until either no more rows match the
cutoff or MAX_BATCHES_PER_RUN batches have run (a real, hard bound —
never an unbounded single transaction, and never an unbounded single
process invocation against a huge backlog). A backlog larger than one
run can clear is completely normal and expected to be finished across
several scheduled ticks (deploy/scripts/retention-loop.sh runs this
once every TELEMETRY_RETENTION_INTERVAL_HOURS) — this script reports
that honestly (see the "backlog remains" log line) rather than
pretending one run always finishes.

Exit codes: 0 on success (dry run or execute, including a run that
only partially drains a large backlog — that is not a failure, see
above), non-zero on any real error (connection failure, permission
error, a batch failing) — deploy/scripts/retention-loop.sh's own
"observable failure path" greps this exit code, not stdout text.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import asyncpg

TABLE = "reliability.telemetry_samples"

# A hard ceiling on how many batches ONE invocation will run, so a
# single process can never run forever against an enormous backlog —
# the scheduler's own next tick (TELEMETRY_RETENTION_INTERVAL_HOURS)
# picks up wherever this run left off. At the default batch size
# (5000) this bounds one run to at most 500,000 deleted rows.
MAX_BATCHES_PER_RUN = 100

# A hard wall-clock ceiling per invocation, independent of batch
# count, in case individual batches are unexpectedly slow (e.g. lock
# contention) — belt-and-suspenders alongside MAX_BATCHES_PER_RUN.
#
# CORRECTION ROUND -- real finding: this was previously only ever
# CHECKED between loop iterations (at the top of the `while` loop in
# `run()`), never enforced on any individual operation. A connection
# attempt that hangs, the initial/final COUNT queries, or -- the real
# fault-injected case -- a single DELETE blocked indefinitely behind
# another transaction's lock on this table could each exceed this
# "ceiling" without limit, since nothing ever interrupted them. Fixed
# by giving every operation its OWN real, enforced timeout:
# `asyncpg.connect(..., timeout=...)` bounds the connection attempt,
# and a session-level Postgres `statement_timeout` (set immediately
# after connecting, server_settings is applied before this
# connection runs ANY query) bounds every single SQL statement on
# this connection for its entire lifetime -- including, specifically,
# time spent WAITING for a lock, which Postgres counts as part of
# statement execution for this setting's purposes. This is what
# actually makes "no single operation can hang forever" true, rather
# than merely a claim.
CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_SECONDS = 30
MAX_RUNTIME_SECONDS = 300


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    """Reads a positive, bounded integer from the environment.
    CORRECTION ROUND: previously accepted ANY integer, including
    negative/zero values -- a negative TELEMETRY_RETENTION_DAYS
    computes a cutoff in the FUTURE, matching almost every row
    (including ones written seconds ago) instead of only stale ones,
    a real near-total-data-loss risk if ever misconfigured. Fails
    loudly (raises, caught by `run()` and reported as a FAIL: exit 1)
    rather than silently proceeding with a nonsensical value --
    belt-and-suspenders alongside deploy/scripts/preflight.sh's own
    identical deploy-time check, in case this script is ever invoked
    directly or the environment changes between preflight and
    execution."""
    raw = os.environ.get(name, "").strip()
    value = int(raw) if raw else default
    if not (minimum <= value <= maximum):
        raise ValueError(f"{name}={value!r} is out of the required bounds [{minimum}, {maximum}]")
    return value


async def _connect() -> asyncpg.Connection:
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = int(os.environ.get("POSTGRES_PORT") or os.environ.get("POSTGRES_INTERNAL_PORT") or "5432")
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    database = os.environ["POSTGRES_DB"]
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        timeout=CONNECT_TIMEOUT_SECONDS,
        server_settings={"statement_timeout": str(STATEMENT_TIMEOUT_SECONDS * 1000)},
    )
    return conn


async def _count_eligible(conn: asyncpg.Connection, cutoff: datetime) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {TABLE} WHERE observed_at < $1", cutoff)


async def _count_eligible_by_org(conn: asyncpg.Connection, cutoff: datetime) -> list[tuple[str, str, int]]:
    rows = await conn.fetch(
        f"""
        SELECT organization_id::text, service_id::text, count(*) AS n
        FROM {TABLE}
        WHERE observed_at < $1
        GROUP BY organization_id, service_id
        ORDER BY n DESC
        """,
        cutoff,
    )
    return [(r["organization_id"], r["service_id"], r["n"]) for r in rows]


async def _delete_one_batch(conn: asyncpg.Connection, cutoff: datetime, batch_size: int) -> int:
    """Deletes at most `batch_size` eligible rows in ONE bounded
    statement/transaction and returns how many were actually deleted.
    The inner SELECT ... LIMIT bounds the batch; the outer DELETE ...
    WHERE id IN (...) is the only statement that ever touches this
    table's rows anywhere in this script."""
    rows = await conn.fetch(
        f"""
        DELETE FROM {TABLE}
        WHERE id IN (
            SELECT id FROM {TABLE} WHERE observed_at < $1 ORDER BY id LIMIT $2
        )
        RETURNING id
        """,
        cutoff,
        batch_size,
    )
    return len(rows)


async def run(execute: bool) -> int:
    try:
        # Bounds match deploy/scripts/preflight.sh's own identical
        # deploy-time check exactly (see validate_positive_int()
        # there) -- this is the SAME script's own defense in depth,
        # not a second, independently-drifting policy.
        retention_days = _env_int("TELEMETRY_RETENTION_DAYS", 30, minimum=1, maximum=3650)
        batch_size = _env_int("TELEMETRY_RETENTION_BATCH_SIZE", 5000, minimum=1, maximum=100_000)
    except ValueError as exc:
        print(f"FAIL: invalid retention configuration: {exc}", file=sys.stderr)
        return 1
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    started = time.monotonic()

    try:
        conn = await _connect()
    except Exception as exc:  # noqa: BLE001 - any connection failure must exit non-zero with a clear message
        print(f"FAIL: could not connect to the database: {exc}", file=sys.stderr)
        return 1

    try:
        total_eligible = await _count_eligible(conn, cutoff)
        print(
            f"[prune-telemetry-samples] cutoff={cutoff.isoformat()} "
            f"(TELEMETRY_RETENTION_DAYS={retention_days}) eligible_rows={total_eligible}"
        )

        breakdown = await _count_eligible_by_org(conn, cutoff)
        for org_id, service_id, n in breakdown[:20]:
            print(f"[prune-telemetry-samples]   organization_id={org_id} service_id={service_id} rows={n}")
        if len(breakdown) > 20:
            print(f"[prune-telemetry-samples]   ... and {len(breakdown) - 20} more organization/service group(s)")

        if not execute:
            print(f"[prune-telemetry-samples] DRY RUN -- would delete {total_eligible} row(s); deleted 0")
            return 0

        if total_eligible == 0:
            print("[prune-telemetry-samples] nothing to delete")
            return 0

        deleted_total = 0
        batches_run = 0
        while batches_run < MAX_BATCHES_PER_RUN:
            if time.monotonic() - started > MAX_RUNTIME_SECONDS:
                print(
                    f"[prune-telemetry-samples] stopping: MAX_RUNTIME_SECONDS "
                    f"({MAX_RUNTIME_SECONDS}s) reached after {batches_run} batch(es)"
                )
                break
            deleted_this_batch = await _delete_one_batch(conn, cutoff, batch_size)
            batches_run += 1
            deleted_total += deleted_this_batch
            print(
                f"[prune-telemetry-samples] batch {batches_run}: deleted {deleted_this_batch} row(s) "
                f"(running total {deleted_total})"
            )
            if deleted_this_batch < batch_size:
                # Fewer rows than the batch size means this was the
                # last batch -- nothing more matches the cutoff.
                break

        remaining = await _count_eligible(conn, cutoff)
        duration = time.monotonic() - started
        print(
            f"[prune-telemetry-samples] done in {duration:.2f}s: deleted {deleted_total} row(s) across "
            f"{batches_run} batch(es); {remaining} eligible row(s) remain for a future run"
            if remaining
            else f"[prune-telemetry-samples] done in {duration:.2f}s: deleted {deleted_total} row(s) across "
            f"{batches_run} batch(es); backlog fully cleared"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - any batch/query failure must exit non-zero with a clear message
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="perform the real, batched deletion (default: dry run only)"
    )
    args = parser.parse_args()
    return asyncio.run(run(execute=args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
