-- Phase 14, Gate 4: tenant-bound ownership for reliability.incidents.
--
-- Additive only -- V1 through V9 are never edited (Gate 4: "Never edit
-- V1 through V9"). This migration:
--
--   1. Adds a nullable `organization_id` column.
--   2. Backfills EVERY existing row to a fixed, documented constant --
--      '00000000-0000-0000-0000-000000000001', the "legacy local
--      development organization" (see
--      services/control-plane/src/control_plane/core/config.py's
--      LEGACY_LOCAL_DEVELOPMENT_ORGANIZATION_ID, which application
--      code refers to by the SAME value). Deliberately NOT "whichever
--      user signs up first" and NOT a production fallback for an
--      unrecognized tenant -- Gate 4 explicitly prohibits both; this
--      is a single, well-known, intentional constant chosen before any
--      user account exists.
--   3. Makes the column NOT NULL and gives it a DEFAULT of that same
--      constant, so every EXISTING ingestion/ -- insert path
--      (Alertmanager webhook, Kubernetes/AWS finding ingestion --
--      none of which this phase makes tenant-aware; see Gate 6's own
--      "known limitations" note in
--      docs/architecture/phase-14-security-multitenancy.md) continues
--      to insert valid rows WITHOUT any application-code change, all
--      landing in the same legacy organization until Gate 6's real
--      per-tenant ingestion association is implemented in a future
--      phase.
--   4. Redefines incidents_active_fingerprint_uniq (originally defined
--      in V1) to be scoped PER ORGANIZATION, preserving its original
--      dedup semantics exactly (same partial predicate) within each
--      tenant -- so a future multi-tenant deployment cannot have
--      org A's active alert silently dedup against org B's identically
--      fingerprinted one. The original index is dropped and replaced
--      with an equivalent one that also includes organization_id; this
--      changes nothing for any existing (single-organization) data, by
--      construction (every row currently shares the same
--      organization_id).
--   5. Adds a supporting composite index for organization-scoped
--      listing/pagination (mirrors incidents_last_seen_at_idx's own
--      ordering, additionally scoped by organization_id).
--
-- Historical incident ids, audit chronology (reliability.incident_events,
-- untouched by this migration), and every remediation_proposals/
-- remediation_events row (both already FK'd to incidents.id --
-- untouched by this migration, inheriting organization scope
-- transitively through that existing foreign key) are fully preserved.
-- No row is ever deleted, reset, or re-keyed.

ALTER TABLE reliability.incidents
    ADD COLUMN organization_id UUID;

UPDATE reliability.incidents
    SET organization_id = '00000000-0000-0000-0000-000000000001'
    WHERE organization_id IS NULL;

ALTER TABLE reliability.incidents
    ALTER COLUMN organization_id SET NOT NULL,
    ALTER COLUMN organization_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

DROP INDEX reliability.incidents_active_fingerprint_uniq;

CREATE UNIQUE INDEX incidents_active_fingerprint_uniq
    ON reliability.incidents (organization_id, source, source_fingerprint)
    WHERE status NOT IN ('resolved', 'closed');

CREATE INDEX incidents_organization_last_seen_at_idx
    ON reliability.incidents (organization_id, last_seen_at DESC);
