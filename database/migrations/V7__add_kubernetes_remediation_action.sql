-- Phase 12B-D: adds exactly ONE new remediation action/target pair --
-- restart_allowlisted_deployment against
-- Deployment/reliability-sandbox/crashloop-demo in cluster
-- kind-reliability-lab -- alongside Phase 8's existing
-- clear_payment_authorization_fault/payment-service pair.
--
-- NEVER modifies V1-V6 -- all six are already applied to the real
-- local development database, and editing any of them would
-- invalidate Flyway's recorded checksum for it. Purely additive DDL.
--
-- Scope note: V6's original action_type/target CHECK constraints each
-- independently allowed exactly one value, which (since they are two
-- SEPARATE single-column constraints) could never express "these two
-- values must appear TOGETHER, as a pair" -- there was only ever one
-- legal value per column, so the question never arose. Adding a
-- second action/target pair makes it arise for the first time: two
-- independent single-column CHECKs would accidentally also permit the
-- CROSS PRODUCT (e.g. action_type='restart_allowlisted_deployment'
-- with target='payment-service') -- exactly the "independent wildcard
-- lists that accidentally permit cross-product combinations" this
-- round is explicitly required to avoid. Both single-column CHECKs are
-- therefore DROPPED and replaced by ONE combined CHECK enumerating
-- only the two explicit, legal (action_type, target, target_cluster)
-- tuples.

-- --------------------------------------------------------------------
-- 1. New, nullable identity-binding columns (Gate 5/6: "bind execution
--    to exact Deployment identity", "recheck UID, namespace, cluster")
-- --------------------------------------------------------------------
-- NULL for the existing payment action (enforced by
-- remediation_proposals_kubernetes_identity_shape below) -- Phase 8's
-- payment proposals are completely unaffected; every existing row's
-- new columns backfill to NULL, which is exactly correct for them.
ALTER TABLE reliability.remediation_proposals
    ADD COLUMN target_cluster TEXT
        CHECK (target_cluster IS NULL OR (btrim(target_cluster) <> '' AND char_length(target_cluster) <= 200)),
    ADD COLUMN expected_resource_uid TEXT
        CHECK (expected_resource_uid IS NULL OR (btrim(expected_resource_uid) <> '' AND char_length(expected_resource_uid) <= 200));

-- --------------------------------------------------------------------
-- 2. Replace the two independent single-column CHECKs with ONE
--    combined, explicit-pair CHECK (never a cross-product)
-- --------------------------------------------------------------------
-- Constraint names confirmed empirically against a real, freshly
-- migrated (V1-V6) database before writing this migration:
--   remediation_proposals_action_type_check: CHECK (action_type = 'clear_payment_authorization_fault')
--   remediation_proposals_target_check:      CHECK (target = 'payment-service')
ALTER TABLE reliability.remediation_proposals
    DROP CONSTRAINT remediation_proposals_action_type_check,
    DROP CONSTRAINT remediation_proposals_target_check;

-- The ONLY two legal (action_type, target, target_cluster) tuples for
-- the whole platform. A future phase adding a third real action must
-- extend this exact list (a new additive migration), never widen
-- either column independently.
ALTER TABLE reliability.remediation_proposals
    ADD CONSTRAINT remediation_proposals_action_target_pair_check
        CHECK (
            (action_type = 'clear_payment_authorization_fault' AND target = 'payment-service' AND target_cluster IS NULL)
            OR
            (action_type = 'restart_allowlisted_deployment'
                AND target = 'Deployment/reliability-sandbox/crashloop-demo'
                AND target_cluster = 'kind-reliability-lab')
        );

-- expected_resource_uid is REQUIRED for the Kubernetes action (its own
-- identity-binding anchor -- Gate 6: "recheck UID ... between
-- approval/execution") and forbidden for the payment action (which has
-- no Kubernetes resource identity at all).
ALTER TABLE reliability.remediation_proposals
    ADD CONSTRAINT remediation_proposals_kubernetes_identity_shape
        CHECK ((action_type = 'restart_allowlisted_deployment') = (expected_resource_uid IS NOT NULL));
