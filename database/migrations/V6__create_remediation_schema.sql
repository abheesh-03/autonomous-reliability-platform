-- Phase 8: human-approved remediation proposal/audit persistence.
--
-- NEVER modifies V1__create_incident_schema.sql,
-- V2__add_occurrence_watermark.sql, V3__create_incident_audit.sql,
-- V4__harden_incident_audit.sql, or V5__create_retrieval_index.sql --
-- all five are already applied to the real local development database
-- (confirmed via `flyway info` / this file's own reconnaissance before
-- writing it), and editing any of them would invalidate Flyway's
-- recorded checksum for it. Purely additive DDL: two new tables in the
-- SAME "reliability" schema those migrations already own.
--
-- Ownership: these tables are written to ONLY by control-plane's own
-- remediation API (api/remediation.py / repositories/remediation_repository.py)
-- -- never directly by agent-runtime-service, tool-gateway, or
-- payment-service, none of which hold any PostgreSQL credential for
-- this schema at all (see docs/architecture/phase-8-human-approval-remediation.md).
--
-- Scope note (Phase 8): exactly ONE allowlisted action exists for the
-- whole platform right now -- clear_payment_authorization_fault against
-- payment-service. The CHECK constraints on action_type/target below
-- enforce this at the database level too, not merely in application
-- code -- a defense-in-depth mirror of tool-gateway's own Go allowlist
-- and of propose_remediation's own deterministic policy, not a
-- substitute for either.

-- --------------------------------------------------------------------
-- 1. reliability.remediation_proposals
-- --------------------------------------------------------------------
-- Status vocabulary (also documented in
-- docs/architecture/phase-8-human-approval-remediation.md):
--   pending_approval - proposed by the agent runtime, awaiting a human
--                       decision
--   approved         - a human/operator approved it (atomically, with
--                       the owning incident's investigating->remediating
--                       transition -- see api/remediation.py)
--   rejected         - a human/operator rejected it; terminal, the
--                       owning incident is left untouched
--   executing        - tool-gateway has started executing the
--                       allowlisted action (idempotent re-entry point
--                       for an at-least-once retry after a crash)
--   succeeded        - tool-gateway independently verified the action's
--                       effect and recorded success; terminal
--   failed           - tool-gateway's action or its independent
--                       verification did not succeed; terminal (the
--                       owning incident is transitioned back
--                       remediating->investigating in the same
--                       transaction that records this -- see
--                       api/remediation.py)
--
-- Legal transitions (enforced in application code via an optimistic
-- compare-and-swap UPDATE, the same `WHERE ... AND status = :expected`
-- idiom control_plane/repositories/incident_repository.py already uses
-- -- never a DB-level trigger graph, consistent with how
-- domain/lifecycle.py keeps the INCIDENT state machine in Python, not
-- SQL):
--   pending_approval -> approved | rejected
--   approved         -> executing
--   executing        -> executing (idempotent retry) | succeeded | failed
CREATE TABLE reliability.remediation_proposals (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    incident_id             UUID        NOT NULL
                                         REFERENCES reliability.incidents(id)
                                         ON DELETE RESTRICT,

    -- The durable LangGraph thread/run this proposal was created from
    -- (agent-runtime-service's own run_id, a UUID it generates --
    -- Phase 7 §AGENT RUN IDENTITY). Not a foreign key: agent-runtime's
    -- checkpoint store is a completely separate, least-privileged
    -- database role/schema (`agent_runtime`), which this schema has no
    -- relationship to and must never be joined against.
    agent_run_id            UUID        NOT NULL,

    -- Proposal idempotency (REQUIRED -- a node may execute an external
    -- call, crash before its own checkpoint commits, and run again).
    -- Deterministically derived by agent-runtime-service as
    -- "phase8-proposal:<run_id>" -- never random -- so a retried
    -- creation request for the SAME run converges on the SAME row via
    -- this UNIQUE constraint, not a duplicate.
    idempotency_key         TEXT        NOT NULL UNIQUE
                                         CHECK (btrim(idempotency_key) <> ''
                                                AND char_length(idempotency_key) <= 200),

    -- Phase 8 scope: exactly one allowlisted action/target pair. A
    -- future phase that adds a second real action must add it here
    -- explicitly (a new additive migration), never widen this to a
    -- free-form string.
    action_type             TEXT        NOT NULL
                                         CHECK (action_type = 'clear_payment_authorization_fault'),
    target                  TEXT        NOT NULL
                                         CHECK (target = 'payment-service'),

    -- Bounded free text only -- never a raw LLM prompt, never a secret,
    -- never an arbitrarily large blob (see propose_remediation's own
    -- text_safety bounding before this is ever sent to control-plane).
    reason                  TEXT        NOT NULL
                                         CHECK (char_length(reason) <= 1000),

    -- Bounded, structured provenance only -- opaque evidence/context
    -- identifiers already produced and bounded by investigator-service/
    -- retrieval-service (Phase 5/6), never raw evidence text itself.
    -- Bounded at most 50 entries (a defensive ceiling, not an
    -- expectation that a real Phase 8 report ever approaches it) and,
    -- via array_to_string's own total length, a combined ceiling on
    -- every element's size together -- PostgreSQL CHECK constraints
    -- cannot contain a subquery/aggregate (confirmed empirically:
    -- `cannot use subquery in check constraint`), so a true per-element
    -- length bound is enforced in application code
    -- (repositories/remediation_repository.py), not here; this
    -- constraint is the real, enforceable database-level backstop.
    supporting_evidence_ids TEXT[]      NOT NULL DEFAULT '{}'
                                         CHECK (
                                             cardinality(supporting_evidence_ids) <= 50
                                             AND char_length(array_to_string(supporting_evidence_ids, ',')) <= 5000
                                         ),
    supporting_context_ids  TEXT[]      NOT NULL DEFAULT '{}'
                                         CHECK (
                                             cardinality(supporting_context_ids) <= 50
                                             AND char_length(array_to_string(supporting_context_ids, ',')) <= 5000
                                         ),

    status                  TEXT        NOT NULL DEFAULT 'pending_approval'
                                         CHECK (status IN (
                                             'pending_approval', 'approved', 'rejected',
                                             'executing', 'succeeded', 'failed'
                                         )),

    proposed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Set only on the pending_approval -> approved|rejected transition;
    -- left untouched by every later transition (executing/succeeded/
    -- failed), preserving the ORIGINAL human decision moment -- the
    -- same "never overwrite the original moment" discipline V4 already
    -- established for incident_events.occurred_at.
    decided_at              TIMESTAMPTZ,
    decision_comment        TEXT        CHECK (char_length(decision_comment) <= 1000),

    execution_started_at    TIMESTAMPTZ,
    execution_completed_at  TIMESTAMPTZ,

    -- Shape invariants, enforced per status (mirrors the named-CHECK-
    -- per-shape convention V3 established for incident_events):
    CONSTRAINT remediation_proposals_decided_shape
        CHECK ((status = 'pending_approval') = (decided_at IS NULL)),
    CONSTRAINT remediation_proposals_execution_shape
        CHECK (
            (status IN ('pending_approval', 'approved', 'rejected') AND execution_started_at IS NULL)
            OR (status IN ('executing', 'succeeded', 'failed') AND execution_started_at IS NOT NULL)
        ),
    CONSTRAINT remediation_proposals_completion_shape
        CHECK (
            (status IN ('succeeded', 'failed') AND execution_completed_at IS NOT NULL)
            OR (status NOT IN ('succeeded', 'failed') AND execution_completed_at IS NULL)
        )
);

CREATE INDEX remediation_proposals_incident_id_idx
    ON reliability.remediation_proposals (incident_id, proposed_at DESC);

CREATE INDEX remediation_proposals_status_idx
    ON reliability.remediation_proposals (status);

CREATE FUNCTION reliability.set_remediation_proposals_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER remediation_proposals_set_updated_at
    BEFORE UPDATE ON reliability.remediation_proposals
    FOR EACH ROW
    EXECUTE FUNCTION reliability.set_remediation_proposals_updated_at();

-- --------------------------------------------------------------------
-- 2. reliability.remediation_events -- append-only audit trail
-- --------------------------------------------------------------------
-- Vocabulary:
--   event_type - proposed | approved | rejected | execution_started |
--                execution_succeeded | execution_failed
--   actor_type - agent (the durable LangGraph run that created the
--                proposal), operator (the human/operator decision
--                endpoint), executor (tool-gateway's own bookkeeping
--                calls)
CREATE TABLE reliability.remediation_events (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    proposal_id UUID        NOT NULL
                             REFERENCES reliability.remediation_proposals(id)
                             ON DELETE RESTRICT,

    event_type  TEXT        NOT NULL
                             CHECK (event_type IN (
                                 'proposed', 'approved', 'rejected',
                                 'execution_started', 'execution_succeeded', 'execution_failed'
                             )),

    actor_type  TEXT        NOT NULL
                             CHECK (actor_type IN ('agent', 'operator', 'executor')),

    -- clock_timestamp(), not now() -- the genuine insertion-time fix
    -- V4 applied retroactively to incident_events is built in here
    -- from day one (see V4's own docstring for why now()/transaction
    -- timestamp is the wrong choice for an append-only audit log).
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    -- Allowlisted, structured, bounded metadata only -- never a raw
    -- LLM prompt, a Bearer token, an Authorization header, or an
    -- unfiltered HTTP response body. The object-shape requirement is
    -- enforced here; "no secrets" is an application-layer discipline
    -- (repositories/remediation_repository.py), the same honest
    -- limitation V3 already states for incident_events.metadata.
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb
                             CHECK (jsonb_typeof(metadata) = 'object'),

    CONSTRAINT remediation_events_proposed_shape
        CHECK (event_type <> 'proposed' OR actor_type = 'agent'),
    CONSTRAINT remediation_events_approved_shape
        CHECK (event_type <> 'approved' OR actor_type = 'operator'),
    CONSTRAINT remediation_events_rejected_shape
        CHECK (event_type <> 'rejected' OR actor_type = 'operator'),
    CONSTRAINT remediation_events_execution_shape
        CHECK (
            event_type NOT IN ('execution_started', 'execution_succeeded', 'execution_failed')
            OR actor_type = 'executor'
        )
);

CREATE INDEX remediation_events_proposal_id_occurred_at_idx
    ON reliability.remediation_events (proposal_id, occurred_at ASC, id ASC);

-- Append-only enforcement -- same pattern, and same honest limitation
-- (a real application-record guarantee against this application's own
-- normal connection role, never a tamper-proof/superuser-proof claim),
-- as V3/V4 already establish for reliability.incident_events. A
-- separate function (not reused across tables with different column
-- sets, same reasoning as V5's set_retrieval_chunks_updated_at using
-- its own function rather than reusing reliability.set_updated_at()),
-- but covering UPDATE/DELETE/TRUNCATE together from the very first
-- migration that creates this table -- unlike incident_events, which
-- needed V4 to retrofit the TRUNCATE case, this table has no such gap
-- to retrofit later.
CREATE FUNCTION reliability.remediation_events_block_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        RAISE EXCEPTION
            'reliability.remediation_events is append-only: TRUNCATE is not permitted';
    ELSE
        RAISE EXCEPTION
            'reliability.remediation_events is append-only: % is not permitted (id=%)',
            TG_OP, OLD.id;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER remediation_events_no_update
    BEFORE UPDATE ON reliability.remediation_events
    FOR EACH ROW
    EXECUTE FUNCTION reliability.remediation_events_block_mutation();

CREATE TRIGGER remediation_events_no_delete
    BEFORE DELETE ON reliability.remediation_events
    FOR EACH ROW
    EXECUTE FUNCTION reliability.remediation_events_block_mutation();

CREATE TRIGGER remediation_events_no_truncate
    BEFORE TRUNCATE ON reliability.remediation_events
    FOR EACH STATEMENT
    EXECUTE FUNCTION reliability.remediation_events_block_mutation();
