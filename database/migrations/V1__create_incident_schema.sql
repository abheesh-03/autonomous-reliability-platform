-- Phase 3A: incident domain model + persistence.
--
-- Creates a dedicated "reliability" schema (never the default "public"
-- schema, which already holds an unrelated pre-existing Phase 0
-- verification table, public.phase_02_verification, that this
-- migration must never touch) and its first table, incidents.
--
-- Scope note: this migration defines the incident entity, its
-- constraints, and its deduplication index only. It deliberately does
-- NOT implement incident lifecycle transition logic (e.g. a trigger or
-- function validating status A -> status B is a legal transition) —
-- that belongs to Phase 3D. The only lifecycle-adjacent rule enforced
-- here is a data-integrity invariant, not a transition rule: resolved
-- incidents must have a resolved_at timestamp, and non-resolved
-- incidents must not.

CREATE SCHEMA IF NOT EXISTS reliability;

-- Status vocabulary (documented here, also see
-- docs/architecture/incident-domain-model.md):
--   open          - detected, not yet acknowledged by anyone/anything
--   acknowledged  - a human or agent has acknowledged the incident
--   investigating - actively being investigated
--   remediating   - remediation is in progress
--   resolved      - the underlying condition has cleared
--   closed        - resolved and administratively closed/archived
--
-- Initial-state invariant: every new incident is created with
-- status = 'open' (the column DEFAULT below) and resolved_at = NULL.
-- Phase 3D will implement real transition validation (which statuses
-- may follow which); this migration only guarantees the vocabulary
-- itself is enforced (via the CHECK constraint) and that resolved_at's
-- nullability always agrees with whether status is a resolved-type
-- status, which is a data-integrity rule, not a transition rule.
CREATE TABLE reliability.incidents (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Originating monitoring system, e.g. "alertmanager". Free-text
    -- (not an enum) since Phase 3C may eventually ingest from more
    -- than one source; only required to be non-blank.
    source              TEXT        NOT NULL CHECK (btrim(source) <> ''),

    -- Stable external identifier used for deduplication, scoped to
    -- (source, source_fingerprint) — see the partial unique index
    -- below. For an Alertmanager-originated incident this is expected
    -- to be derived from the alert's own fingerprint/labels in
    -- Phase 3C; this migration only requires it be non-blank.
    source_fingerprint  TEXT        NOT NULL CHECK (btrim(source_fingerprint) <> ''),

    title               TEXT        NOT NULL CHECK (btrim(title) <> ''),
    description         TEXT,

    severity            TEXT        NOT NULL
                                     CHECK (severity IN ('critical', 'warning', 'info')),

    status              TEXT        NOT NULL DEFAULT 'open'
                                     CHECK (status IN (
                                         'open', 'acknowledged', 'investigating',
                                         'remediating', 'resolved', 'closed'
                                     )),

    first_seen_at       TIMESTAMPTZ NOT NULL,
    last_seen_at        TIMESTAMPTZ NOT NULL,
    resolved_at         TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT incidents_last_seen_not_before_first_seen
        CHECK (last_seen_at >= first_seen_at),

    -- Data-integrity invariant (not a transition rule): resolved_at is
    -- set if and only if status is one of the resolved-type statuses.
    CONSTRAINT incidents_resolved_at_matches_status
        CHECK (
            (status IN ('resolved', 'closed') AND resolved_at IS NOT NULL)
            OR
            (status NOT IN ('resolved', 'closed') AND resolved_at IS NULL)
        )
);

-- Deduplication: at most one ACTIVE (non-resolved, non-closed)
-- incident per (source, source_fingerprint) at a time. A new incident
-- with the same fingerprint is allowed again once the previous one has
-- moved to 'resolved' or 'closed' — that prior row is preserved, not
-- overwritten or deleted, so incident history is never lost. This is
-- the database-level protection against Alertmanager (or any future
-- source) re-sending the same firing alert repeatedly and spawning
-- unbounded duplicate active incidents; a concurrent duplicate INSERT
-- fails with a real unique_violation (SQLSTATE 23505), not a silently
-- coexisting duplicate row.
CREATE UNIQUE INDEX incidents_active_fingerprint_uniq
    ON reliability.incidents (source, source_fingerprint)
    WHERE status NOT IN ('resolved', 'closed');

-- Supporting indexes for the query patterns a future control plane
-- (Phase 3C+) is expected to need: filter by status, filter by
-- severity, and list/sort by recency.
CREATE INDEX incidents_status_idx ON reliability.incidents (status);
CREATE INDEX incidents_severity_idx ON reliability.incidents (severity);
CREATE INDEX incidents_last_seen_at_idx ON reliability.incidents (last_seen_at DESC);

-- updated_at bookkeeping only (not lifecycle logic): keeps the column
-- honest on every UPDATE, regardless of which client performs it.
CREATE FUNCTION reliability.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER incidents_set_updated_at
    BEFORE UPDATE ON reliability.incidents
    FOR EACH ROW
    EXECUTE FUNCTION reliability.set_updated_at();
