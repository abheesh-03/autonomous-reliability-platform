-- Phase 16 Gate 2/3: durable, organization-scoped INTEGRATION
-- CREDENTIAL records -- the enrollment/connection record binding one
-- registered service (reliability.services, Phase 15) to one real,
-- authenticated external telemetry source.
--
-- Additive only -- V1 through V12 are never edited. A brand-new table;
-- no existing table, column, constraint, index, or row from any prior
-- migration is altered, dropped, or renamed.
--
-- organization_id has NO literal foreign key to auth.organization --
-- same cross-schema-FK-avoidance rule every other organization_id
-- column in this schema already follows (see V10/V12's own comments).
-- service_id DOES have a real foreign key to reliability.services,
-- since both tables are owned by this same schema/migration history.
--
-- NEVER stores a plaintext secret. `credential_secret_hash` is a
-- SHA-256 hex digest of the real, CSPRNG-generated secret portion
-- (see services/control-plane/src/control_plane/core/credentials.py);
-- the real secret value is shown to the user exactly once, at creation
-- time, and is never persisted or recoverable afterward -- the same
-- "shown once" discipline a real cloud provider's own API key creation
-- flow uses. `credential_id` is the public, non-secret, indexed lookup
-- prefix (e.g. "cred_<22 random base62 chars>") presented alongside the
-- secret as `Authorization: Bearer <credential_id>.<secret>" -- it is
-- the ONLY thing ever reused by this service to find a row before
-- verifying the secret's hash; it alone grants nothing.
CREATE TABLE reliability.integration_credentials (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id          UUID        NOT NULL,

    service_id               UUID        NOT NULL
                                          REFERENCES reliability.services (id),

    -- An open CHECK vocabulary, not a hardcoded single value --
    -- mirrors V12's own "kind" column rationale. Phase 16 implements
    -- exactly one value ('opentelemetry'); the others are reserved
    -- for a future phase's own real, separately-reviewed ingestion
    -- path -- never selectable today (enforced by the API, not merely
    -- this CHECK).
    connection_type          TEXT        NOT NULL
                                          CHECK (connection_type IN ('opentelemetry')),

    credential_id             TEXT        NOT NULL UNIQUE
                                          CHECK (char_length(credential_id) BETWEEN 8 AND 64),

    credential_secret_hash    TEXT        NOT NULL,

    status                    TEXT        NOT NULL DEFAULT 'active'
                                          CHECK (status IN ('active', 'revoked')),

    created_by_user_id        TEXT        NOT NULL,

    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- NULL until revoked; once set, status is always 'revoked' (both
    -- maintained together, in the same application-code transaction --
    -- see repositories/integration_credential_repository.py).
    revoked_at                TIMESTAMPTZ,

    -- The last time THIS credential successfully authenticated a real
    -- telemetry submission -- the dashboard's own "last observed
    -- telemetry" / staleness signal (Gate 5). NULL means "issued, but
    -- has never once been used to submit anything real yet" --
    -- deliberately distinct from "recently used," never conflated.
    last_verified_telemetry_at TIMESTAMPTZ
);

-- The query this table exists to serve most often: "find this
-- credential by its public id, to verify the secret hash against it" --
-- the ingestion endpoint's own hot path, exactly once per request.
-- UNIQUE above already creates an index on credential_id; no separate
-- one is needed for that lookup.

-- The Services/Integrations page's own data source: "list this
-- service's enrolled integrations."
CREATE INDEX integration_credentials_service_id_idx
    ON reliability.integration_credentials (service_id);

-- Defense in depth, mirroring V12's own organization-scoped listing
-- index: every real query this service issues is already scoped by a
-- verified actor's organization_id first (Gate 2: "a service belongs
-- to exactly one organization"), so this index serves that filter
-- directly rather than relying solely on the service_id join above.
CREATE INDEX integration_credentials_organization_id_idx
    ON reliability.integration_credentials (organization_id);
