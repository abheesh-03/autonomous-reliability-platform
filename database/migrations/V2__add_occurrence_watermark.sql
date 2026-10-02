-- Phase 3D (post-review correction): occurrence watermark.
--
-- V1 never introduced a second persistent timestamp alongside
-- first_seen_at, so ingestion/service.py's occurrence-identity logic
-- had nothing to compare an incoming alert's startsAt against except
-- first_seen_at itself -- which is set once, at creation, and
-- deliberately never advanced (so a still-pending delayed resolved
-- notification for the ORIGINAL occurrence would keep matching). That
-- is exactly what made it impossible to tell apart, for an incident
-- that is still active after accepting a newer firing observation:
--   - a stale replay of the occurrence it just superseded (must be
--     ignored), from
--   - a genuine, later resolved notification for the occurrence it
--     now represents (must be allowed to resolve it).
-- Independent review reproduced the resulting regression directly: a
-- delayed resolved notification for the ORIGINAL occurrence could
-- incorrectly resolve an incident that had already moved on to a
-- newer, still-unresolved occurrence; and a delayed duplicate firing
-- replay of that newer occurrence, arriving after it finally
-- resolved, could be mistaken for a genuinely new recurrence and spawn
-- a second incident.
--
-- Fix: a second, narrowly-scoped column, occurrence_starts_at, records
-- the LATEST accepted firing startsAt for a fingerprint's row,
-- separately from first_seen_at (which keeps meaning exactly what it
-- always meant: when THIS row was first created). See
-- docs/architecture/phase-3d-incident-lifecycle.md for the full
-- comparison logic this column enables.
--
-- Never touches V1__create_incident_schema.sql. Backfills every
-- existing row's occurrence_starts_at from its own first_seen_at --
-- the correct, safe default: no row inserted before this migration
-- could possibly have had a "latest accepted firing" more recent than
-- its own first_seen_at, since this column (and the logic that
-- advances it) did not exist yet. No existing first_seen_at value is
-- touched by this migration.

ALTER TABLE reliability.incidents
    ADD COLUMN occurrence_starts_at TIMESTAMPTZ;

UPDATE reliability.incidents
    SET occurrence_starts_at = first_seen_at
    WHERE occurrence_starts_at IS NULL;

ALTER TABLE reliability.incidents
    ALTER COLUMN occurrence_starts_at SET NOT NULL;

-- Same invariant first_seen_at/last_seen_at already enforce: the
-- watermark can only ever be at or after the row's own first_seen_at,
-- never before it.
ALTER TABLE reliability.incidents
    ADD CONSTRAINT incidents_occurrence_starts_at_not_before_first_seen
        CHECK (occurrence_starts_at >= first_seen_at);

-- No new index: lookups remain scoped by (source, source_fingerprint)
-- via the existing incidents_active_fingerprint_uniq partial index and
-- incidents_status_idx; per-fingerprint row counts stay low (dedup by
-- design), so ordering a handful of candidate rows by
-- occurrence_starts_at DESC needs no dedicated index, exactly as
-- first_seen_at DESC never needed one either. No Phase 3E
-- audit-history table is introduced here.
