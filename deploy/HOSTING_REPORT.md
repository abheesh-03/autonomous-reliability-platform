# Phase 17A Hosting Decision Report

**Status: sizing/cost information only. Nothing in this report has
been provisioned, purchased, or deployed to any cloud provider.**
Actual hosting is Phase 17B, pending review of this report and an
explicit domain/provider/budget decision.

## 1. Measured resource usage (real, this round)

Measured against the actual, fully running 20-container deployment
stack (19 application/observability services + the one-time test-SMTP
receiver) on this developer's own Mac (Apple Silicon, arm64), via
`docker stats --no-stream` and `docker system df -v`.

### Idle (no load applied, all services healthy)

| Service | Memory (RSS) |
|---|---|
| control-plane | 71.5 MiB |
| web-console | 46.4 MiB |
| caddy | 54.0 MiB |
| postgres | 25.1 MiB |
| retrieval-service | 20.4 MiB |
| investigator-service | 17.7 MiB |
| agent-runtime-service | 32.2 MiB |
| tool-gateway | 4.4 MiB |
| tempo | 140.6 MiB |
| loki | 62.8 MiB |
| alloy | 39.6 MiB |
| inventory-service | 6.9 MiB |
| checkout-service | 211.1 MiB |
| prometheus | 38.0 MiB |
| alertmanager | 14.9 MiB |
| notification-service | 52.8 MiB |
| payment-service | 24.2 MiB |
| grafana | 134.1 MiB |
| otel-collector | 68.4 MiB |
| docker-socket-proxy | 16.9 MiB |
| **Total (real services only)** | **≈ 1.08 GiB** |

CPU at idle: effectively 0% across every service except brief,
sub-1% ticks from Loki/Tempo's own background compaction.

### Under light real load (50 sequential real telemetry-ingestion
requests through the public proxy)

| Service | Memory after burst | Memory growth |
|---|---|---|
| control-plane | 75.1 MiB | +3.7 MiB |
| web-console | 73.5 MiB | +27.1 MiB (first real request after idle; includes Next.js route compilation) |
| caddy | 58.1 MiB | +4.1 MiB |
| postgres | 35.0 MiB | +9.9 MiB |

Memory growth under this light load is modest and bounded — nothing
here suggests a leak or runaway consumer; a real production load test
(sustained, concurrent, over a longer window) is explicitly **not**
done this round and should precede any real capacity commitment in
Phase 17B.

## 2. Measured image/build sizes (real, this round)

| Image | Size |
|---|---|
| checkout-service (built) | 569 MB |
| web-console (built) | 439 MB |
| notification-service (built) | 433 MB |
| agent-runtime-service (built) | 355 MB |
| control-plane (built) | 308 MB |
| retrieval-service (built) | 296 MB |
| investigator-service (built) | 279 MB |
| payment-service (built) | 260 MB |
| retention-scheduler (built, new) | 233 MB |
| inventory-service (built) | 41.9 MB |
| tool-gateway (built) | 22 MB |
| **Total, this deployment's own built images** | **≈ 3.24 GB** |

Plus third-party pulled images (`pgvector/pgvector:pg18`,
`flyway/flyway:13.9.0`, `otel/opentelemetry-collector-contrib:0.161.0`,
`grafana/tempo:3.0.3`, `grafana/loki:3.7.8`, `grafana/alloy:v1.20.1`,
`prom/prometheus:v3.15.0`, `prom/alertmanager:v0.34.1`,
`grafana/grafana-oss:13.0.2`, `caddy:2.10.2-alpine`,
`tecnativa/docker-socket-proxy:v0.4.2`) — not separately re-measured
this round (these are the SAME pinned images the pre-existing
local-development stack already pulls, except the two new ones, which
are both small, single-digit-to-low-double-digit MB Alpine/static
binaries).

## 3. Measured volume disk usage (real, this round, moments after a
fresh deployment + light proof traffic — NOT a steady-state
production estimate)

| Volume | Size |
|---|---|
| `postgres_data` | 67.2 MB |
| `grafana_data` | 50.6 MB |
| `tempo_data` | 27.1 MB |
| `prometheus_data` | 1.6 MB |
| `loki_data` | 49.6 kB |
| `caddy_data`/`caddy_config` | ~5 kB |
| `alloy_data` | 126 B |

These numbers reflect minutes of real traffic, not a representative
production retention window — `postgres_data` in particular will grow
with real incident/audit/telemetry history (bounded for telemetry
specifically by the new retention tool, item 6; unbounded for
incidents/audit by design, since that data is intentionally permanent)
and should be re-measured after a real multi-week run before sizing a
production disk.

## 4. Candidate single-host sizing

Given the above (≈1.1 GiB idle RSS across all 19 real services, ≈3.2
GB of application images, a Postgres volume that will grow over time
but started under 100 MB after a fresh deploy):

| Tier | vCPU | RAM | Disk | Fits this stack? |
|---|---|---|---|---|
| Minimum | 2 | 4 GB | 40 GB SSD | Tight — idle RSS alone is ~1.1 GiB; OS + Docker overhead + image storage (~3.2 GB) + room for real Postgres growth leaves little headroom. Workable for a demo/evaluation deployment, not recommended for anything with real sustained traffic. |
| Recommended | 4 | 8 GB | 80 GB SSD | Comfortable headroom for the measured idle footprint, image storage, Postgres growth, and the explicitly-not-load-tested "real sustained traffic" case this round didn't exercise. |

Both tiers assume a single host running the ENTIRE stack (all 19
services) — there is no component this round recommends splitting
onto a second host; doing so would require revisiting the
network-isolation assumptions in §2 of
`docs/architecture/phase-17a-deployment.md`.

## 5. Required inputs before Phase 17B can provision anything

- A real domain name (for Caddy's real ACME certificate — this
  round's local proof uses Caddy's own local CA, never a public one).
- A real SMTP provider's credentials (host/port/user/password/from
  address) — this round's proof uses a disposable, non-public local
  test receiver (Mailpit), never a real mailbox.
- An off-host backup destination (object storage, a second host,
  etc.) and its own credentials — this round's backup tooling writes
  to a local directory only; shipping it off-host is a documented
  requirement, not implemented.
- An explicit provider/budget decision (below is pricing information
  only, not a recommendation or a purchase).

## 6. Illustrative current provider pricing (informational only — no
provisioning, no commitment)

Current, publicly listed on-demand pricing as of this round
(October 2026), for the "Recommended" tier (4 vCPU / 8 GB RAM / 80 GB
SSD) — **always confirm current pricing directly with the provider
before any real commitment; these figures are not re-verified after
this report is written.**

| Provider | Comparable instance | Monthly compute | Notes |
|---|---|---|---|
| DigitalOcean | Premium AMD Droplet, 4 vCPU / 8 GB | ~$48/mo | Includes some bandwidth; block storage for extra disk billed separately (~$0.10/GB/mo) |
| Hetzner Cloud | CPX31, 4 vCPU / 8 GB | ~€16–17/mo (~$17–18/mo) | Notably cheaper; EU-based (data-residency consideration) |
| AWS Lightsail | 4 vCPU / 8 GB plan | ~$40/mo | Includes a fixed bandwidth allowance |

**Separate, additional recurring costs not included above** (exact
amounts depend on the chosen provider/registrar — get current pricing
before committing):
- A domain name registration/renewal (~$10–20/year for a common TLD).
- Outbound SMTP: either a transactional-email provider's own monthly
  plan/per-email pricing, or the chosen compute provider's own SMTP
  relay restrictions (several providers block outbound port 25/587 by
  default on new accounts and require a support request to lift it —
  confirm this explicitly with whichever provider is chosen).
- Off-host backup storage (e.g. S3-compatible object storage — low
  single-digit dollars/month at this data volume, but priced per-GB
  by the provider actually chosen).
- A static/reserved public IPv4 address — several providers now
  charge separately for this (e.g. AWS's own IPv4 charge); confirm
  whether the chosen plan includes one.
- Data transfer beyond whatever allowance the chosen plan includes.
- Applicable sales/VAT tax, which varies by billing jurisdiction and
  is not reflected in any of the headline prices above.

No cost figure above has been paid, committed, or provisioned — this
section exists solely to inform a future Phase 17B budget decision.

## 7. Remaining deployment steps (Phase 17B)

1. Choose a provider, tier, and domain; register the domain.
2. Point DNS at the provisioned host's public IP.
3. Set `DEPLOYMENT_PUBLIC_ORIGIN` to the real domain and
   `DEPLOYMENT_TLS_MODE`-equivalent Caddy config to real automatic
   ACME (remove the `tls internal` line in `deploy/caddy/Caddyfile` —
   see that file's own comment).
4. Obtain real SMTP credentials from a real provider; set `SMTP_*` in
   `deploy/.env.deploy` accordingly; remove
   `ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF`.
5. Set up an off-host destination for `deploy/scripts/backup.sh`'s
   own output (e.g. a cron job that runs the backup then syncs
   `$BACKUP_OUTPUT_DIR` to object storage with server-side
   encryption).
6. Run `./deploy/scripts/preflight.sh` then `./deploy/scripts/
   deploy-up.sh` against the real host.
7. Perform a real, sustained load test before treating this as
   production-ready — this round's own load evidence (§1) is light
   and short-duration only.
