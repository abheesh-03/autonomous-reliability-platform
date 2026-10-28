-- Phase 15 Gate 7: a minimal, durable, organization-scoped SERVICE
-- REGISTRY -- the smallest real backend capability needed to let an
-- engineer register the systems they actually operate (a REST/GraphQL
-- API, a microservice, a database dependency, a queue worker, a
-- Kubernetes workload, an observed cloud resource, ...) so the web
-- console has something real to list on its Services page and
-- reference from the dashboard, instead of hardcoding the Phase 0-14
-- demo's own checkout/payment/inventory/notification service names
-- as if they were the product itself.
--
-- Additive only -- V1 through V11 are never edited. A brand-new table;
-- no existing table, column, constraint, index, or row from any prior
-- migration is altered, dropped, or renamed.
--
-- Deliberately NOT a telemetry/health table: this records only what a
-- user has explicitly REGISTERED (Gate 7: "Separate: a service
-- registered by a user; a service actually connected to telemetry; a
-- service with recent observations; a service whose health can be
-- established"). There is no real OpenTelemetry resource-attribute
-- correlation implemented yet to populate "actually connected"/"has
-- recent observations" truthfully, so this migration does not add a
-- column for either -- a column this platform could never honestly
-- populate would be worse than no column at all. The web console
-- (and this schema) must therefore never represent a registered
-- service as HEALTHY, CONNECTED, or MONITORED until a future,
-- separate migration adds the real telemetry-correlation capability
-- that column would need to mean anything; see
-- docs/architecture/phase-15-product-experience.md's own "known
-- limitations" section.
--
-- organization_id has NO literal foreign key to auth.organization --
-- same cross-schema-FK-avoidance rule reliability.incidents.organization_id
-- already follows (see V10's own comment and
-- docs/architecture/phase-14-security-multitenancy.md's "schema
-- separation" note): Better Auth owns the `auth` schema's own
-- lifecycle (including organization deletion) independently of
-- Flyway, and control-plane never takes a literal FK dependency on a
-- table it does not own the schema of.
CREATE TABLE reliability.services (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id     UUID        NOT NULL,

    name                TEXT        NOT NULL
                                     CHECK (char_length(name) BETWEEN 1 AND 200),

    -- Deliberately an open CHECK vocabulary, not a hardcoded
    -- application-specific list -- Phase 15's own mission statement:
    -- "application-agnostic... REST and GraphQL APIs, microservices,
    -- distributed systems, databases, background workers and queues,
    -- Kubernetes workloads, cloud infrastructure, web and mobile
    -- application backends". 'other' is always a safe fallback so a
    -- legitimate service kind this list does not yet name is never
    -- unregisterable.
    kind                TEXT        NOT NULL
                                     CHECK (kind IN (
                                         'rest_api', 'graphql_api', 'microservice',
                                         'database', 'queue_worker', 'kubernetes_workload',
                                         'cloud_resource', 'other'
                                     )),

    -- Free-text, intentionally never an enum: "implemented in Java,
    -- Python, Go, Node.js, .NET, and other languages" is an open set
    -- by design: NULL means "not specified", never a guessed default.
    language            TEXT,

    description         TEXT,

    -- The REAL Better Auth user id (auth.user.id) who registered this
    -- service -- TEXT, not a literal FK, for the same cross-schema
    -- reason organization_id above has none. Never NULL: every row is
    -- created through the one real, authenticated API endpoint that
    -- sets this from the actor's own verified session, never a
    -- client-supplied claim.
    created_by_user_id  TEXT        NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One organization may not register the same service name twice
    -- -- a real, enforced constraint, not just a UI-level suggestion.
    -- Two DIFFERENT organizations may each freely use the same name
    -- (e.g. both legitimately have a service called "checkout-api"),
    -- since this is scoped per-organization, never globally.
    CONSTRAINT services_org_name_uniq UNIQUE (organization_id, name)
);

-- The query this table exists to serve: "list this organization's
-- registered services, most recently added first" -- the Services
-- page's own entire data source.
CREATE INDEX services_organization_id_created_at_idx
    ON reliability.services (organization_id, created_at DESC);
