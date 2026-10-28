-- Phase 16 independent security/protocol correction round, item 5:
-- durable deduplication for retried DELTA telemetry exports.
--
-- ADDITIVE ONLY -- V1 through V15 are never edited (V13-V15 were
-- already applied to at least one developer database before this
-- migration was written; editing any of them in place would silently
-- break Flyway's own checksum verification on that database).
--
-- A real OTel exporter's "at-least-once" delivery contract means the
-- EXACT same export (the same DELTA interval, for the same timeseries)
-- can legitimately arrive more than once -- a client retry after a
-- timed-out response whose request actually succeeded, for example.
-- Before this migration, control_plane.repositories.telemetry_repository
-- stored every row it was given, so a retried export inflated
-- request_count/duration_sum_seconds (and therefore the dashboard's
-- request-rate/error-rate/mean-latency numbers, and the incident
-- detector's own window aggregate) exactly as if it were new, distinct
-- traffic.
--
-- A single accepted data point's stable timeseries identity is: which
-- service, which exact DELTA interval (its own `observed_at` end
-- timestamp -- two genuinely distinct intervals always have distinct
-- end timestamps), and which attribute set (http_method/http_route/
-- http_status_code). COALESCE normalizes a NULL attribute to a fixed
-- sentinel value so two "no attributes present" points are correctly
-- treated as the SAME timeseries for uniqueness purposes -- plain SQL
-- NULL is never equal to itself in a unique index, which would
-- otherwise let that one combination bypass dedup entirely.
--
-- This must be a plain UNIQUE INDEX (not an ADD CONSTRAINT ... UNIQUE,
-- which Postgres only accepts over bare column references, never
-- expressions like COALESCE) so repositories/telemetry_repository.py
-- can use a real `INSERT ... ON CONFLICT (<these exact expressions>)
-- DO NOTHING` -- Postgres matches an ON CONFLICT inference clause
-- against any unique index (constraint-backed or not) whose
-- expressions match exactly.
CREATE UNIQUE INDEX telemetry_samples_dedup_idx
    ON reliability.telemetry_samples (
        service_id,
        observed_at,
        COALESCE(http_method, ''),
        COALESCE(http_route, ''),
        COALESCE(http_status_code, -1)
    );
