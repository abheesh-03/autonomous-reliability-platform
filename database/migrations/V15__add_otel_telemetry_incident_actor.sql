-- Phase 16 Gate 6: widens reliability.incident_events' actor_type
-- vocabulary to include 'otel-telemetry' -- the new, authenticated
-- OpenTelemetry telemetry-threshold detector
-- (control_plane/ingestion/telemetry_threshold_detector.py) creates,
-- observes, AND (unlike the Kubernetes/AWS finding-ingestion paths)
-- genuinely RESOLVES incidents, since a telemetry-derived incident's
-- own triggering condition (an elevated error rate) is something this
-- service can independently re-observe on the very next accepted
-- batch -- unlike a one-shot Kubernetes/AWS finding. Its audit trail
-- must honestly record that this specific, distinct source caused
-- each event -- never misattributed to 'alertmanager' (a different
-- real ingestion path) merely because it reuses the same incident
-- upsert/resolve machinery.
--
-- NEVER modifies V1-V14 -- all fourteen are already applied to the
-- real local development database, and editing any of them would
-- invalidate Flyway's recorded checksum for it. Purely additive DDL:
-- drops and recreates the same four CHECK constraints
-- V8/V9 already widened once each, widening each again to also accept
-- 'otel-telemetry'. Constraint names confirmed empirically against a
-- real, freshly migrated (V1-V14) database before writing this
-- migration.
--
-- Unlike V8/V9 (Kubernetes/AWS, which never resolve an incident
-- themselves), 'otel-telemetry' IS added to
-- incident_events_status_transition_shape's own allowed actor_type
-- list -- this is the one real behavioral difference from those two
-- prior migrations, and is deliberate: see
-- ingestion/telemetry_threshold_detector.py's own module docstring for
-- why a telemetry-derived incident is safe to auto-resolve the same
-- way an Alertmanager-derived one already is (the triggering condition
-- is independently re-observed on every subsequent accepted batch,
-- never inferred from an alert's mere absence).

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_actor_type_check,
    ADD CONSTRAINT incident_events_actor_type_check
        CHECK (actor_type IN ('alertmanager', 'operator', 'kubernetes', 'aws', 'otel-telemetry'));

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_created_shape,
    ADD CONSTRAINT incident_events_created_shape
        CHECK (
            event_type <> 'created'
            OR (previous_status IS NULL AND new_status = 'open' AND actor_type IN ('alertmanager', 'kubernetes', 'aws', 'otel-telemetry'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_observed_shape,
    ADD CONSTRAINT incident_events_observed_shape
        CHECK (
            event_type <> 'observed'
            OR (previous_status IS NOT NULL AND previous_status = new_status AND actor_type IN ('alertmanager', 'kubernetes', 'aws', 'otel-telemetry'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_status_transition_shape,
    ADD CONSTRAINT incident_events_status_transition_shape
        CHECK (
            event_type <> 'status_transition'
            OR (previous_status IS NOT NULL AND previous_status <> new_status AND actor_type IN ('alertmanager', 'operator', 'otel-telemetry'))
        );
