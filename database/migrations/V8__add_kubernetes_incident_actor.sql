-- Phase 12B-D: widens reliability.incident_events' actor_type
-- vocabulary to include 'kubernetes' -- the new, authenticated
-- Kubernetes finding-ingestion path (control_plane/api/kubernetes.py)
-- creates/observes incidents exactly like Alertmanager's existing
-- ingestion path, and needs its own, distinct actor_type so an
-- incident's audit trail honestly records WHICH source actually
-- caused each 'created'/'observed' event -- never misattributed to
-- 'alertmanager'.
--
-- NEVER modifies V1-V7 -- all seven are already applied to the real
-- local development database, and editing any of them would
-- invalidate Flyway's recorded checksum for it. Purely additive DDL:
-- drops and recreates exactly the three CHECK constraints that
-- hardcoded 'alertmanager' as the only legal actor for a
-- 'created'/'observed' event, widening each to also accept
-- 'kubernetes'. Constraint names confirmed empirically against a real,
-- freshly migrated (V1-V7) database before writing this migration.
--
-- Kubernetes-sourced ingestion deliberately NEVER produces a
-- 'status_transition' event -- Gate 2's own requirement that
-- "incident resolution must require independent current-state
-- verification" means the Kubernetes ingestion path only ever
-- creates/observes an incident, never resolves or otherwise
-- transitions one; that remains exclusively the authenticated
-- operator lifecycle endpoint's job (api/incidents.py,
-- CONTROL_PLANE_LIFECYCLE_TOKEN), unchanged by this phase. Unlike
-- 'created'/'observed' above, this is enforced as a hard DATABASE
-- constraint, not merely an application-code discipline:
-- incident_events_status_transition_shape is widened here too, to
-- explicitly EXCLUDE 'kubernetes' from the set of valid actors for
-- that event_type (a plain CHECK (actor_type IN (...)) with 'kubernetes'
-- left out, the mirror image of the widening below).

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_actor_type_check,
    ADD CONSTRAINT incident_events_actor_type_check
        CHECK (actor_type IN ('alertmanager', 'operator', 'kubernetes'));

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_created_shape,
    ADD CONSTRAINT incident_events_created_shape
        CHECK (
            event_type <> 'created'
            OR (previous_status IS NULL AND new_status = 'open' AND actor_type IN ('alertmanager', 'kubernetes'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_observed_shape,
    ADD CONSTRAINT incident_events_observed_shape
        CHECK (
            event_type <> 'observed'
            OR (previous_status IS NOT NULL AND previous_status = new_status AND actor_type IN ('alertmanager', 'kubernetes'))
        );

ALTER TABLE reliability.incident_events
    DROP CONSTRAINT incident_events_status_transition_shape,
    ADD CONSTRAINT incident_events_status_transition_shape
        CHECK (
            event_type <> 'status_transition'
            OR (previous_status IS NOT NULL AND previous_status <> new_status AND actor_type IN ('alertmanager', 'operator'))
        );
