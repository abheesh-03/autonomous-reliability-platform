# Screenshot provenance

Captured 2026-10-31 against a fully disposable, isolated copy of this
repository (fresh checkout, fresh Postgres volume, its own Docker
Compose project with every host port offset by +10000, torn down
completely afterward) — never the developer's own long-running dev
stack, never any pre-existing data.

## How the disposable stack was built

From an `rsync` copy of the repository, with every host-side port in
`docker-compose.yml` offset by 10000 (e.g. `8000→18000`, `3101→13101`)
and `WEB_CONSOLE_TRUSTED_ORIGIN` updated to match:

```
make check
make db-up
make db-migrate
make db-status
```

All four completed successfully on the first real fresh-start run — no
service crash-looped before migrations existed, and `make db-up`'s own
documented ordering (webhook/remediation secrets → Postgres →
`init-agent-runtime-db.sh`/`init-web-console-db.sh` → full stack)
worked exactly as written.

One real, pre-existing default needed to be set explicitly for this
demo: `PAYMENT_FAULT_INJECTION_ENABLED=true` (the fault-injection
endpoint is disabled by default — a deliberate safety default, not a
bug). This has no effect on the real dev stack's own `.env`.

## How the screenshots were produced

- **dashboard.png**, **incident-detail.png**, **investigation-workspace.png**:
  a real `checkout-service is returning HTTP 5xx errors` incident,
  produced end-to-end by this repository's own existing Playwright
  acceptance spec (`services/web-console/e2e/phase9-workflow.spec.ts`)
  run against the disposable stack: real controlled payment-fault
  injection → real sustained failing traffic → a real Prometheus alert
  → a real Alertmanager webhook → a real incident → a real AI
  investigation → real human approval → real tool-gateway remediation
  execution → real recovery verification → real resolution, entirely
  through the real HTTP APIs (no mocked backend, no DOM edits). Took
  8.4 real minutes end to end, exit 0.
  - Incident id: `260cd9d7-cbdf-4e2f-b20b-29b8516bf425`
  - Agent run id: `e67019a3-40f3-48a8-94ac-a5a66c3888e4` (status
    `completed`, real `investigation_report`, `remediation_proposal_id`,
    and `recovery_verification` all present, confirmed via a direct
    `GET /api/v1/agent-runs/{id}` before capture)
  - **`INVESTIGATOR_LLM_PROVIDER=stub` was forced for this disposable
    stack's `.env` — the investigation used investigator-service's own
    deterministic stub provider. No real/paid LLM call was made.**

- **service-telemetry.png**: a real sign-up → real logged-link email
  verification → real organization membership → real service
  registration via the real BFF route (`POST /api/services`) → a real
  integration credential (`POST /api/services/{id}/integrations`) →
  one real metric exported with the **official OpenTelemetry Python
  SDK** (`opentelemetry-exporter-otlp-proto-http`) to this disposable
  stack's control-plane, over the local-dev fallback endpoint
  (`http://127.0.0.1:<offset-port>/api/v1/telemetry/otlp/v1/metrics` —
  no Caddy/HTTPS involved, matching real local-dev behavior). Confirmed
  landed in `reliability.telemetry_samples` by direct query before
  capture.
  - Service id: `cd7658b8-fc99-417c-85f9-e0a23772e62d`

## Capture command

```
WEB_CONSOLE_URL=http://127.0.0.1:13101 \
WEB_CONSOLE_TRUSTED_ORIGIN=http://127.0.0.1:13101 \
CONTROL_PLANE_URL=http://127.0.0.1:18000 \
AGENT_RUNTIME_URL=http://127.0.0.1:18003 \
README_AGENT_RUN_ID=e67019a3-40f3-48a8-94ac-a5a66c3888e4 \
README_SERVICE_ID=cd7658b8-fc99-417c-85f9-e0a23772e62d \
WEB_CONSOLE_DB_PASSWORD=<this disposable stack's own generated value> \
POSTGRES_DB=reliability_platform_dev POSTGRES_PORT=15432 POSTGRES_TEST_HOST=127.0.0.1 \
npx tsx services/web-console/e2e/capture-screenshots.ts
```

All four images were captured at a 1440×900 viewport. Correction:
**`dashboard.png` is actually 1440×902** (the capture command above
used an earlier version of `capture-screenshots.ts`, where this one
shot still defaulted to `fullPage: true` — its real page content is 2px
taller than the viewport, so the saved PNG is 2px taller too); the
other three (`incident-detail.png`, `investigation-workspace.png`,
`service-telemetry.png`) are exactly 1440×900, `fullPage: false`. (Verified
directly from each PNG's own header, not assumed.) `capture-screenshots.ts`
has since been corrected so a future recapture would also cap the
dashboard shot to exactly 1440×900 — but per this round's own
instructions, these four files were kept byte-for-byte unchanged and
were not recaptured. Three are in light theme, the investigation
workspace in dark theme (`newContext({ colorScheme: "dark" })`, a real
OS dark mode, not a hand-set DOM attribute) — kept as its own
established screenshot in this repo's prior rounds, and reads cleanly
alongside the light ones.

## Checked before accepting each image

Each image was visually inspected. None show a sign-in redirect, an
error page, or a loading state. No bearer tokens, credential dialogs,
personal emails, AWS account details, or browser chrome appear in any
frame — the one credential identifier visible in `service-telemetry.png`
(`cred_ARg_Gvs4A4E0g2hg_3EbVw`) is a public credential *id*, not the
secret bearer token itself (which is never rendered by this UI at all
after creation).

## Teardown and real-stack safety check

The disposable stack was torn down completely
(`docker compose down -v --rmi local`) and its isolated checkout
directory deleted. Before and after, the real dev stack's own
containers (`autonomous-reliability-platform-*`) and its real
`reliability_platform_dev` database row counts were confirmed
unchanged: 169 incidents, 3 services, 33 users, 12 telemetry samples,
19 organizations — identical before and after this capture round.
