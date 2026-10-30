# Phase 17A — Single-Host Deployment

A deployable, hardened, single-host Docker Compose configuration for
the Autonomous Production Reliability Platform, under `deploy/`,
**completely separate from** the repository root's own
`docker-compose.yml` (the local-development workflow, unchanged by
this phase). See `docs/architecture/phase-17a-deployment.md` for the
full design rationale; this file is the operational runbook.

## What this is, and isn't

This is a **single-host MVP**. There is no high availability, no
automatic failover, and no horizontal scaling story for the rate
limiters or the Postgres instance. A host reboot, a `docker compose
restart`, or a bad deploy all cause real, if brief, downtime — this
is honestly documented, not hidden. Actual hosting (a real domain,
real ACME TLS, a real SMTP provider, a real off-host backup
destination, a real cloud/VPS provider) is **Phase 17B** — nothing in
this phase provisions, pays for, or registers anything external.

## Prerequisites

- Docker Compose **v2.24.4 or later** (this round was tested against
  v5.1.3) — required for the `!override` YAML merge-key tag
  `deploy/docker-compose.override.yml` uses throughout to replace
  (never concatenate onto) the base file's own development port
  bindings. `deploy/scripts/preflight.sh` verifies this is working
  correctly on your actual installed version every time, not merely
  once.
- A real domain you control, for Phase 17B — for THIS phase's local
  proof, no real domain is needed at all (see "Local HTTPS proof"
  below).

## One-time setup

```bash
./deploy/scripts/init-deploy-secrets.sh
# Edit deploy/.env.deploy: set DEPLOYMENT_PUBLIC_ORIGIN to a real
# https:// origin (or the local-proof test domain below), and SMTP_*
# to a real provider (or the local test receiver below).
./deploy/scripts/preflight.sh
```

`preflight.sh` fails closed on: a placeholder/missing
`DEPLOYMENT_PUBLIC_ORIGIN`, missing/placeholder secrets, organization
enforcement disabled, insecure cookies, relaxed auth rate limits, an
ambiguous legacy-ingestion setting, a disabled/wildcard trusted-proxy
configuration, missing SMTP configuration, and (programmatically,
re-derived every run, never a stale assumption) any non-proxy service
publishing a port in the fully merged Compose configuration. It never
prints a secret value.

## Deploy

```bash
./deploy/scripts/deploy-up.sh
./deploy/scripts/deploy-status.sh
```

`deploy-up.sh` runs the preflight first and refuses to continue on any
failure, then: starts `postgres` alone, applies every migration in
`database/migrations/` (V1–V17 — V1–V16 byte-for-byte unchanged, V17
newly added this round, additive only) via the existing `flyway`
service, creates the four
least-privileged runtime roles (`control_plane_app`, `retrieval_app`,
`web_console`, `agent_runtime` — see `deploy/sql/
01-create-runtime-roles.sql.template`), applies Better Auth's own
schema, then brings up the full stack.

## Update (code rollout)

```bash
git pull   # or check out the release you want
docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file deploy/.env.deploy \
  -f docker-compose.yml -f deploy/docker-compose.override.yml up -d --build
```

This never touches the database schema — only application containers
are rebuilt/recreated. A real restart (`docker compose restart
web-console control-plane`, or a full `up -d --build`) preserves all
durable state (Postgres data, agent checkpoints, telemetry) because
none of it lives in a container's own writable layer.

## Rollback (code only — not a disaster restore)

```bash
# BEFORE a rollout, make the version about to be replaced
# identifiable and recoverable (tags it with the git commit it was
# built from, plus a floating `:previous` pointer):
./deploy/scripts/release-tag.sh

# ... roll out the new version as usual (git pull; up -d --build) ...

# If the new version needs to be rolled back:
./deploy/scripts/rollback.sh                  # every application service, back to :previous
./deploy/scripts/rollback.sh web-console      # just one service, back to :previous
./deploy/scripts/rollback.sh web-console a1b2c3d   # one service, to an exact git-sha tag
```

CORRECTION ROUND: this previously showed `up -d --no-deps <service>`
as "the" rollback command. That alone selects no specific previous
image at all — with no explicit `image:` field and no registry in
this phase (see `deploy/RELEASE_MANIFEST.md`'s own "Application
release identity" note), Compose resolves a `build:`-only service
back to whatever is CURRENTLY tagged `:latest`, which after a rollout
already IS the new version — so that command was a no-op, not a
rollback. `rollback.sh` first retargets `:latest` at the preserved,
previously-tagged image, then recreates the service with
`--no-deps --no-build` (so Compose reuses that retargeted image
rather than building the current working tree again) — confirmed
directly: tagging two real, distinguishable images, rolling "out" the
second, then running the same retag-and-recreate logic this script
uses, measurably restores the first image's own identity and
behavior, not merely a plausible-looking command.

A code rollback only ever swaps which application image is running
against the EXISTING, unmodified database/schema — it is only safe
between versions that share the same migration state (never roll back
past a migration that has already run; that is a schema change, not a
code one, and this repository's own Flyway convention has no
"migrate down"). This is distinct from the disaster-recovery restore
below, which replaces the database itself.

## Backup and restore

See `deploy/scripts/backup.sh` / `deploy/scripts/restore.sh` for the
real tooling and their own header comments for the exact guarantees.
**A local backup file on this same host does not protect you against
loss of the host itself** — shipping the backup artifact to a
separate, off-host, encrypted destination (object storage with
server-side encryption, a separate backup host, etc.) is a required
operational step this phase documents but does not implement or
provision (Phase 17B).

```bash
./deploy/scripts/backup.sh                    # writes to $BACKUP_OUTPUT_DIR
./deploy/scripts/restore.sh <artifact> --target-project <disposable-name>
```

Never run `restore.sh` against this deployment's own running project,
or the developer's local-development stack — it refuses to run against
a target that isn't obviously fresh/disposable.

## Telemetry retention

```bash
python3 scripts/prune-telemetry-samples.py            # dry run (default)
python3 scripts/prune-telemetry-samples.py --execute   # real deletion, batched
```

The `retention-scheduler` sidecar (`deploy/docker-compose.override.yml`)
runs this automatically every `TELEMETRY_RETENTION_INTERVAL_HOURS`
(default 24h), honoring `TELEMETRY_RETENTION_DRY_RUN`
(default `true` — set to `false` in `deploy/.env.deploy` once you've
reviewed at least one real dry-run report) and
`TELEMETRY_RETENTION_DAYS` (default 30). Its failure path is
observable: `docker compose logs retention-scheduler` shows a `FAIL:`
line with the run's own start time and exit code on any error, and the
container keeps retrying on the next scheduled tick rather than
crash-looping. Only `reliability.telemetry_samples` is ever touched —
incidents, audit events, credentials, and auth/checkpoint data are
never in scope for this tool.

## Local HTTPS proof (no real domain needed)

Caddy's own built-in local certificate authority ("tls internal" in
`deploy/caddy/Caddyfile`) issues a real certificate for whatever
`DEPLOYMENT_PUBLIC_ORIGIN` you configure — including a non-resolvable
test domain, for local proof:

```bash
# In deploy/.env.deploy:
DEPLOYMENT_PUBLIC_ORIGIN=https://arp-deploy.test

./deploy/scripts/deploy-up.sh

# Extract Caddy's own local CA root certificate:
docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file deploy/.env.deploy \
  -f docker-compose.yml -f deploy/docker-compose.override.yml \
  cp caddy:/data/caddy/pki/authorities/local/root.crt ./deploy/caddy_root.crt

# Explicit client trust -- never -k, never a global TLS-verification
# bypass:
curl --resolve arp-deploy.test:443:127.0.0.1 --cacert ./deploy/caddy_root.crt \
  https://arp-deploy.test/
```

This is a real, dedicated test CA (Caddy's own, generated fresh for
this deployment) — never a globally/publicly trusted one, and this
procedure never claims otherwise.

## Trusted-proxy boundary (rate limits)

Caddy is the only path into this deployment (no other service
publishes a port). It OVERWRITES `X-Forwarded-For` with the real
connecting client's address on every proxied request — a client's own
forged value is always discarded at the edge, never forwarded.
`control-plane` (`core/trusted_proxy.py`) and `web-console` (Better
Auth's own `advanced.ipAddress.ipAddressHeaders`) trust that header
ONLY on a connection whose real, direct TCP peer independently
resolves to the configured `TRUSTED_PROXY_HOSTS` (`caddy`) — never a
wildcard, never "all private addresses." See
`services/control-plane/tests/test_trusted_proxy.py` for the unit
proof and the CI job's own "Spoofed X-Forwarded-For does not bypass"
step for the real, running-stack proof.

**Known limitation**: both of this platform's rate limiters
(`core/rate_limit.py`'s telemetry limiter, Better Auth's own
browser-auth limiter) are in-process, in-memory. This deployment runs
exactly ONE `control-plane` replica and ONE `web-console` replica —
scaling either to more than one replica without a shared backing
store (Redis, etc.) would silently split each limiter's own budget
across replicas, weakening it. A process restart resets every budget
to zero. Neither limiter is shared or durable, and this phase does not
change that (a Redis migration is explicitly out of scope this round).

## Legacy ingestion boundary

`CONTROL_PLANE_ALLOW_LEGACY_INGESTION=true` is this deployment's
tested default — the internal demo stack (Alertmanager →
control-plane's own webhook) keeps producing real demo incidents in
the single, fixed legacy organization. This is safe here specifically
because that path is **never reachable through Caddy** —
`deploy/caddy/Caddyfile` defines no route for
`/api/v1/alertmanager/webhook`, `/api/v1/incidents/*/status`, or any
other control-plane route besides the one exact telemetry-ingestion
path; every one of those requests Caddy actually receives falls
through to web-console instead, which has no matching route either. A
deployment that wants the legacy demo pipeline fully disabled instead
of merely network-isolated should set this to `false`, after which
`POST /internal/v1/alertmanager/webhook` fails closed (503).

## Observability Docker-socket access

`alloy` (container log shipping) talks to a NEW `docker-socket-proxy`
sidecar over TCP, never a direct bind-mount of the real Docker socket.
The proxy allowlists `CONTAINERS=1` (list/inspect/stream logs) only —
every mutating category (`POST`) and every other read category
(images, networks, volumes, exec, services, swarm, system, info, ...)
is explicitly `0`.

**Network isolation (correction round)**: `docker-socket-proxy` lives
on its own dedicated, `internal: true` Compose network
(`docker-socket-proxy-internal`) that only `alloy` also joins —
confirmed directly via the real merged `docker compose config` output,
not merely this file's own claim. Previously it had no `networks:` key
at all and so sat on the same flat default network as every other
service in this stack (postgres, control-plane, web-console, ...),
none of which have any legitimate reason to reach it; none of them can
reach it at all now.

**Known residual exposure, honestly stated**: network isolation and
the `CONTAINERS=1`-only allowlist narrow WHO can reach the proxy and
WHAT category of call it accepts, but neither narrows WHICH containers
it can see once reached. The real Docker socket it proxies to is the
HOST's socket, which is not scoped to this Compose project at all —
`alloy` (and anyone who compromises `alloy` or this one sidecar) can
still list, inspect, and (via `GET .../containers/{id}/archive`)
read-only-export the filesystem of EVERY container on the Docker
host, including ones that have nothing to do with this deployment.
This is an inherent property of talking to the host socket at all,
not something the allowlist or network placement removes; narrower
than the raw socket (which also permits container creation with
arbitrary host mounts, exec into any container, and swarm control),
but a real, remaining boundary a reader should know about rather than
assume away.

## Runbook: readiness / health

```bash
./deploy/scripts/deploy-status.sh
```

Shows container health (dependency-aware — Docker Compose's own
`condition: service_healthy` ordering already gates startup), named-
volume disk usage for this deployment's own project, and a real HTTPS
reachability probe through Caddy.

## Disk/volume monitoring guidance

Watch, at minimum: the `postgres` data volume (grows with incidents,
audit events, telemetry — retention bounds the telemetry table
specifically, nothing else yet), the `alloy_data` volume (log-shipping
position state, small and stable), and `caddy_data` (certificates,
small and stable). `docker system df -v` (also shown by
`deploy-status.sh`) is the simplest way to watch all three on a
single host; nothing in this phase wires up an alert on disk
pressure — a real deployment should add host-level disk-space
alerting (e.g. via the existing Prometheus/Alertmanager stack already
running internally, pointed at `node_exporter`'s own filesystem
metrics — not wired up this round).

## Release manifest

See `deploy/RELEASE_MANIFEST.md` — the pinned image/tag list for every
third-party image this configuration uses, generated from this exact
round's own `docker-compose.override.yml`.
