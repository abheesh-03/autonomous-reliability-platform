-- Phase 3E: durable, append-only incident audit trail.
--
-- Never modifies V1__create_incident_schema.sql or
-- V2__add_occurrence_watermark.sql. Adds exactly one new table,
-- reliability.incident_events, recording every ACCEPTED application-
-- level incident mutation (creation, an accepted firing observation,
-- an operator-driven status transition, or Alertmanager's automatic
-- resolution) alongside the incident change itself, in the SAME
-- PostgreSQL transaction — see
-- services/control-plane/src/control_plane/repositories/incident_repository.py
-- and docs/architecture/phase-3e-incident-audit.md for the application
-- side of that guarantee; this migration only establishes the durable
-- storage and its own invariants.
--
-- Honest scope limitation, stated here and not just in documentation:
-- this table is populated going forward, starting with this
-- migration. It is NOT backfilled with invented historical events for
-- incidents (or incident mutations) that predate Phase 3E — there is
-- no reliable source to reconstruct them from, and fabricating history
-- would defeat the entire purpose of an audit trail. A pre-existing
-- incident may legitimately have zero rows here; that is expected,
-- not a bug — see GET /api/v1/incidents/{id}/events.

-- --------------------------------------------------------------------
-- The table
-- --------------------------------------------------------------------
-- Vocabulary:
--   event_type   - what kind of accepted mutation this record is:
--                     created           - a brand-new incident row was inserted
--                     observed          - a repeat/renewed firing observation
--                                         was accepted into an already-active
--                                         incident (no status change)
--                     status_transition - the incident's status actually
--                                         changed (operator PATCH, or
--                                         Alertmanager's automatic resolution)
--   actor_type   - who/what caused this event:
--                     alertmanager - the automated ingestion/resolution path
--                     operator     - the authenticated human/operator PATCH
--                                    endpoint. This is a SHARED Bearer
--                                    token (see
--                                    docs/architecture/phase-3d-incident-lifecycle.md)
--                                    that does not identify an individual
--                                    human — actor_type='operator' records
--                                    only that an authenticated operator
--                                    request caused this event, never a
--                                    fabricated user id or identity claim.
CREATE TABLE reliability.incident_events (
    -- A plain, monotonically increasing bigint identity column —
    -- deliberately not a UUID: its only job is to be a stable,
    -- deterministic tie-breaker for ordering events that share the
    -- same occurred_at (entirely plausible; see occurred_at below),
    -- never a public identifier callers are expected to construct or
    -- guess.
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- ON DELETE RESTRICT, deliberately not CASCADE: an incident with
    -- any recorded audit history can never be deleted out from under
    -- that history — the history is never silently discarded along
    -- with its incident. This is a real operational constraint, not
    -- just documentation: no code path in this service ever deletes a
    -- row from reliability.incidents at all (there is no delete
    -- endpoint), so this is additionally a defense against a future
    -- mistake, not something today's application code currently needs
    -- to work around.
    incident_id         UUID        NOT NULL
                                     REFERENCES reliability.incidents(id)
                                     ON DELETE RESTRICT,

    event_type          TEXT        NOT NULL
                                     CHECK (event_type IN ('created', 'observed', 'status_transition')),

    actor_type          TEXT        NOT NULL
                                     CHECK (actor_type IN ('alertmanager', 'operator')),

    -- NULL only for event_type='created' (a brand-new incident has no
    -- "previous" status) — enforced below, not left to application
    -- discipline alone.
    previous_status     TEXT        CHECK (previous_status IN (
                                         'open', 'acknowledged', 'investigating',
                                         'remediating', 'resolved', 'closed'
                                     )),

    new_status          TEXT        NOT NULL
                                     CHECK (new_status IN (
                                         'open', 'acknowledged', 'investigating',
                                         'remediating', 'resolved', 'closed'
                                     )),

    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A minimal, structured, allowlisted summary (source fingerprint,
    -- the observed/occurrence timestamp, a resolution source tag —
    -- see ingestion/mapping.py and repositories/incident_repository.py
    -- for the exact, narrow set of keys this service ever writes).
    -- NEVER a Bearer token, an Authorization header, or an unfiltered
    -- webhook payload — enforced by the application layer (there is no
    -- way to enforce "no secrets" via a CHECK constraint), but the
    -- object-shape requirement below IS enforced here.
    metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb
                                     CHECK (jsonb_typeof(metadata) = 'object'),

    -- Event/status shape consistency, enforced per event_type, named
    -- separately (rather than one large OR expression) so a violated
    -- constraint's name alone explains which shape rule was broken:
    CONSTRAINT incident_events_created_shape
        CHECK (
            event_type <> 'created'
            OR (previous_status IS NULL AND new_status = 'open' AND actor_type = 'alertmanager')
        ),
    -- An "observed" event never changes status (see the module
    -- docstring in ingestion/service.py — a repeat/renewed firing
    -- observation into an already-active incident never touches
    -- status): previous_status and new_status must be identical.
    CONSTRAINT incident_events_observed_shape
        CHECK (
            event_type <> 'observed'
            OR (previous_status IS NOT NULL AND previous_status = new_status AND actor_type = 'alertmanager')
        ),
    -- A "status_transition" event, by definition, actually changes
    -- status — previous_status and new_status must differ. Either
    -- actor_type is valid here (an operator PATCH or Alertmanager's
    -- automatic resolution).
    CONSTRAINT incident_events_status_transition_shape
        CHECK (
            event_type <> 'status_transition'
            OR (previous_status IS NOT NULL AND previous_status <> new_status)
        )
);

-- The query this table exists to serve: "give me incident X's timeline,
-- oldest first, with a deterministic tie-breaker" — exactly
-- GET /api/v1/incidents/{id}/events's own ORDER BY. occurred_at alone
-- is not guaranteed unique (DEFAULT now() has ordinary timestamp
-- resolution; two events for the same incident within the same
-- transaction, or simply a fast enough pair of requests, can share a
-- value), so id (monotonic by construction) is the real tie-breaker —
-- included in the index for the same reason it is included in the
-- ORDER BY.
CREATE INDEX incident_events_incident_id_occurred_at_idx
    ON reliability.incident_events (incident_id, occurred_at ASC, id ASC);

-- --------------------------------------------------------------------
-- Append-only enforcement
-- --------------------------------------------------------------------
-- A database-level trigger, not merely an application-layer convention
-- "we just never UPDATE or DELETE this table" — the only reliable way
-- to make a direct SQL client (not just this application's own code)
-- fail loudly if it ever attempts either. Stated honestly, per the
-- task's own framing: this is an append-only APPLICATION record, not a
-- claim of tamper-proof storage against a PostgreSQL superuser, who
-- can always disable triggers, drop the trigger itself, or bypass this
-- entirely with sufficient privilege. It is a real, enforced guard
-- against this application's own normal connection role (and any
-- other normal, non-superuser client) ever mutating or erasing
-- history — not a cryptographic or storage-level tamper-proofing
-- mechanism.
CREATE FUNCTION reliability.incident_events_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'reliability.incident_events is append-only: % is not permitted (id=%)',
        TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER incident_events_no_update
    BEFORE UPDATE ON reliability.incident_events
    FOR EACH ROW
    EXECUTE FUNCTION reliability.incident_events_block_mutation();

CREATE TRIGGER incident_events_no_delete
    BEFORE DELETE ON reliability.incident_events
    FOR EACH ROW
    EXECUTE FUNCTION reliability.incident_events_block_mutation();
