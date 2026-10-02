-- Phase 3E (post-review correction): harden the append-only audit
-- trail against TRUNCATE, and record genuine insertion-time
-- timestamps instead of transaction-start-time timestamps.
--
-- NEVER modifies V1__create_incident_schema.sql,
-- V2__add_occurrence_watermark.sql, or V3__create_incident_audit.sql —
-- V3 has already been applied to the non-empty local development
-- database, and editing it would invalidate Flyway's recorded
-- checksum for it (a real, reproduced failure mode — see
-- docs/architecture/incident-domain-model.md). Both fixes below are
-- expressed as new, additive DDL instead.

-- --------------------------------------------------------------------
-- 1. Close the TRUNCATE gap in the append-only guarantee
-- --------------------------------------------------------------------
-- V3's two triggers (incident_events_no_update, incident_events_no_delete)
-- are BEFORE UPDATE/DELETE, FOR EACH ROW triggers — independent review
-- correctly identified that neither fires for TRUNCATE, which is a
-- distinct statement in PostgreSQL's trigger model (it does not
-- generate row-level events at all, which is exactly why it is so much
-- faster than a row-by-row DELETE — and exactly why it needs its own,
-- separate trigger type: BEFORE TRUNCATE, FOR EACH STATEMENT).
--
-- CREATE OR REPLACE FUNCTION on the EXISTING function V3 created
-- (reliability.incident_events_block_mutation) rather than a new,
-- separate function: this is additive, non-destructive DDL — it does
-- not touch V3's own file, and the two existing triggers
-- (incident_events_no_update/_no_delete) automatically pick up this
-- new body with no further changes, since they reference the function
-- by name, not by a frozen definition.
--
-- The one real subtlety: a FOR EACH STATEMENT trigger has no row-level
-- OLD/NEW record at all (TRUNCATE does not operate row-by-row), so a
-- function shared between row-level and statement-level triggers must
-- never evaluate `OLD.id` while running in the statement-level
-- (TG_OP = 'TRUNCATE') context — attempting to do so raises Postgres's
-- own "record \"old\" is not assigned yet" error instead of this
-- function's own clear, intentional message. The IF/ELSIF below
-- branches on TG_OP before ever referencing OLD, so the UPDATE/DELETE
-- branch's `OLD.id` reference is never evaluated during a TRUNCATE
-- invocation.
CREATE OR REPLACE FUNCTION reliability.incident_events_block_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        RAISE EXCEPTION
            'reliability.incident_events is append-only: TRUNCATE is not permitted';
    ELSE
        RAISE EXCEPTION
            'reliability.incident_events is append-only: % is not permitted (id=%)',
            TG_OP, OLD.id;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER incident_events_no_truncate
    BEFORE TRUNCATE ON reliability.incident_events
    FOR EACH STATEMENT
    EXECUTE FUNCTION reliability.incident_events_block_mutation();

-- Post-review correction to V3's own stated security limitation,
-- restated accurately here rather than by editing V3's file (whose
-- checksum must not change): this append-only guarantee is not a
-- "PostgreSQL superuser can bypass it" caveat specifically — ANY role
-- with sufficient privilege over this table (the table's owner, a role
-- with the right to ALTER/DROP it or its triggers, not only a
-- superuser) can disable or drop these triggers, or TRUNCATE/DROP the
-- table outright regardless of trigger state. This is a guard against
-- this application's own normal connection role and any other
-- similarly-unprivileged client — not a claim about what a
-- sufficiently privileged table owner could do. See
-- docs/architecture/phase-3e-incident-audit.md for the corrected,
-- fuller explanation.

-- --------------------------------------------------------------------
-- 2. Correct occurred_at to record genuine insertion time
-- --------------------------------------------------------------------
-- V3 declared `occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()`. In
-- PostgreSQL, now() (and its equivalent, CURRENT_TIMESTAMP/
-- transaction_timestamp()) returns the time the CURRENT TRANSACTION
-- began, not the time the INSERT actually executes — a single value,
-- fixed for the whole transaction, no matter how long it runs or how
-- many statements it contains.
--
-- Independent review correctly identified a real consequence under
-- concurrent writes: transaction A can start first (fixing its own
-- now() value earlier), then block waiting for a row lock transaction
-- B is holding; B commits first, and only then does A proceed to
-- INSERT its own audit event — using the EARLIER now() value A's
-- transaction captured when it first began, not the genuinely later
-- wall-clock moment its INSERT actually ran. Since
-- GET /api/v1/incidents/{id}/events orders by `occurred_at ASC, id
-- ASC`, this could place A's event BEFORE B's in the reported
-- timeline even though A's mutation genuinely happened after B's —
-- a misleading incident history.
--
-- clock_timestamp() does not have this problem: it returns the actual
-- current wall-clock time at the moment the expression is evaluated,
-- changing on every call within a transaction (or even within a
-- single statement) rather than being fixed once per transaction. This
-- is exactly "when was this specific row actually inserted", which is
-- what an append-only audit log's own timestamp should mean.
--
-- ALTER COLUMN ... SET DEFAULT changes the default applied to FUTURE
-- INSERTs only — it is not a backfill and does not rewrite any
-- existing row. Every event already recorded under V3 keeps its
-- original, genuinely-already-correct-for-its-own-row now()-based
-- timestamp untouched; this migration does not and must not rewrite
-- history. The application itself
-- (repositories/incident_repository.py's `_record_event`) never
-- specifies `occurred_at` explicitly in its INSERT — it has always
-- relied on the column default — so this schema-only change takes
-- effect for every future event with zero application code changes.
--
-- The existing deterministic tie-breaker (`id ASC`, after `occurred_at
-- ASC`, both in the ORDER BY and in incident_events_incident_id_occurred_at_idx)
-- is unchanged and still correct: id remains monotonically increasing
-- by insertion order regardless of which clock function supplies
-- occurred_at.
ALTER TABLE reliability.incident_events
    ALTER COLUMN occurred_at SET DEFAULT clock_timestamp();
