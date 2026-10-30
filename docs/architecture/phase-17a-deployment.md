# Phase 17A — Single-Host Deployment and Operational Hardening

Baseline HEAD: `0bbb73dd6b6f0bdbd1cfeb743264f3bf792a75f2` (`feat(phase-16):
add secure tenant telemetry onboarding`). This document covers the
deployment configuration and hardening added under `deploy/` this
round; `deploy/README.md` is the operational runbook (deploy/update/
rollback/backup/restore/retention), and `deploy/HOSTING_REPORT.md` is
the separate sizing/cost decision report.

## 1. Mission and scope

A real, deployable, single-host Docker Compose configuration —
**not** a rewrite of the existing local-development stack, which
`docker-compose.yml` and its own Makefile targets continue to serve
unchanged. Everything in this round lives under `deploy/` (a new,
separately-invoked configuration) plus a small number of focused
application-code changes (trusted-proxy IP resolution, deployment-mode
email verification/reset, a new additive migration) that are safe in
both local development and a real deployment.

Explicitly **not** in scope this round: actual hosting (a real domain,
real ACME TLS, a real SMTP provider's credentials, a real off-host
backup destination, any cloud/VPS provisioning) — that is Phase 17B,
and nothing in this round provisions, pays for, or registers anything
external. This is a **single-host MVP**: no high availability, no
automatic failover, no horizontal scaling story for either rate
limiter or for Postgres.

## 2. Deployment topology

```
Internet (Phase 17B) / host network (this round's local proof)
        │
        ▼ :80, :443 (ONLY published ports)
   ┌─────────┐
   │  Caddy  │  real TLS (local CA this round; real ACME in 17B)
   └────┬────┘
        │ internal Compose network only — every other service below
        │ publishes NO port; this is the actual enforcement
        │ mechanism, proven by `docker compose config` every run
        │ (deploy/scripts/preflight.sh), not merely asserted.
   ┌────┴─────────────────────────────────────────────────┐
   │                                                         │
   ▼ exact path only: POST /api/v1/telemetry/otlp/v1/metrics ▼ everything else
┌───────────────┐                                    ┌──────────────┐
│ control-plane │◄──────────┐                        │  web-console │
└───────┬───────┘           │                        └──────┬───────┘
        │                   │ internal-service reads         │ owns its
        ▼                   │                                │ own BFF/
┌───────────────┐  ┌────────┴────────┐  ┌──────────────┐     │ auth
│  retrieval-   │  │ agent-runtime-  │  │ investigator-│      │ routes
│  service      │  │ service         │  │ service      │      │
└───────────────┘  └────────┬────────┘  └──────────────┘      │
                             ▼                                 │
                      ┌─────────────┐                          │
                      │ tool-gateway│                          │
                      └─────────────┘                          │
                                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ postgres (pgvector) — reliability / auth / agent_runtime schemas, │
│ FOUR least-privileged runtime roles (below), bootstrap role never │
│ given to an application container at runtime                     │
└──────────────────────────────────────────────────────────────────┘

Internal-only demo/observability (never proxied): checkout-service,
payment-service, inventory-service, notification-service,
otel-collector, tempo, loki, prometheus, alertmanager, grafana, alloy
(→ docker-socket-proxy, never the raw Docker socket).
```

## 3. Database role separation (item 3)

| Role | Used by | Scope |
|---|---|---|
| `${POSTGRES_BOOTSTRAP_USER}` | `postgres` container itself, `flyway` migrations, the one-time role-bootstrap script | schema owner; never given to an application container at runtime |
| `control_plane_app` | control-plane | SELECT/INSERT/UPDATE/DELETE on `incidents`, `services`, `integration_credentials`, `telemetry_samples`, `remediation_proposals`; SELECT/INSERT only on the two append-only audit tables (`incident_events`, `remediation_events` — matches their own real triggers' intent); CORRECTION ROUND: narrowed from a blanket `SELECT ON ALL TABLES IN SCHEMA auth` to a real, column-level `SELECT ("organizationId", "userId", "role") ON auth.member` ONLY — audited directly against the one real cross-schema query this service issues (`AuthMembershipRepository.get_current_role`); proven directly (`deploy/scripts/test-auth-grant-boundary.sh`, against a real disposable database) that this role CAN read those three columns and CANNOT read `auth.session`, `auth.account`, `auth.verification`, or any other column of `auth.member` |
| `retrieval_app` | retrieval-service | SELECT on `incidents`; full DML on `retrieval_chunks` only |
| `web_console` | web-console | owns `auth` schema only (reused, unchanged shape from Phase 14) |
| `agent_runtime` | agent-runtime-service | owns `agent_runtime` schema only (reused, unchanged shape from Phase 7) |

None of the four application-facing roles can CREATE/ALTER/DROP a
table or schema, create/alter another role, bypass row-level security,
or connect as a replication client. See
`deploy/sql/01-create-runtime-roles.sql.template` for the exact,
applied SQL.

Local-development scripts that hardcode the repository root's own
`.env` (`scripts/init-web-console-db.sh`, `scripts/
init-agent-runtime-db.sh`, `scripts/apply-web-console-auth-schema.sh`)
are **never invoked** by the deployment flow — `deploy/scripts/
init-deploy-secrets.sh` and `deploy/scripts/apply-deploy-auth-schema.sh`
are deployment's own, parallel bootstrap path reading only
`deploy/.env.deploy`, so the developer's own `.env` can never be
touched by a deployment operation.

## 4. Trusted-proxy boundary (item 2)

See `services/control-plane/src/control_plane/core/trusted_proxy.py`
and its own test suite (`tests/test_trusted_proxy.py`) for the full
mechanism. Summary: `X-Forwarded-For` is trusted only when the
request's real, direct TCP peer independently resolves to
`TRUSTED_PROXY_HOSTS` (`caddy`) — never a wildcard, never "all private
addresses." Caddy itself always overwrites (never appends to) that
header with the real connecting client's address. Real proof (this
round, against the live deployed stack): 15 requests from one real
source, each with a different spoofed `X-Forwarded-For` value, still
tripped the real 10-failures/5-minute limiter exactly as if no spoofing
had been attempted — control-plane's own logs show the REAL resolved
address (the Docker gateway address of the test client), never any of
the 15 spoofed values.

Better Auth's own browser-auth rate limiter/session-IP-tracking is
configured the same way (`advanced.ipAddress.ipAddressHeaders`,
`services/web-console/lib/auth/auth.ts`), gated behind the same
`TRUSTED_PROXY_ENABLED` flag.

**Explicitly one `control-plane` replica and one `web-console`
replica** in this deployment — both rate limiters remain in-process
and in-memory; scaling either service to more than one replica
without a shared backing store would silently split each limiter's
own budget. A process restart resets every budget to zero. This is
unchanged from Phase 16 and is not addressed this round (no Redis
migration).

## 5. Legacy ingestion boundary (item 2)

`CONTROL_PLANE_ALLOW_LEGACY_INGESTION=true` is kept in this
deployment's template. This is safe specifically because
`deploy/caddy/Caddyfile` defines no route for the Alertmanager webhook
or any other control-plane path besides the one exact telemetry-
ingestion path — confirmed this round, live, against the REAL route
(`services/control-plane/src/control_plane/api/webhook.py` registers
it at `/internal/v1/alertmanager/webhook`, not `/api/v1/...` — a
prior round's own CI check probed the wrong path, proving nothing
about the real one; see `.github/workflows/ci.yml`'s "Legacy/internal
routes are unreachable through the public proxy" step): `POST
/internal/v1/alertmanager/webhook` through the public proxy does not
return 200 (falls through to web-console, which has no matching route
either), never reaching control-plane. A deployment that wants the
pipeline fully disabled (not merely network-isolated) sets this flag
to `false`.

## 6. Email delivery (item 4)

`services/web-console/lib/auth/mail-transport.ts` (new) wraps
`nodemailer`, mapping `SMTP_SECURITY` (`starttls`/`tls`/`none`) to its
real, verified transport options. `emailAndPassword.requireEmailVerification`
is now `isSecureDeployment()` (verified directly against the installed
Better Auth route source that this actually blocks `/sign-in/email`
for an unverified user); `sendResetPassword` is wired to a new,
symmetrical `email-reset-delivery.ts` module. Local development
(no SMTP configured) is completely unaffected — the existing log-only
fallback still applies. New, minimal forgot-password/reset-password
pages were added (`app/forgot-password/`, `app/reset-password/`).
See `deploy/README.md`/the final report for the real proof against a
disposable, non-public test SMTP receiver (Mailpit).

## 7. Observability Docker-socket access (item 1)

`alloy` no longer bind-mounts `/var/run/docker.sock` in this
deployment. A new `docker-socket-proxy` sidecar
(`tecnativa/docker-socket-proxy:v0.4.2`, pinned) allowlists
`CONTAINERS=1` only (list/inspect/stream logs) — every mutating
category (`POST`) and every other read category is explicitly `0`.
CORRECTION ROUND: `docker-socket-proxy` previously had no `networks:`
key at all and so sat on the same flat default network as every
other service in this stack, none of which have any legitimate
reason to reach it; it now lives on its own dedicated, `internal:
true` network that only `alloy` also joins — confirmed directly
against the real merged `docker compose config` output. Known
residual exposure, unchanged by that fix: `CONTAINERS=1` also permits
a read-only filesystem-archive export of ANY container on the Docker
HOST (the socket is not scoped to this Compose project), not merely
narrowing WHICH containers it can see once reached — narrower than
the raw socket (which also permits container creation, exec, and
swarm control) but documented, not hidden.

## 8. Resource/logging/hardening baseline (item 1)

Every service in `deploy/docker-compose.override.yml` gets:
`security_opt: [no-new-privileges:true]`, a bounded `json-file` log
driver (`max-size`/`max-file`, configurable), and an explicit
`deploy.resources.limits` (cpus/memory) sized per service's real role
(small for internal demo/observability services, medium for
control-plane/web-console, larger for postgres). Every application
image already runs as a non-root user (`app`/`node`/`nonroot` —
audited this round; see `deploy/RELEASE_MANIFEST.md`'s own table) —
this was already true before Phase 17A and is carried through
unchanged.

## 9. Migration

One new, additive migration this round:
`database/migrations/V17__add_telemetry_samples_observed_at_idx.sql`
— a plain `(observed_at)` index supporting the retention tool's own
cutoff scan (V14's two existing indexes both have the wrong leading
column for a global `WHERE observed_at < $cutoff` scan). V1–V16 remain
byte-for-byte unchanged; Flyway's own checksum validation confirms
this on every `deploy-up.sh` run.

## 10. What was deliberately NOT built this round

- Actual hosting (Phase 17B): a real domain, real ACME certificate, a
  real SMTP provider's credentials, a real off-host backup
  destination, any cloud/VPS provisioning.
- A shared/durable rate-limit backing store (Redis) — explicitly out
  of scope per this round's own instructions.
- High availability / horizontal scaling for any service.
- Automated disk-pressure alerting (the existing internal Prometheus/
  Alertmanager stack could be pointed at a host-level `node_exporter`
  for this — not wired up this round).
- A container-registry-backed release/rollback scheme (images are
  built directly from the working tree this round — see
  `deploy/RELEASE_MANIFEST.md`'s own note).
