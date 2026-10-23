-- Phase 14 correction round, BLOCKER 4: durable audit of WHO actually
-- decided a remediation proposal.
--
-- Additive only -- V1 through V10 are never edited. Adds two nullable
-- columns to the EXISTING reliability.remediation_proposals table
-- (never a new table, matching V6's own decided_at/decision_comment
-- convention exactly): the verified human approver's real user id and
-- organization id, captured at the moment `decide()` actually applies
-- a decision -- NEVER derived from an unverified claim, and NEVER
-- backfillable for a historical decision this platform did not
-- previously record an actor for (both columns are nullable
-- specifically so every pre-Phase-14 and pre-correction-round
-- decision remains exactly as it was: a real, preserved row with an
-- honestly-absent actor identity, never a fabricated one).
--
-- Why not a new audit table: `remediation_events` (V6) is already the
-- append-only audit log for proposal state transitions, and this
-- migration ALSO starts recording the same actor identity into that
-- table's own `metadata` JSONB for every new 'approved'/'rejected'
-- event (application-level change, not a schema change -- see
-- repositories/remediation_repository.py::decide). These two new
-- columns on remediation_proposals exist ADDITIONALLY so the CURRENT
-- decision's actor is directly queryable without reading the event
-- log -- the same "both a queryable column and an immutable event"
-- redundancy V4/V6 already use for occurred_at/decided_at.
--
-- No existing row, column, constraint, or index from V1-V10 is
-- altered, dropped, or renamed. No existing remediation_proposals row
-- changes value. Historical incident ids, audit chronology, and
-- remediation references are fully preserved.

ALTER TABLE reliability.remediation_proposals
    ADD COLUMN decided_by_user_id         TEXT,
    ADD COLUMN decided_by_organization_id UUID;

-- Shape invariant, mirroring V6's own `remediation_proposals_decided_shape`
-- convention: a proposal that has NOT yet been decided (decided_at IS
-- NULL) must not carry a decider identity either. A DECIDED proposal
-- is NOT required to carry one (pre-correction-round rows, and any
-- decision made while organization-context enforcement is disabled,
-- legitimately have neither) -- this is a one-directional invariant,
-- not a mandatory-actor requirement.
ALTER TABLE reliability.remediation_proposals
    ADD CONSTRAINT remediation_proposals_decider_requires_decision
        CHECK (decided_at IS NOT NULL OR (decided_by_user_id IS NULL AND decided_by_organization_id IS NULL));
