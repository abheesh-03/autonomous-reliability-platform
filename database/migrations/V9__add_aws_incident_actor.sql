-- Phase 13: widens reliability.incident_events' actor_type vocabulary
-- to include 'aws' -- the new, authenticated AWS finding-ingestion
-- path (control_plane/api/aws.py) creates/observes incidents exactly
-- like the Kubernetes finding-ingestion path (Phase 12B-D), and needs
-- its own, distinct actor_type so an incident's audit trail honestly
-- records WHICH source actually caused each 'created'/'observed'
-- event -- never misattributed to 'alertmanager' or 'kubernetes'.
--
-- NEVER modifies V1-V8 -- all eight are already applied to the real
-- local development database, and editing any of them would
-- invalidate Flyway's recorded checksum for it. Purely additive DDL:
-- drops and recreates exactly the same three CHECK constraints
-- V8__add_kubernetes_incident_actor.sql already widened once, widening
-- each again to also accept 'aws'. Constraint names confirmed
-- empirically against a real, freshly migrated (V1-V8) database before
-- writing this migration.
--
-- AWS-sourced ingestion deliberately NEVER produces a
-- 'status_transition' event, for the exact same reason Kubernetes-
-- sourced ingestion does not (Gate 4: "Never resolve an incident
-- merely because an alarm disappears or a source returns an empty
-- response" -- incident resolution requires independent current-state
-- verification via the authenticated operator lifecycle endpoint
-- only). incident_events_status_transition_shape is therefore left
-- EXCLUDING both 'kubernetes' and 'aws', unchanged from V8.

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_actor_type_check,
    ADD CONSTRAINT incident_events_actor_type_check
        CHECK (actor_type IN ('alertmanager', 'operator', 'kubernetes', 'aws'));

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_created_shape,
    ADD CONSTRAINT incident_events_created_shape
        CHECK (
            event_type <> 'created'
            OR (previous_status IS NULL AND new_status = 'open' AND actor_type IN ('alertmanager', 'kubernetes', 'aws'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_observed_shape,
    ADD CONSTRAINT incident_events_observed_shape
        CHECK (
            event_type <> 'observed'
            OR (previous_status IS NOT NULL AND previous_status = new_status AND actor_type IN ('alertmanager', 'kubernetes', 'aws'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_status_transition_shape,
    ADD CONSTRAINT incident_events_status_transition_shape
        CHECK (
            event_type <> 'status_transition'
            OR (previous_status IS NOT NULL AND previous_status <> new_status AND actor_type IN ('alertmanager', 'operator'))
        );
