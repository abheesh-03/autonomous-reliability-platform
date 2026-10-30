# Phase 17A Release Manifest

Generated for this round, against baseline HEAD
`0bbb73dd6b6f0bdbd1cfeb743264f3bf792a75f2`. Every third-party image
this deployment configuration pulls, with its pinned tag — no
`:latest` anywhere in `docker-compose.yml` or
`deploy/docker-compose.override.yml`.

## Application images (built from this repository, not pulled)

| Service | Build context | Base image |
|---|---|---|
| control-plane | `services/control-plane` | `python:3.13-slim` |
| retrieval-service | `services/retrieval-service` | `python:3.13-slim` |
| investigator-service | `services/investigator-service` | `python:3.13-slim` |
| agent-runtime-service | `services/agent-runtime-service` | `python:3.13-slim` |
| tool-gateway | `services/tool-gateway` | `gcr.io/distroless/static-debian12:nonroot` |
| checkout-service | `services/checkout-service` | `eclipse-temurin:21-jre` |
| payment-service | `services/payment-service` | `python:3.13-slim` |
| inventory-service | `services/inventory-service` | `gcr.io/distroless/static-debian12:nonroot` |
| notification-service | `services/notification-service` | `node:24-slim` |
| web-console | `services/web-console` | `node:24-slim` |
| retention-scheduler | repo root, `deploy/retention-scheduler.Dockerfile` (NEW this round) | `python:3.13-slim` |

Every one of these runs as a non-root user inside its container
(`app`, `node`, or `nonroot` — audited this round; see
`docs/architecture/phase-17a-deployment.md`'s own table).

## Third-party images (pulled, pinned by tag)

| Image | Tag | Role | Pinned by |
|---|---|---|---|
| `pgvector/pgvector` | `pg18` | PostgreSQL 18 + pgvector | base compose (unchanged) |
| `flyway/flyway` | `13.9.0` | migrations | base compose (unchanged) |
| `otel/opentelemetry-collector-contrib` | `0.161.0` | OTel Collector | base compose (unchanged) |
| `grafana/tempo` | `3.0.3` | traces | base compose (unchanged) |
| `grafana/loki` | `3.7.8` | logs | base compose (unchanged) |
| `grafana/alloy` | `v1.20.1` | log shipping | base compose (unchanged) |
| `prom/prometheus` | `v3.15.0` | metrics | base compose (unchanged) |
| `prom/alertmanager` | `v0.34.1` | alerting | base compose (unchanged) |
| `grafana/grafana-oss` | `13.0.2` | dashboards | base compose (unchanged) |
| `tecnativa/docker-socket-proxy` | `v0.4.2` | **NEW this round** — allowlisted Docker API access for Alloy | `deploy/docker-compose.override.yml`, verified pullable |
| `caddy` | `2.10.2-alpine` | **NEW this round** — the one public-facing reverse proxy | `deploy/docker-compose.override.yml`, verified pullable |

## Application release identity

This deployment's own application images are built directly from this
exact checkout (`docker compose ... up -d --build`) — there is still
no separate container REGISTRY in this phase. CORRECTION ROUND:
there is now a real, local tag-per-release scheme --
`deploy/scripts/release-tag.sh`, run before each rollout, tags every
currently-running application image with the git commit it was built
from (plus a floating `:previous` pointer), and
`deploy/scripts/rollback.sh` retargets `:latest` at a previously
tagged image and recreates the service WITHOUT rebuilding -- see
`deploy/README.md`'s "Rollback" section. Phase 17B (actual hosting)
should still adopt a real registry (pushing those same git-SHA tags
to it) so a rollback target survives this host's own local Docker
image cache being cleared, which this local-only scheme cannot
protect against.
