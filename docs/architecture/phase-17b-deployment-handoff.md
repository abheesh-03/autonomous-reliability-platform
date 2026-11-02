# Phase 17B — Live Deployment Record and Operator Handoff

## Current public address — updated 2026-11-02

- [Recorded demo](https://reliability.abheesh.dev/demo) — no account required.
- [Live console](https://reliability.abheesh.dev) and [sign-in](https://reliability.abheesh.dev/sign-in).

The operator migrated the deployment to `reliability.abheesh.dev` and confirmed the new address works. The migration output showed validated HTTPS 200 for `/demo`, preserved all private environment values except the public origin, and confirmed that only web-console and Caddy were recreated.

The server-only Caddy configuration now also handles the custom hostname, trusts the published Cloudflare proxy ranges for client-IP forwarding, and redirects browser requests on the original provider hostname to the new origin. The original exact OTLP metrics endpoint remains routed for the existing sample sender. Settings backups are stored privately under the Ubuntu user's `~/arp-domain-backups/`.

**The sections below preserve the original Phase 17B/18 record.** Their provider-hostname configuration and rollout guards describe the earlier deployment; the guards deliberately reject the newer Caddy configuration. Do not reuse that historical rollout block unchanged on the migrated server. The repository's local `tls internal` default remains unchanged.

This records the real, live Phase 17B deployment on top of Phase 17A's
own single-host configuration (`docs/architecture/phase-17a-deployment.md`,
`deploy/README.md`). It distinguishes facts **reported by the operator**
(the person who actually provisioned and operates the VPS — not
independently re-verified in this session) from checks performed
**in this session** against the local repository only. Nothing in this
document was executed as part of writing it; no SSH session, deploy,
or server change was made while producing Phase 18.

## 1. Infrastructure (operator-reported)

- Provider: **OVHcloud US, VPS-1 plan**, region **Vint Hill**, OS
  **Ubuntu 24.04**.
- Resources: **2 vCPU, ~4 GB RAM, 40 GB disk, 2 GB swap**.
- Price at purchase: **$5.35/month before tax** — the price actually
  selected at signup, not a guaranteed future rate.
- Original provider hostname: `vps-9037dd41.vps.ovh.us` (used during
  Phase 17B; see the current public address above).
- This is a **single-host MVP**, unchanged in kind from Phase 17A's own
  stated scope: no high availability, no automatic failover, no
  sustained-load or production SLA claim.

## 2. What was actually exercised on the live deployment (operator-reported)

- Public HTTPS reachable on the provider hostname.
- Real Gmail SMTP delivering verification and password-reset email;
  the operator confirmed a subsequent real login after following a
  real delivered link.
- A full, real tenant flow on the live deployment: sign-up,
  organization creation, service registration, authenticated OTLP
  JSON metrics ingestion, a real threshold-based incident created from
  that telemetry, and its automatic resolution once the threshold
  cleared.
- A real database backup: created, encrypted with `age`, copied off
  the VPS to the operator's Mac, decrypted there, and checked against
  the original file's checksum on both ends. **This confirms the
  backup/encryption/copy/decrypt pipeline integrity — it is not a
  database restore drill.** A real restore proof (standing up a second
  instance from that backup and confirming the application reads it
  correctly) remains a documented gap, not something this round
  claims.
- Backups are currently **manual**, run on demand by the operator —
  not yet scheduled or shipped off-host automatically.
- `INVESTIGATOR_LLM_PROVIDER` on the live deployment is **stub**; the
  embeddings provider is **local**. No paid LLM/embedding API is
  configured or billed on this deployment.
- Telemetry retention (`deploy/README.md`'s own retention job) is
  currently run in **dry-run mode** on the live deployment — it
  reports what it would delete, but does not delete anything yet.
- One real, reproduced client-side symptom, cause not fully isolated:
  accessing the site over the operator's normal home Wi-Fi produced a
  TLS error in the browser; the same Mac, on cellular data, loaded the
  application correctly immediately afterward. Plausible causes
  (a stale DNS/TLS session on that Wi-Fi network, a captive/filtering
  middlebox, a transient CDN/edge issue) were not individually ruled
  out — recorded honestly as unconfirmed, not diagnosed.

## 3. Reproducible configuration (no secret values)

The live deployment follows Phase 17A's own `deploy/` configuration
(`deploy/docker-compose.override.yml`, `deploy/caddy/Caddyfile`,
`deploy/scripts/init-deploy-secrets.sh`) with one intentional,
server-only change:

**`deploy/caddy/Caddyfile`'s `tls internal` line was removed on the
live server**, replaced with Caddy's default automatic public-CA
certificate issuance (Caddy obtains and renews a real publicly-trusted
certificate for the configured `DEPLOYMENT_PUBLIC_ORIGIN` once it is a
real, DNS-resolvable, publicly reachable hostname — exactly the
"actual, DNS-resolvable domain replaces the `tls internal` line below"
case that file's own comment already anticipated). **This change was
made only on the live server's own copy of the file — it is
deliberately NOT applied to this repository's `deploy/caddy/Caddyfile`**,
which must keep `tls internal` as its default so Phase 17A's own local
HTTPS proof (`deploy/README.md`'s "Local HTTPS proof" section) keeps
working with no real domain, exactly as designed. Reproducing the live
server's config means: take this repo's `deploy/caddy/Caddyfile`
unchanged, delete only the `tls internal` line, and point
`DEPLOYMENT_PUBLIC_ORIGIN` at a real, DNS-resolvable hostname.

Every other secret (`WEB_CONSOLE_DB_PASSWORD`, `BETTER_AUTH_SECRET`,
`SMTP_*` credentials, etc.) lives only in the server's own
`deploy/.env.deploy`, generated by `deploy/scripts/init-deploy-secrets.sh`
exactly as Phase 17A documents — this round introduces no new secret
and did not read the live server's real `.env.deploy`, SSH private
key, or any backup file.

## 4. Reviewed rollout / check / rollback procedure for the Phase 18 web-console change

**Documented only — not executed against the live server in this
session.** This reuses Phase 17A's own existing, already-proven
mechanism (`deploy/README.md`'s "Update"/"Rollback" sections) with no
new tooling; the only thing specific to Phase 18 is that it touches
`services/web-console` alone (a new `/demo` route tree, a new
`middleware.ts`, and new presentational components — no migration, no
new environment variable, no change to `deploy/docker-compose.override.yml`
or `deploy/caddy/Caddyfile`).

**A real bug was found and fixed as part of validating this change**
(in a real, disposable, isolated container build during this round —
not assumed): `services/web-console/Dockerfile`'s builder stage never
copied `middleware.ts` into the image, only `tsconfig.json`/
`next.config.ts`/`postcss.config.mjs`. Since `middleware.ts` is new
this round and is what tells `RootShell` a request is for `/demo`,
the real containerized production build silently never registered it
— `/demo`'s own content rendered correctly, but with none of its
dedicated navigation/chrome (confirmed via a real build + a real
browser check before and after the fix: the build output's own route
list gained a `ƒ Proxy (Middleware)` line, and the shell's "Recorded
demo" chrome text went from absent to present in the raw served HTML).
This is now fixed (`COPY tsconfig.json next.config.ts
postcss.config.mjs middleware.ts ./`) and would have affected a real
rollout to this very server had it shipped unfixed — worth calling
out explicitly here since it's exactly the kind of gap a step 3 check
below exists to catch.

The actual server checkout is `/home/ubuntu/autonomous-reliability-platform`,
currently detached at `1aaa31b1c91b1358ae804a7387aba8ed09d2cbf9`. Docker
commands require `sudo`. `--env-file` supplies Compose interpolation values;
it does not export `COMPOSE_PROJECT_NAME` into the calling shell. The known
project is therefore named explicitly below: `arp-deploy`.

After the reviewed Phase 18 commit has been pushed and CI has passed, replace
`PASTE_REVIEWED_40_CHARACTER_COMMIT_SHA` below with that exact commit. Run on
the VPS in Bash. This refuses unexpected checkout changes, preserves the
intentional Caddy edit and private environment file, tags existing images,
and updates only web-console. Use a detached checkout of the selected commit,
not `git pull` on a detached HEAD.

```bash
(
set -euo pipefail
cd /home/ubuntu/autonomous-reliability-platform
arp_target=PASTE_REVIEWED_40_CHARACTER_COMMIT_SHA
[[ "$arp_target" =~ ^[0-9a-f]{40}$ ]] || { echo "STOP: set the reviewed commit SHA"; exit 1; }
git diff --cached --quiet || { echo "STOP: staged changes exist"; exit 1; }
python3 - <<'PY'
from pathlib import Path
import subprocess

def git(*args):
    return subprocess.check_output(['git', *args])

changed = set(filter(None, git('diff', '--name-only', '-z').split(b'\0')))
if changed - {b'deploy/caddy/Caddyfile'} or git('ls-files', '--others', '--exclude-standard', '-z'):
    raise SystemExit('STOP: unexpected checkout changes; review without discarding them')
path = Path('deploy/caddy/Caddyfile')
original = git('show', 'HEAD:deploy/caddy/Caddyfile')
if original.count(b'\ttls internal\n') != 1 or path.is_symlink():
    raise SystemExit('STOP: unexpected Caddy baseline')
if path.read_bytes() != original.replace(b'\ttls internal\n', b'', 1):
    raise SystemExit('STOP: Caddy is not the reviewed public-HTTPS configuration')
PY
arp_env_before="$(sudo sha256sum deploy/.env.deploy)"
arp_caddy_before="$(sha256sum deploy/caddy/Caddyfile)"
sudo bash deploy/scripts/release-tag.sh

git fetch origin main
git merge-base --is-ancestor HEAD "$arp_target"
git merge-base --is-ancestor "$arp_target" origin/main
git diff --quiet HEAD "$arp_target" -- deploy/caddy/Caddyfile
git checkout --detach "$arp_target"
[[ "$(sudo sha256sum deploy/.env.deploy)" == "$arp_env_before" ]]
[[ "$(sha256sum deploy/caddy/Caddyfile)" == "$arp_caddy_before" ]]

arp_compose=(sudo docker compose --project-name arp-deploy
  --env-file deploy/.env.deploy
  -f docker-compose.yml -f deploy/docker-compose.override.yml)
"${arp_compose[@]}" build web-console
"${arp_compose[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 web-console
"${arp_compose[@]}" ps web-console
curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  -o /dev/null -w 'Recorded demo HTTPS status: %{http_code}\n' \
  https://vps-9037dd41.vps.ovh.us/demo
)
```

Check `/demo` while signed out: all four recorded views and their navigation
must render. Check `/sign-in` and `/register` for the recorded-demo link,
then verify normal sign-in and your existing workspace still work. No
migration or database reset is part of this rollout. Dependent services
are neither rebuilt nor recreated (`--no-deps`).

If needed, roll back **only web-console** using the existing tagged image,
then check readiness with the same Compose project and files:

```bash
(
set -euo pipefail
cd /home/ubuntu/autonomous-reliability-platform
sudo bash deploy/scripts/rollback.sh web-console
sudo docker compose --project-name arp-deploy --env-file deploy/.env.deploy \
  -f docker-compose.yml -f deploy/docker-compose.override.yml \
  up -d --no-deps --no-build --wait --wait-timeout 120 web-console
sudo docker compose --project-name arp-deploy --env-file deploy/.env.deploy \
  -f docker-compose.yml -f deploy/docker-compose.override.yml ps web-console
)
```

Rollback retags/recreates the prior image; it does not move Git HEAD back.
Before another release-tag, reconcile the checkout with the image actually
running so the script does not label an old image with a newer source SHA.
Keep the `:previous` image until the new deployment has been checked.

## 5. Limitations (unchanged in kind from Phase 17A, restated for this record)

- Single-host MVP: no HA, no automatic failover, no sustained-load or
  production SLA claim.
- Backups are manual. A verified encrypted off-host copy exists on the
  operator's Mac; scheduled backup creation and automatic off-host shipping
  are not configured.
- Telemetry retention is dry-run only on the live deployment; nothing
  is actually deleted yet.
- The Wi-Fi TLS access issue above remains unconfirmed in root cause.
