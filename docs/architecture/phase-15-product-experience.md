# Phase 15 — Premium SaaS Product Experience

## 1. Product scope

Phase 15 redesigns the operator web console (`services/web-console`) into a
coherent, application-agnostic reliability product: a real dashboard, a
polished incident/investigation workflow, a minimal service registry, and an
honest integrations page. It does **not** replace any backend reliability
capability built through Phase 14 — every mutation, every tenant-isolation
check, every approval gate, and every allowlisted remediation action is
unchanged. The payments/checkout/inventory/notification services remain
exactly what they always were: an internal demonstration environment used to
produce real incidents for the platform to investigate and remediate, never
the product itself.

## 2. UX / navigation architecture

One application shell (`components/shell/`) wraps every authenticated page:

- **Desktop**: a persistent left sidebar (Overview / Platform / Workspace
  groups) and a compact top bar (organization switcher, theme toggle, account
  menu).
- **Mobile**: the sidebar collapses into a Radix Dialog-based sheet, opened
  from a hamburger button in the top bar.
- Unimplemented nav destinations are shown disabled with a tooltip
  explaining why, never linked to a fake page (Gate 3).

`components/shell/root-shell.tsx` picks between three real, session-derived
layouts — no session (minimal, centered), a session with no resolved
organization (minimal top bar, pointing at `/organizations`), or a fully
resolved actor (the full shell). It is a presentation decision only; it is
never itself a security boundary — every protected page still independently
calls `requireActorOrRedirect()`, and the real boundary remains each
backend's own signed-assertion verification, unchanged from Phase 14.

## 3. Design system

- **Tailwind CSS v4** (`@tailwindcss/postcss`), with semantic design tokens
  defined once in `app/globals.css` (`--bg`, `--surface`, `--fg`, `--accent`,
  severity/status colors, …) and mapped into Tailwind's `@theme` so utilities
  like `bg-surface`/`text-fg-muted` stay correct across both themes.
- **Dark (deep navy/slate) by default**, with a cohesive light theme toggled
  via `data-theme` on `<html>`, persisted in `localStorage`
  (`components/theme/`). An inline pre-hydration script avoids a flash of
  the wrong theme.
- **Radix UI primitives** (Dialog, DropdownMenu, Tabs, Tooltip, Toast) for
  accessible interactive components, wrapped in `components/ui/` with
  consistent styling (`class-variance-authority`, `tailwind-merge`).
- **lucide-react** for iconography.
- A small, dependency-free **custom SVG chart** (`components/dashboard/
  activity-chart.tsx`) for the incident-activity visualization — chosen
  deliberately over a third-party charting library to avoid any React
  19/Next 16/Turbopack compatibility risk, given the scope of this phase.
- Every dependency's React 19 / Next.js 16 peer-dependency compatibility was
  checked (`npm view ... peerDependencies`) before installation.
- Focus-visible outlines, semantic HTML, and `prefers-reduced-motion`
  support are defined globally in `app/globals.css`.

## 4. Routes and screens

| Route | Status | Notes |
|---|---|---|
| `/` | Rewritten | Real dashboard (Gate 4) |
| `/incidents`, `/incidents/[id]` | Re-skinned | Same data/logic, new visual system |
| `/agent-runs/[id]` | Re-skinned | AI investigation workspace (Gate 6) |
| `/services` | New | Service registry (Gate 7) |
| `/integrations` | New | Honest integration status (Gate 8) |
| `/organizations` | Re-skinned | Team & organization management |
| `/system` | Re-skinned | Platform-internal health, explicitly distinguished from customer services |
| `/sign-in`, `/register`, `/unauthorized` | Re-skinned | Polished auth UX (Gate 9) |

**Re-skinned** means every literal text string, ARIA role, and heading that
the existing Vitest/Playwright suite depends on was preserved exactly — only
inline styles were replaced with the new design system. This was a
deliberate, conservative choice: the Phase 9/14 acceptance suite was
expensive to get passing, and a visual redesign is not a reason to risk
regressing it.

## 5. Frontend-to-backend data flow

Unchanged architecture (Gate 10): Browser → Next.js server routes (real
session + signed service assertion) → control-plane / agent-runtime-service
/ investigator-service → PostgreSQL / observability systems. No internal
credential or static token is ever sent to the browser. New mutations
(service registration) follow the exact same BFF-only pattern as every
existing mutation (`app/api/services/route.ts`).

### New backend surface

- **`GET /api/v1/dashboard/summary`** (control-plane) — one new,
  organization-scoped, bounded aggregate endpoint
  (`repositories/dashboard_repository.py`) backing the entire dashboard:
  status counts, a bounded "needs attention" list, bounded pending
  approvals, a zero-filled daily activity window, and a bounded recent-
  events feed. Every query is a real, indexed SQL query with a fixed
  `LIMIT` — the dashboard never fetches every incident to compute a chart
  client-side.
- **`GET`/`POST /api/v1/services`** (control-plane) — the services registry
  (Gate 7). Backed by `database/migrations/V12__create_services_registry.sql`
  (additive; V1–V11 untouched). Always requires a real, verified actor via
  a new `require_actor_context` dependency — unlike every pre-Phase-14
  endpoint, this brand-new resource has no legacy "unscoped" precedent to
  preserve, so it is tenant-scoped unconditionally, in both legacy and
  secure mode.

### A real bug this round found and fixed

`require_actor_context` originally wrapped the existing nullable
`get_actor_context`, whose own first line returns `None` unconditionally
whenever `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` is disabled — this
platform's own real local-development default. That meant a genuinely
valid, correctly-signed web-console assertion was being rejected with 401
on every default-configuration deployment, discovered by inspecting the
live dashboard's own real "Services" card (`This server could not
authenticate to the backend.`) before it was ever specified in a test.
Fixed by making `require_actor_context` independently verify the real
assertion unconditionally, and covered by a new regression test
(`test_a_real_valid_assertion_succeeds_even_with_organization_context_enforcement_disabled`).

A second real bug: the Docker builder stage never copied
`postcss.config.mjs`, so Tailwind never actually ran inside the production
image — the `@theme` block shipped raw, unprocessed CSS, and the entire UI
would have rendered unstyled. Found by inspecting the actual compiled CSS
inside a real, uncached Docker build, not assumed from a passing `next
build` on the host. Fixed in `services/web-console/Dockerfile`.

A third: `IntegrationCard` (a Client Component) originally received a
`LucideIcon` component reference as a prop directly from a Server
Component page — React rejects passing functions across that boundary.
Found by inspecting real browser console/server errors during screenshot
capture, not by a type-level check (TypeScript does not currently catch
this class of error). Fixed by splitting the interactive "View setup
guide" dialog into its own small Client Component that receives only
plain, serializable data.

A fourth, found while re-running `scripts/verify-phase14-multitenant-
security.sh` against the Phase-15-redesigned web-console: that script's
own test harness bind-mounts the host's `node_modules` directly into its
disposable Linux web-console container, then ran `npm run dev`. Tailwind
v4's `lightningcss` native dependency ships a platform-specific prebuilt
binary (`lightningcss-{platform}-{arch}-{libc}`); the host's own
`node_modules` was resolved for macOS/darwin-arm64, so the Linux container
failed with `Cannot find module '../lightningcss.linux-arm64-gnu.node'`.
This is **not** a regression in the application or its real Docker build
— the real `Dockerfile`, the real CI pipeline, and the real Playwright
acceptance run all build and run the production bundle (`next build` /
`next start`) inside the container from a clean `npm ci`, so they never
inherit the host's native binary. Confirmed via a disposable debug
reproduction: adding an isolated `node_modules` volume plus a real
container-side `npm ci` installed the correct
`lightningcss-linux-arm64-gnu` package (verified present on disk), yet
the same error still occurred — isolating this further to a
**Turbopack dev-mode-specific** bundler limitation, since switching the
same container to the production path (`next build && next start`)
resolved it immediately. Fixed by changing
`scripts/verify-phase14-multitenant-security.sh`'s own web-console
container command from `npm run dev` to `npm ci && npm run build && npx
next start`, matching the same production-mode path every other real
verification in this platform already uses. Re-ran the full script
afterward: `34 passed, 0 failed`.

## 6. Supported incident and service data

Every number and list on the dashboard is sourced from a real, bounded
backend query — no fabricated statistics, no invented customer/service
names, no hardcoded uptime percentage. An organization with zero incidents
and zero registered services sees a genuine, honest empty state with a
clear next action, never a fake chart.

## 7. Services (Gate 7)

A minimal, durable, organization-scoped catalog
(`reliability.services`) that a user explicitly registers. It is
**deliberately not a health/telemetry table**: there is no real
OpenTelemetry resource-correlation capability implemented yet to populate
a `connected`/`healthy` field truthfully, so no such column exists. The
web console always renders a registered service's connection status as
"Not connected" — never automatically healthy — consistent with Gate 7's
explicit requirement to separate "registered" from "observed" from
"healthy."

Independent-review correction round: `GET /api/v1/services` is now
genuinely paginated (bounded `limit`/`offset`, a real `COUNT`-derived
`total`, deterministic `created_at DESC, id DESC` ordering) — see §15.
Registration (`POST /api/v1/services`) now requires one of
`OWNER`/`ADMIN`/`ENGINEER` (`core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES`),
enforced in control-plane itself, not merely hidden in the UI.

## 8. Integration capabilities vs. limitations (Gate 8)

The Integrations page shows three real, honestly-stated pathways:

- **OpenTelemetry** — `configuration_required`. The same collector pipeline
  already powers this platform's own demo services (Prometheus/Loki/Tempo
  ingestion), but it is shared and platform-operated, not per-organization.
  Tenant-scoped, self-service OTLP onboarding (a credentialed endpoint your
  own services push to, with cross-tenant denial enforced) is **not**
  implemented this phase.
- **Kubernetes** — `operator_only` (independent-review correction round:
  previously `not_yet_supported`, which risked implying the capability was
  wholly absent). A real, read-only observer exists at the platform level
  (Phase 12A) for an operator-configured cluster; self-service,
  organization-scoped cluster enrollment is not implemented.
- **AWS (read-only)** — `operator_only`, same reasoning. Backed by Phase
  13's real read-only observer.

This is the deliberate, explicitly-permitted fallback (truthful guided
setup + a clearly unavailable activation state + a documented backend
blocker) rather than an unsafe shortcut. No integration is ever shown as
`connected` unless it genuinely is — none are, today, for a newly
registered organization. No AWS API calls, no Terraform apply, no live
Kubernetes writes were made or enabled this phase.

## 9. Security and tenant trust boundaries

- No change to Better Auth session handling, service-assertion signing/
  verification, or any Phase 14 tenant-isolation check.
- The `/api/v1/dashboard/summary` and `/api/v1/services` endpoints are both
  unconditionally organization-scoped in both legacy and secure mode —
  independent-review correction round, BLOCKER 1: `dashboard/summary`
  originally followed the legacy-vs-secure-mode convention every
  pre-existing read endpoint uses (unscoped when
  `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` is disabled); since this is
  a brand-new Phase 15 resource with no pre-Phase-14 unscoped precedent to
  preserve, it now requires a real, verified actor unconditionally, exactly
  like `/api/v1/services` already did (see §15).
- `POST /api/v1/services` additionally enforces a role gate
  (`OWNER`/`ADMIN`/`ENGINEER` only) — independent-review correction round,
  BLOCKER 2 (see §15).
- Verified for real against the live stack: `verify-phase14-multitenant-
  security.sh` (34 checks) and `verify-retrieval-tenant-isolation.sh` (17
  checks), both with secure mode genuinely enabled, both still pass
  unmodified.
- No weakening of human-approval gates, Kubernetes/payment remediation
  allowlists, or AWS read-only restrictions.

## 10. Tests and browser acceptance

- Full Vitest suite (226 tests, after the independent-review correction
  round added a dashboard pending-approvals-count case) passes, with
  `tests/page.test.tsx` covering the new real Dashboard (replacing
  assertions against the old static placeholder page it superseded).
- Backend coverage in control-plane: `tests/test_dashboard.py` (10 tests)
  and `tests/test_services.py` (20 tests), covering shape, zero-filled
  activity windows, tenant scoping in both legacy and secure mode, the
  real-assertion regression, the full role matrix (BLOCKER 2), and
  pagination (BLOCKER 4) — see §15.
- `npx tsc --noEmit`, `npm run lint`, and `npm run build` all clean.
- A real, uncached `docker build` of `services/web-console/Dockerfile` was
  run and its compiled CSS inspected directly inside the image.
- The full real Playwright acceptance suite
  (`e2e/phase9-workflow.spec.ts`) was re-run against the redesigned UI
  end-to-end: real alert firing, real incident, real session, real
  investigation, real human approval, real tool-gateway execution, real
  recovery, real resolution via Alertmanager's own webhook.
- `scripts/verify-phase14-multitenant-security.sh` (34 checks) and
  `scripts/verify-retrieval-tenant-isolation.sh` (17 checks) were both
  re-run for real against the redesigned stack — not assumed unaffected
  merely because they predate this round — and both pass in full (see
  §5's fourth bug writeup for the one harness-level fix this required).
- A disposable fresh-checkout validation (per the Phase 14 lesson that a
  developer's already-initialized `.env`/volumes/credentials can hide a
  real bug): an isolated `rsync` copy of the repository, a separate
  Compose project and ports, `make db-migrate` from a brand-new empty
  database through V12, a real sign-up, a real email verification, a
  real organization creation, a real service registration through the
  BFF route, and the real dashboard/services pages rendering the correct
  honest empty state and then the newly registered service — all against
  containers built fresh from this round's code, never the developer
  machine's pre-existing stack. Torn down afterward (`docker compose down
  -v` plus image removal); the developer's own long-running stack was
  verified unaffected (same incident/service row counts, all containers
  healthy) throughout.

## 11. Screenshot locations

Captured with a small Playwright script (`services/web-console/
e2e/capture-screenshots.ts`, reusing the real `createRealLegacyOrgActor`
fixture — never a mocked session) against the live local stack, saved
under `services/web-console/e2e/screenshots-output/` (gitignored, DEMO /
SAMPLE data from this repository's own long-running local development
stack — never fabricated mockups):

- `01-dashboard-desktop.png`, `02-dashboard-mobile.png`, `10-dashboard-dark.png`
- `03-incidents-list.png`, `04-incident-detail.png`
- `05-agent-run-dark.png` (AI investigation workspace)
- `06-system-health.png`, `06b-integrations.png`
- `07-organizations.png`, `07b-services.png`
- `08-sign-in.png`, `09-register.png`

## 12. Known incomplete capabilities

- **AI Investigations is not a separate top-level nav item.** No backend
  capability exists to list all agent runs (neither a cross-incident nor
  an organization-scoped index) — only `GET`/`POST` on a single run by id.
  Adding a real, efficient reverse index was judged out of scope for this
  round; investigations remain reachable from the incident that triggered
  them and from pending-approval links on the dashboard, never from a
  fabricated list page.
- **Tenant-scoped, self-service integration onboarding is not
  implemented** for OpenTelemetry, Kubernetes, or AWS — see §8.
- **No service health/telemetry correlation** — see §7.
- **No update/delete on registered services** this phase — list and create
  only.
- **"Incidents being investigated" is a real incident-status count, not an
  active-AI-run count.** control-plane has no bounded, tenant-scoped
  "active LangGraph AgentRun" aggregate to report honestly yet; the metric
  is labeled for exactly what it measures (independent-review correction
  round, BLOCKER 3 bug A).
- **The "needs attention" / "recent activity" dashboard lists remain
  bounded** (8 items each) with no "view full history" link — no genuine
  supporting page exists yet for either; adding one was judged out of
  scope for this round.
- Real secure-mode invitation email delivery remains unimplemented
  (unchanged from Phase 14) — invitations still surface their real
  verification link via server logs in local development only.

## 13. How to launch locally

Unchanged from prior phases:

```bash
make db-up        # fresh/idempotent bootstrap, including the new V12 migration
make verify-web-console   # the real Playwright acceptance suite
```

Then sign in (or register) at `http://127.0.0.1:3101/sign-in`, select or
create an organization, and the dashboard, incidents, services, and
integrations pages are immediately usable.

## 14. The truthful user journey

Sign in → select organization → dashboard shows real observed incidents
(if any) and a real, honest empty state otherwise → open an incident →
start a real AI investigation → review evidence and hypotheses → approve
an authorized remediation as a real, verified human → watch real recovery
verification and the real, durable audit trail. General customer-specific
service onboarding (connect your own OpenTelemetry/Kubernetes/AWS source)
is **not** claimed to work end-to-end this phase — see §8 and §12.

## 15. Independent review correction round

An independent reviewer approved Phase 15's visual design as a foundation
and raised six blockers plus two polish gates against the implementation.
All were fixed in one consolidated round, without redesigning the
approved UI. Nothing in this round weakened any Phase 14 security
property; the full tenant-isolation acceptance (`verify-phase14-
multitenant-security.sh`, 34 checks; `verify-retrieval-tenant-isolation.sh`,
17 checks) was re-run for real against the live stack and passes in full
after every change below.

**BLOCKER 1 — dashboard tenant authorization.** `GET /api/v1/dashboard/
summary` depended on the nullable `get_actor_context`, which returns
`None` unconditionally whenever `CONTROL_PLANE_REQUIRE_ORGANIZATION_
CONTEXT` is disabled (this platform's own real local-development
default) — meaning the dashboard ran unscoped queries even with a real
browser session, in that default configuration. Fixed by switching to
`require_actor_context` (the same unconditional, independently-verifying
dependency `/api/v1/services` already used), making every dashboard query
always scoped to the verified actor's real organization. New real-request
tests in `tests/test_dashboard.py` cover: missing assertion → 401,
invalid assertion → 401, Org A sees only Org A's counts, Org B sees only
Org B's counts, disabling organization-context enforcement does not
bypass the requirement, and a genuinely valid, correctly-signed
local-development assertion still succeeds.

**BLOCKER 2 — service registration RBAC.** `POST /api/v1/services`
accepted any authenticated role, including `VIEWER` — a real
organization mutation with no role gate. Fixed with a new
`core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES = {OWNER, ADMIN,
ENGINEER}` and a reusable `require_role()` helper, enforced in
control-plane (never merely hidden in the UI) and returning a real 403.
`VIEWER` is excluded as a genuinely read-only role; `INCIDENT_APPROVER`
is deliberately excluded too — that role's entire purpose is deciding
remediation proposals, not general catalog administration, and granting
it here would have been undocumented scope creep. The BFF
(`lib/server/service-client.ts`) translates the real 403 into a
`"forbidden"` `BackendResult`, which `app/api/services/route.ts` already
mapped to a real HTTP 403 via the existing `backendErrorResponse` table.
`RegisterServiceDialog` now accepts a `canRegister` prop (computed
server-side from the real actor's role in `app/services/page.tsx`) and
renders a disabled button with an accessible tooltip explanation for a
role that may not register — a UI convenience only; control-plane's own
check is the real, unbypassable boundary. `tests/test_services.py` now
parametrizes every one of the five real roles against both outcomes,
plus cross-tenant-isolation-under-denial and list-still-works-for-VIEWER
checks.

**BLOCKER 3 — truthful dashboard statistics (three bugs).**
- *Bug A*: "Investigations in progress" was `counts.investigating` — a
  real incident **status** count, not a count of active LangGraph
  AgentRuns (control-plane has no bounded, tenant-scoped aggregate for
  the latter). Relabeled to "Incidents being investigated" rather than
  building a new, unvalidated aggregate under time pressure.
- *Bug B*: "Pending approvals" used `pending_approvals.length`, but the
  backing list is bounded to 8 for the "needs attention" section's
  display purposes — silently wrong above 8. Fixed with a new real SQL
  `COUNT` (`DashboardRepository.get_pending_approvals_count`), returned
  as a new, separate `pending_approvals_count` field the frontend now
  reads for the metric card; the bounded list is unchanged and still
  used only for the attention section itself. Tested with a case where
  the real count (12) and the bounded list (8) deliberately differ.
- *Bug C*: "All clear" was shown whenever there were zero active
  incidents — but the absence of a recorded incident is not proof of
  production health when no customer telemetry is connected. Reworded to
  "No active incidents recorded," which states only what the data
  actually supports.

**BLOCKER 4 — service registry pagination.** `list_services` fetched
every row in an organization unbounded, and the dashboard called it just
to read `.total`. Fixed with real server-side pagination end to end:
`ServiceRepository.list_services` now takes `limit`/`offset`, runs a
separate `COUNT` over the same filtered base query (never `len()` of the
page), and orders deterministically (`created_at DESC, id DESC`,
mirroring `incident_repository.py`'s own established pattern).
`GET /api/v1/services` validates `limit` (1–100, default 20) and
`offset` (≥0, default 0) exactly like `/api/v1/incidents`. The dashboard
now calls `listServices(actorToken, { limit: 1, offset: 0 })` — at most
one row is ever fetched merely to read the real, independently-computed
`total`. The Services page gained a real pagination control (mirroring
`app/incidents/page.tsx`'s own). `tests/test_services.py` proves: a real
total and stable, non-overlapping pages across 25 services split into
three pages of 10/10/5; two organizations registering the identical
service name without collision; and no cross-tenant row ever appearing
in another organization's page.

**BLOCKER 5 — mobile responsiveness (root-caused, not patched over).**
The dashboard rendered at 669px actual width inside a 375px viewport.
Root causes, found by directly querying `document.documentElement.
scrollWidth` and walking the DOM for the exact offending elements in a
real headless browser (never guessed from reading the CSS alone):
1. `components/dashboard/attention-section.tsx` rendered each
   approval/incident timestamp as a `shrink-0` flex item — `flex-shrink:
   0` forces a flex item to keep its full single-line width regardless of
   available space, which is what actually drove the overflow. Fixed by
   letting the timestamp wrap onto its own line below the title on narrow
   viewports (`flex-wrap` + `basis-full`) and only pinning it inline from
   the `sm:` breakpoint up.
2. Three `grid`/`dl` containers (`app/page.tsx`'s two dashboard rows,
   four `dl className="grid grid-cols-[10rem_1fr] …"` detail panels
   across `app/incidents/[incidentId]/page.tsx`, `app/agent-runs/
   [runId]/page.tsx`, `components/RemediationStateCard.tsx`, and
   `components/AgentRunSummary.tsx`, and five plain `grid gap-N` list
   containers in `EvidenceList.tsx`/`CheckpointTimeline.tsx`/
   `InvestigationReportView.tsx`/`RecoveryVerificationCard.tsx`/
   `RetrievalContextView.tsx`) had no explicit `grid-cols-1` (or used a
   bare `1fr` track) below their responsive breakpoint. Without Tailwind's
   own `minmax(0, 1fr)` track sizing, a CSS Grid item's default
   `min-width: auto` lets it grow to its content's min-content width —
   an unbreakable long value (a UUID, a long retrieval source filename)
   silently forced the whole grid, and therefore the page, wider than the
   viewport. Fixed by making every one of these tracks explicit
   (`grid-cols-1`, or `grid-cols-[10rem_minmax(0,1fr)]` with a narrower
   `8rem` label column below `sm:`), plus `break-words`/`break-all` on
   the long-value cells as defense in depth.
   Verified with a real Playwright script measuring
   `document.documentElement.scrollWidth <= window.innerWidth` across the
   dashboard, incidents, incident detail, services, integrations,
   organizations, system, and agent-run pages at 375px, 768px, and
   1440px — all pass (24/24 checks, zero overflow) after the fix. A new
   `02-dashboard-mobile.png` was captured at the real 375px viewport.

**BLOCKER 6 — the AI investigation screenshot showed a real error, not
the workspace.** `05-agent-run-dark.png` previously showed "Received an
unexpected response from the backend." Investigated by directly querying
`GET /api/v1/agent-runs/{id}` against the live agent-runtime-service for
a confirmed-real, same-organization (legacy org) run produced by this
repository's own Phase 9 Playwright acceptance test earlier this round
(`c4cc7ee1-efc6-419c-97c9-ba3293c98187`, status `completed`, a real
`investigation_report`/`remediation_proposal_id`/`recovery_verification`
all present) — that direct call returned a clean HTTP 200. The frontend
and backend were independently proven correct against a real, valid run;
the exact mechanism that produced the earlier broken screenshot predates
this round's own capture logic (the script had no agent-run capture
logic in it at all beforehand) and could not be reproduced, so it is not
attributed to any specific regression. `e2e/capture-screenshots.ts` was
extended to validate the known run id's real HTTP status before
capturing it, and to capture both dashboards and the agent-run workspace
in a real dark-theme browser context (`newContext({ colorScheme: "dark"
})`, which drives `components/theme/theme-script.tsx`'s own real
OS-preference detection — never a hand-set DOM attribute). The new
`05-agent-run-dark.png` shows the complete, real workspace: workflow
progress, checkpoint history, live incident state, the durable incident
snapshot, the full investigation report (observed facts, hypotheses with
confidence, evidence, retrieval context), remediation, and recovery
verification. No real paid LLM call was made — this run's investigation
was produced by investigator-service's own deterministic stub provider,
the same mechanism `e2e/phase9-workflow.spec.ts` always uses.

**GATE 7 — visual polish.**
- The dashboard's "recent activity" card now shows at most 8 items
  (`DashboardRepository.list_recent_events(..., limit=8)`, reduced from
  20 at the query level) rather than a much longer list with no
  supporting "view full history" page to link to — no fake navigation
  was added.
- Kubernetes/AWS integration status changed from `not_yet_supported` to a
  new, distinct `operator_only` status ("Operator-managed only") — the
  blocker text already explained a real, operator-level read-only
  observer exists for both; the badge alone previously risked implying
  the capability was wholly absent. No integration is shown as
  `connected` unless it genuinely is; none are, for a newly registered
  organization.
- The mobile sidebar sheet (`components/shell/app-shell.tsx`) gained the
  real `OrgSwitcher` component above its nav — previously the desktop
  header's switcher was `hidden lg:block` with no mobile equivalent at
  all, making organization switching completely unreachable on a mobile
  viewport.

**GATE 8 — regression (real, not assumed).** Re-run after every fix
above, against the live stack (never only unit tests): full control-plane
pytest suite (397 passed, 23 skipped, 0 failed — includes the new/updated
role-matrix, pagination, and dashboard-authorization tests); full
web-console Vitest suite (226 passed) in an isolated, freshly-`npm ci`'d
Node 24 container (never the host's own Node 20 or a bind-mounted,
wrong-platform `node_modules` — the same lesson this round's own
`verify-phase14-multitenant-security.sh` fix already established);
`tsc --noEmit` and `eslint .` both clean; a real, uncached production
Docker build of `services/web-console/Dockerfile`; `verify-phase14-
multitenant-security.sh` (34/34) and `verify-retrieval-tenant-isolation.sh`
(17/17) against real PostgreSQL with secure mode enabled; the full real
Playwright `phase9-workflow.spec.ts` browser workflow (1 passed, 8.2m);
and six targeted, real-HTTP checks directly against the live
control-plane + real PostgreSQL proving BLOCKER 1/2/4's exact behavior
(401 without an assertion on both new endpoints, 403 for `VIEWER`
registering a service, 201 for `OWNER`, a real bounded `total` from
`limit=1`, and the dashboard's real `pending_approvals_count`/
`investigating` fields) — the one test row this created was deleted
afterward. The developer's long-running local stack's `POSTGRES_PORT`
was temporarily remapped to work around this machine's own native
PostgreSQL-on-5432 collision (unrelated to this project, documented in
earlier Phase 14/15 rounds) and reverted to 5432 afterward; incident/
service row counts and all 18 containers were confirmed healthy and
unaffected throughout.

## 16. Final authentication smoke test — the registration spinner bug

A user reported that submitting `/register` sometimes left the "Create
account" button spinning indefinitely, with no error and no outcome.

**Reproduction.** A first attempt via `http://127.0.0.1:3101/register`
in a real headless browser completed cleanly (`POST /api/auth/sign-up/
email` → 200, redirect to `/organizations`) — this did NOT reproduce the
bug. The precise trigger was found by matching the user's own report
exactly: they reached the app via `http://localhost:3101`, not
`127.0.0.1`. Reproducing against `http://localhost:3101/register`
immediately hung the button, with the real browser console showing:

```
Access to fetch at 'http://127.0.0.1:3101/api/auth/sign-up/email' from
origin 'http://localhost:3101' has been blocked by CORS policy: ...
Failed to fetch
```

**Root cause (two parts, both real bugs).**
1. `lib/auth/client.ts` hardcoded `baseURL:
   "http://127.0.0.1:3101"` — a value baked into the client JS bundle at
   build time. A browser's same-origin policy treats `localhost` and
   `127.0.0.1` as DIFFERENT origins even on the same machine, so any
   user reaching the app via `localhost` had every `authClient` call
   (sign-up, sign-in) become cross-origin, and the server had no
   matching CORS allowlist entry for it — the browser blocked the
   response outright.
2. `components/auth/RegisterForm.tsx` (and, identically,
   `SignInForm.tsx`) called `await authClient.signUp.email(...)` with
   no `try`/`catch`. A normal rejected sign-up (bad password, duplicate
   email) RESOLVES with `{ error }` and was already handled — but the
   CORS failure above makes the underlying `fetch()` THROW instead. The
   uncaught exception propagated out of `handleSubmit`, so
   `setPending(false)` was never reached: the button stayed disabled
   and spinning forever, with no error shown at all.

**Fix.**
- `lib/auth/client.ts`: `baseURL` no longer hardcoded to a specific
  host. Omitting it lets Better Auth's own client resolve to the
  relative path `/api/auth` (confirmed by reading `better-auth`'s own
  `getClientConfig`/`getBaseURL` source), which the browser always
  resolves against the CURRENT page's own origin — correct regardless
  of which hostname reached the app.  `NEXT_PUBLIC_WEB_CONSOLE_ORIGIN`
  remains available as an explicit override for a deployment that
  genuinely needs one.
- `RegisterForm.tsx`/`SignInForm.tsx`: the `authClient` call is now
  wrapped in `try { ... } catch { setError(...) } finally {
  setPending(false) }` — ANY thrown failure (CORS, network, DNS, a
  future unrelated regression) now always resets the button and shows
  "Could not reach the server. Check your connection and try again."
  instead of hanging. This mirrors the try/catch/finally pattern
  `RegisterServiceDialog.tsx`/`OrgSwitcher` already used elsewhere in
  this console — the two auth forms had simply inherited an older,
  unguarded pattern from before Phase 14.

**What `WEB_CONSOLE_TRUSTED_ORIGIN` still governs.** The relative-URL
fix removes the browser-level CORS failure, but Better Auth's own
*server-side* `trustedOrigins` check (`lib/auth/auth.ts`, an
intentional CSRF boundary, unchanged by this round) still compares the
request's real `Origin` header against its configured allowlist
(`WEB_CONSOLE_TRUSTED_ORIGIN`, `http://127.0.0.1:3101` in this
Compose setup). Re-testing `http://localhost:3101/register` after the
fix now shows a clean, real `403` with the inline message "Invalid
origin" — the button is no longer stuck, and the failure is honest and
actionable, exactly matching what an operator who widens
`WEB_CONSOLE_TRUSTED_ORIGIN` for their own deployment would need to
see. Widening that allowlist itself was judged out of scope for this
fix (a deliberate security boundary, not a bug) and was not changed.

**Full real-browser journey**, verified against the correctly-trusted
`http://127.0.0.1:3101` origin with a disposable test identity (never
logged, never screenshotted): registration (`200`) → the real
verification link from web-console's own server logs (the documented
local-development mechanism, `302`) → sign-in (`200`) → organization
creation (`200`) → dashboard (honest empty state) → services → incidents
→ the AI investigation route. No indefinite spinner at any step. The
disposable user, its organization, and all cascaded rows were deleted
from the database afterward; the developer's own pre-existing users and
data were never touched.

**Regression tests.** New `tests/auth-forms.test.tsx` (6 tests) covers
both forms' success path, their existing resolved-error path, and the
REGRESSION case itself: a rejected/thrown `authClient` call now always
re-enables the button and shows a clear message, for both
`RegisterForm` and `SignInForm`. Full Vitest suite: 232/232 passed.
`tsc --noEmit` and `eslint .` both clean. A real, rebuilt
`services/web-console` Docker image was deployed to the live stack and
the browser journey above was run against it directly (not assumed from
unit tests alone). `scripts/verify-phase14-multitenant-security.sh`
performs its own sign-up calls via direct `curl` against
`/api/auth/sign-up/email`, never through `RegisterForm`/`authClient`,
so it is unaffected by this round's component-level change and was not
re-run; no control-plane file was touched this round.
