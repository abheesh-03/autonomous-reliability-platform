-- Phase 16 Gate 4/5: durable storage for REAL, authenticated, per-
-- organization external telemetry -- the dashboard's own entire data
-- source for a connected service's request rate / error rate / p50 /
-- p95 latency (Gate 5).
--
-- Additive only -- V1 through V13 are never edited.
--
-- DELIBERATE ARCHITECTURAL CHOICE (see Gate 1's own audit in
-- docs/architecture/phase-16-secure-telemetry-onboarding.md): this
-- table, NOT Prometheus, is the system of record for externally
-- submitted tenant telemetry. The platform's existing OTel Collector /
-- Prometheus / Tempo / Loki stack has NO authentication on its OTLP
-- receivers and NO query-time tenant isolation in any of the three
-- backends (Prometheus and Tempo/Loki both run with no multi-tenancy
-- enabled) -- an "organization" PromQL label would be real only in the
-- sense that it exists, never in the sense that it is enforced; any
-- caller with PromQL/TraceQL access could read any label value. This
-- table reuses the EXACT SAME organization_id-scoped-query pattern
-- already proven secure by this project's own real, repeatedly-passing
-- multitenant acceptance suites (scripts/verify-phase14-multitenant-
-- security.sh, scripts/verify-retrieval-tenant-isolation.sh) --
-- isolation is enforced the same way reliability.incidents' always has
-- been: a mandatory, server-derived WHERE organization_id = :actor_org
-- on every single query path, never a client-suppliable label, and
-- never a raw query surface exposed to any caller.
--
-- organization_id and service_id are both SERVER-DERIVED at ingestion
-- time from the authenticated integration_credentials row that
-- accepted the submission -- never taken from any client-supplied
-- OTLP resource attribute, metric label, or request parameter (Gate 4:
-- "Use server-controlled trusted tenant attribution").
--
-- Scope: ONE real OTel semantic-convention signal this round --
-- `http.server.request.duration` (seconds), the same convention this
-- platform's own checkout/payment/inventory/notification services
-- already emit (see observability/otel-collector/config.yaml's own
-- history) and the one real, official OpenTelemetry HTTP-server
-- instrumentation libraries (Java/Python/Go/Node) emit automatically.
--
-- IMPORTANT, HONEST MODELING NOTE: a real OTLP histogram data point is
-- itself already an AGGREGATE over every request its exporter observed
-- during one export interval that shared the same attribute set (http
-- method/route/status code) -- never one row per individual request on
-- the wire. Each row in this table is therefore one ACCEPTED,
-- VALIDATED data point (`request_count` real requests, summing to
-- `duration_sum_seconds` real observed seconds), not a fabricated
-- single-request record. Request rate and error rate are exact
-- (SUM(request_count) / window, divided appropriately) because they
-- only need sums and counts; p50/p95 latency, computed server-side via
-- `percentile_cont` over each row's own MEAN duration
-- (duration_sum_seconds / request_count), are therefore an
-- APPROXIMATION -- a percentile of per-export-interval mean durations,
-- not a true percentile of every individual request's own latency.
-- This is documented honestly in docs/architecture/phase-16-secure-
-- telemetry-onboarding.md rather than silently presented as exact.
CREATE TABLE reliability.telemetry_samples (
    id                         BIGSERIAL   PRIMARY KEY,

    organization_id            UUID        NOT NULL,

    service_id                 UUID        NOT NULL
                                            REFERENCES reliability.services (id),

    integration_credential_id  UUID        NOT NULL
                                            REFERENCES reliability.integration_credentials (id),

    -- The OTel data point's own real timestamp (its `timeUnixNano`),
    -- NOT the time this service received it -- ingestion/service.py
    -- bounds this to a sane recent window before accepting it (never
    -- infinitely far in the past or future), see that module's own
    -- docstring.
    observed_at                TIMESTAMPTZ NOT NULL,

    received_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    http_method                TEXT,
    http_route                 TEXT,
    http_status_code           INTEGER,

    -- How many real requests this ONE accepted data point represents
    -- (the OTLP histogram data point's own real `count` field).
    request_count              INTEGER     NOT NULL
                                            CHECK (request_count >= 1),

    -- The sum of those `request_count` requests' real observed
    -- durations, in seconds (the OTLP histogram data point's own real
    -- `sum` field) -- `duration_sum_seconds / request_count` is this
    -- row's mean request duration.
    duration_sum_seconds       DOUBLE PRECISION NOT NULL
                                            CHECK (duration_sum_seconds >= 0),

    -- Derived server-side (http_status_code >= 500 on THIS data
    -- point's own attributes), never trusted from a client-supplied
    -- boolean -- the dashboard's own "error rate" is
    -- SUM(request_count) WHERE is_error / SUM(request_count) over a
    -- bounded window, never a client-reported ratio.
    is_error                   BOOLEAN     NOT NULL
);

-- The telemetry-summary endpoint's own entire data source: "this
-- service's samples observed within the last N minutes" -- a single
-- bounded, indexed range scan, never a sequential scan over the whole
-- table.
CREATE INDEX telemetry_samples_service_observed_at_idx
    ON reliability.telemetry_samples (service_id, observed_at DESC);

-- Defense in depth, mirroring every other table in this schema: every
-- real query is already scoped by the verified actor's
-- organization_id first.
CREATE INDEX telemetry_samples_organization_id_idx
    ON reliability.telemetry_samples (organization_id);

-- Known limitation (documented in docs/architecture/phase-16-secure-
-- telemetry-onboarding.md): this migration adds no retention/rollup
-- policy. A long-running production deployment would need one (e.g. a
-- scheduled DELETE of rows older than N days, or a rollup into a
-- pre-aggregated table) before this table's row count becomes a real
-- operational concern -- out of scope for this round's "smallest
-- coherent secure integration."
