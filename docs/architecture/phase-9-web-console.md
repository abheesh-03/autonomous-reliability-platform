# Phase 9: operator web console

## 1. Purpose

Phases 0-8 are a complete, architecturally frozen backend: a real
incident lifecycle, a durable AI investigation, and a durable,
human-approved remediation workflow, all provable from the command line
(`make investigate`, `make remediation-approve`, the `verify-*.sh`
acceptance scripts) but with no human-facing surface. Phase 9 adds
**only** that surface — a web console an operator actually looks at and
clicks through. It does not change what the platform can do. It does
not add a new capability, a new incident/remediation state, a new
LangGraph node, or a new credential class. Every mutation the console
will eventually perform is one the backend already supports and
already enforces independently.

## 2. Server-side BFF architecture

```
Browser
  ↓ same-origin, no backend credentials
Next.js web-console
  ↓ Server Components (read) / Route Handlers + Server Actions (BFF mutations)
  ↓ server-to-server fetch, Docker-internal DNS
control-plane (8000) / agent-runtime-service (8003)
```

The browser never talks to control-plane or agent-runtime-service
directly. It talks only to the Next.js server, same-origin. The
Next.js server is the only thing that ever holds a backend Bearer
token, and the only thing that ever makes a server-to-server call.
This is why no CORS change is needed anywhere in the existing backend:
control-plane and agent-runtime-service have no CORS middleware today
(confirmed by source inspection) and never need one, because no
browser ever calls them cross-origin — same-origin BFF is the
alternative to that change, not a workaround for it.

**Server Components are the default** for every read-only page.
**Client Components are introduced only where browser interactivity or
polling genuinely requires them** (a later-stage approve/reject button,
a later-stage polling boundary) — never by default, never for pages
that only render fetched data.

## 3. Credential boundary

Eventually the web-console server may hold exactly two credentials:

- `CONTROL_PLANE_LIFECYCLE_TOKEN` — to transition an incident's status.
- `CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN` — to approve/reject a
  remediation proposal.

It must **never** hold `CONTROL_PLANE_WEBHOOK_TOKEN`,
`CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN`,
`CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN`, `TOOL_GATEWAY_EXECUTION_TOKEN`,
`PAYMENT_FAULT_INJECTION_TOKEN`, or `PAYMENT_REMEDIATION_TOKEN` — none
of those six has any legitimate purpose for a human-operator UI; each
belongs exclusively to Alertmanager, agent-runtime-service, or
tool-gateway respectively. `agent-runtime-service`'s own HTTP API is
entirely unauthenticated (confirmed by source inspection), so the
console needs **zero** tokens to create/read/resume an agent run — it
only ever needs a token to talk to control-plane.

Neither protected token is ever exposed through `NEXT_PUBLIC_*`
environment variables, passed as a prop into a Client Component,
rendered into HTML, serialized into a browser-delivered JavaScript
bundle, or written to browser storage. They are read only inside
server-only modules (Route Handlers, Server Actions, Server
Components) that never execute in the browser.

**Stage 1 holds neither token.** It makes no backend call at all.

## 4. Update model: polling, not push

Phase 9 uses HTTP polling/refetch exclusively. It does not introduce
WebSockets, Server-Sent Events, Kafka, or any event bus — those remain
out of scope for this phase (they may belong to a future Phase 11).
Polling is throttled to the state actually being watched: frequent
while an agent run is `running` or an incident is mid-lifecycle, slowed
or stopped once a run/incident reaches a terminal state. No runaway
polling.

## 5. The backend remains authoritative

The frontend never implements incident or remediation state machines
as its own authoritative logic. It may disable or hide a control for
UX convenience (e.g. hiding "Start Investigation" on an incident that
is already `investigating`), but every real transition is validated
server-side by control-plane/agent-runtime-service exactly as it is
today for `make investigate`/`make remediation-approve`. A wrong
frontend guess produces a normal `409`, never a corrupted transition.

## 6. No fake frontend state

The console displays backend state; it never synthesizes it. There is
no `setIncidentResolved(true)`-style optimistic transition anywhere in
this design. The real flow is always: decision persisted → durable
agent resumes → tool-gateway executes → recovery independently
verified → monitoring recovers → the real Alertmanager resolved
webhook fires → the incident resolves → the UI observes that resolved
state on its next poll. If a step is slow, the UI shows the real
intermediate state, never a guessed final one.

## 7. Correction 1 (recorded per explicit instruction): durable run-id-before-execution invariant

Phase 7 established a core durability invariant: **the caller must
possess the durable `run_id` before fallible graph execution begins.**
`POST /api/v1/agent-runs` seeds a durable checkpoint only — it makes no
control-plane/investigator-service call and cannot fail mid-graph.
Execution — including the very first execution — only happens on the
separate `POST /api/v1/agent-runs/{run_id}/resume` call.

An earlier audit draft proposed collapsing "transition incident →
create run → immediately resume → redirect" into one combined
client-perceived action. **That sequencing must not be implemented.**
The correct, required sequencing for the future "Start AI
Investigation" workflow is:

```
transition incident status, if required (existing lifecycle endpoint)
  → POST /agent-runs                     (receive the durable run_id)
  → navigate to /agent-runs/{run_id}      (the id now durably exists)
  → only THEN resume (POST .../resume)    (fallible graph execution)
```

The navigation to `/agent-runs/{run_id}` happens with a durable,
already-persisted run_id in hand *before* the fallible resume call is
ever made — so a resume failure (a transient `503`, or any other
mid-execution fault) never strands the operator without a way to find
and retry the same run; the run_id was never contingent on execution
succeeding. This ordering is a Stage-1 design record only — Stage 1
implements no agent-run workflow at all.

## 8. Correction 2 (recorded per explicit instruction): Phase 9 E2E must not misuse the Phase 4 payment-outage script

An earlier audit draft proposed basing the eventual real end-to-end
Phase 9 acceptance test on the complete Phase 4 `payment-outage
--full-acceptance` scenario. **That is wrong and must not be
implemented.** That scenario restores and resolves its own incident as
part of its own acceptance proof — it is not a suitable *active,
pending* approval workflow for a UI test to click through; by the time
such a test could act on it, the incident may already be resolving on
its own.

The eventual full remediation UI scenario must instead be based on the
**Phase 8 controlled payment-authorization fault** architecture (the
same mechanism `scripts/verify-remediation.sh` already uses:
`PAYMENT_FAULT_INJECTION_ENABLED` + `PAYMENT_FAULT_INJECTION_TOKEN`,
producing a real pending remediation proposal a human/UI genuinely
approves or rejects). Phase 8's own backend acceptance is already
expensive; the eventual Phase 9 E2E design must reuse that real
backend path for its one real-stack pass, not re-run the entire Phase
8 fault-injection cost inside every frontend unit/component test. This
is a design record only — Stage 1 adds no E2E test of any kind.

## 9. Phase 0-8 remain frozen

No file under `services/control-plane`, `services/agent-runtime-service`,
`services/investigator-service`, `services/retrieval-service`,
`services/tool-gateway`, `services/payment-service`,
`services/inventory-service`, `services/notification-service`,
`services/checkout-service`, `database/migrations`, or `observability`
changes for Phase 9. No existing token, incident state, remediation
state, LangGraph node, Prometheus rule, or Alertmanager timing changes.
No authentication/login system or RBAC redesign is introduced — the
console borrows the same two Bearer tokens an operator already uses
from the command line today.

## 10. Stage 1/2/3/4 scope (this document's current reality)

**Stage 1** implemented the foundation: a minimal Next.js App Router
service (`services/web-console`) with a product-identity homepage and
`GET /api/health` for container healthchecking. No backend call, no
operator token, no `depends_on`.

**Stage 2** adds the read-only real-data layer, still with no operator
token and still no `depends_on` (the `/system` page exists specifically
to show a backend as unavailable, so this container must stay
independently startable even during a real backend outage — see the
`web-console` service's own comment in `docker-compose.yml`):

- `lib/server/http.ts` — a shared, server-only bounded-fetch primitive
  (5s default timeout, never throws), a narrow `BackendErrorKind`
  (`not_found` | `validation` | `unavailable` | `malformed`) every
  page renders a tailored failure state for, and a bounded
  `fetchAllPages` helper (API max page size, a hard page-count safety
  cap, and immediate termination on an empty page) used to fetch an
  incident's/proposal's COMPLETE durable history rather than only its
  first default-sized page.
- `lib/server/control-plane-client.ts` — the only thing that ever
  calls control-plane, using its real, unauthenticated GET contracts
  exactly as documented in `docs/api/control-plane.md`: incident
  list/detail, incident events, remediation proposal list/detail, and
  remediation proposal events. No write call exists yet.
- `lib/server/health-client.ts` — independent `/health/live` +
  `/health/ready` checks per service, run in parallel across
  control-plane, agent-runtime-service, investigator-service, and
  retrieval-service for `/system`; one service's failure never hides
  another's real result.
- `/incidents` (real, backend-driven pagination/filtering),
  `/incidents/[incidentId]` (real metadata, complete audit timeline,
  read-only remediation proposal + event history — no approve/reject
  control exists yet), `/system` (real four-service health fan-out).

**Stage 3** adds the read-only durable AgentRun / LangGraph
investigation view, still zero-credential, still no `depends_on`:

- `lib/types/agent-run.ts` — re-audited directly against
  `agent_runtime_service/domain/{agent_run,investigation,incident_snapshot}.py`
  for this stage (never the prior audit notes alone). Two real
  discrepancies recorded there: `execution_result` and
  `recovery_verification` are plain `dict | None` on the backend's own
  Pydantic model, not structured sub-models — their real shapes
  (`{status, detail}` and `{proposal_succeeded, fault_inactive,
  target_healthy}`) are fixed only by `graph/nodes.py`'s own code, not
  by the schema; and `remediation_status` is plain `str | None`, not a
  backend-enforced `Literal`, unlike `status`. This console still
  validates both against the real, observed vocabulary and fails
  closed on anything else.
- `lib/server/agent-run-validation.ts` + `lib/server/agent-runtime-client.ts`
  — `getAgentRun`/`getAgentRunHistory`, reusing Stage 2's
  `BackendResult`/`BackendErrorKind`/`getJson` rather than a parallel
  error framework; a hand-written (no new schema-validation
  dependency) structural validator covers the full nested
  investigation-report/evidence/retrieval-context shape, failing
  "malformed" on any mismatch rather than casting arbitrary JSON.
- `control-plane-client.ts` gained `getRemediationProposal(proposalId)`
  — a real, existing, unauthenticated GET control-plane already
  exposed but Stage 2 had no caller for; used only to enrich an
  AgentRun's own `remediation_proposal_id` with the proposal's real
  fields, never a new discovery API.
- `/agent-runs/[runId]` — run identity/state, workflow progress
  (completed/current nodes), chronological checkpoint history, incident
  snapshot (linked to the live `/incidents/[id]`, never re-fetched to
  replace it), the real investigation report (evidence, hypotheses,
  retrieval context — rendered directly from the durable report, never
  by calling retrieval-service), remediation state, execution result,
  and recovery verification — all read-only, all scoped-failure (a
  failed history or proposal-enrichment fetch never hides the
  already-loaded AgentRun). `waiting_for_approval` renders as a plain
  read-only wait state with no approve/reject/resume control anywhere
  on the page. There is no list-all-runs endpoint and Stage 3 adds
  none; the page is reached by a known durable `run_id`, including a
  new read-only "View agent run" link from each remediation proposal
  on `/incidents/[incidentId]` to `/agent-runs/{proposal.agent_run_id}`.

**Stage 4** introduces the console's first mutation boundary: **Start
AI Investigation**. This is where `CONTROL_PLANE_LIFECYCLE_TOKEN`
enters web-console's server for the first time — the SAME Phase 3D
secret control-plane already held, reused via the existing
`scripts/init-webhook-secret.sh` generation path, never duplicated
into a second variable. The browser never receives it: it is read only
inside `lib/server/control-plane-client.ts`'s `transitionIncidentStatus`,
which fails CLOSED (returns a `"configuration"` `BackendErrorKind`,
no network request attempted at all) if the token is unset or
blank-only, rather than ever sending an unauthenticated request and
hoping for a useful response.

**Exact start workflow** (`POST /api/incidents/[incidentId]/investigations`,
a Route Handler — deliberately not a Server Action, so the mutation
boundary is one explicit, resource-oriented same-origin endpoint):

```
BFF reads the current incident (GET, unauthenticated)
  → status open/acknowledged: PATCH status (expected=current, target=investigating)
  → status investigating:     skip the PATCH entirely
  → status remediating/resolved/closed: safe 409, no PATCH, no run created
  → POST /api/v1/agent-runs {incident_id}   (seeds a durable checkpoint ONLY)
  → respond { run_id, incident_id }
```

**The durable run-id-before-execution invariant (Phase 7's core
guarantee) is preserved by construction**: this Route Handler NEVER
calls `POST /api/v1/agent-runs/{run_id}/resume`, and the browser's
`StartInvestigationControl` (the one Client Component in this stage)
never calls it either, on mount or otherwise. A freshly created run is
expected to render `status="running"`, `current_node="start"`,
`completed_nodes=[]` on `/agent-runs/{run_id}` — genuinely unexecuted.
Execution/resume is an explicit later stage's own boundary.

**Partial-success semantics, by design, not by accident**: the
lifecycle transition and agent-run creation are two separate durable
systems, never one distributed transaction. If the PATCH succeeds but
`createAgentRun` then fails, this handler does **not** attempt to roll
the incident back to its prior status — that would invent a
cross-service transaction this platform does not have, and might
conflict with real state that changed again in the meantime. The
incident genuinely *is* `investigating` at that point; a safe retry of
the same request naturally skips the PATCH (per the algorithm above)
and only re-attempts `createAgentRun`.

**No automatic retry of `createAgentRun`, documented as a real
limitation, not silently worked around**: `POST /api/v1/agent-runs` has
no known idempotency key. One browser request therefore makes **at
most one** `createAgentRun` call; an ambiguous/network failure returns
a safe `"unavailable"`/`"malformed"` result rather than retrying,
because a blind retry without an idempotency key could create a
second durable run for the same incident. This is a real, open
limitation of the current backend contract — Stage 4 does not modify
agent-runtime-service to add one.

**The `investigating`-status duplicate-run limitation is also real and
undocumented-away**: there is no list-agent-runs-by-incident endpoint
(Stage 3/4 both deliberately add none), so this console cannot prove
whether an `investigating` incident already has a run in flight unless
a remediation proposal happens to expose one. Allowing "Create
investigation run" from `investigating` is a deliberate, named
trade-off for partial-success recovery — `StartInvestigationControl`
labels this variant distinctly and shows explicit helper text that a
duplicate run is possible; it never claims "no run exists."

Reused rather than extended: `BackendErrorKind` gained `conflict`
(a real 409 — stale `expected_status` or an illegal transition, never
a server outage), `unauthorized` (control-plane rejected THIS
server's own token — never caused by anything the browser did), and
`configuration` (the token is unset locally). All of Stage 1-3's
existing read paths and their four original kinds are unchanged.

## 11. The completion pass: resume/execute boundary (Gate B)

The second mutation boundary executes an **already-durable** AgentRun:
`POST /api/agent-runs/[runId]/resume`, a Route Handler that calls
agent-runtime-service's real `POST /api/v1/agent-runs/{run_id}/resume`
exactly once per browser request. This is, by design, a **separate
HTTP request from Stage 4's start-investigation route** — the browser
must already hold a durable `run_id` (received from a prior, separate
request) before this route is ever called; the start route never calls
resume, and this route never creates a run. The real backend contract
binds no request body at all (confirmed by source inspection of
`agent_runtime_service/api/agent_runs.py`); an empty `{}` is still sent,
matching `scripts/verify-agent-runtime.sh`'s own proven convention.

A resume call can run several real LangGraph nodes synchronously before
returning (investigation, evaluation, proposal creation, or — after
approval — tool-gateway execution and recovery verification), so this
call uses a dedicated 60-second timeout (`RESUME_TIMEOUT_MS`), re-
audited against the same script's own `--max-time 60` convention for
resume versus `--max-time 15` for a plain GET.

**No automatic retry, for the same reason as `createAgentRun`**: the
resume endpoint has no idempotency key, so a timeout, network error, or
malformed response makes **at most one** resume call per browser
request and returns a safe `"unavailable"`/`"malformed"` result rather
than retrying blindly — a blind retry could race or duplicate a still-
in-flight execution. The browser's `AgentRunActions` Client Component
reconciles by calling `router.refresh()` on *any* outcome (success,
safe failure, or network exception), which re-runs the owning Server
Component's own read against the real durable state, rather than
retrying the mutation itself.

The route pre-checks `resumable` and, when `waiting_for_approval`, pre-
fetches the real proposal and refuses (safe `409`-equivalent `conflict`)
if it is still `pending_approval` — an optimization that avoids an
avoidable round trip for an outcome already known locally; the
backend's own `409` remains the authoritative safety net regardless,
never weakened or relied upon as the *only* check.

The button itself (`AgentRunActions`) is gated out of the UI entirely
while `status === "waiting_for_approval"` — that state has its own
dedicated controls (§12), never a generic "Resume run" label that would
be misleading mid-interrupt.

## 12. The completion pass: human decision boundary (Gate C)

The third and final mutation boundary records a human/operator decision
on an already-durable remediation proposal:
`POST /api/remediation-proposals/[proposalId]/decision`. This is where
`CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN` enters web-console's server
for the first time — the SAME Phase 8 secret control-plane already
held, reused via the existing `scripts/init-remediation-secrets.sh`
generation path, never duplicated into a second variable. The real
backend endpoint is a **POST**, not a PATCH, despite being a state
transition (`api/remediation.py`'s `@router.post`) — `decideRemediationProposal`
uses `postJson` accordingly. The browser never receives the approver
token: it is read only inside `control-plane-client.ts`, which fails
CLOSED (`"configuration"`, no request attempted) if the token is unset
or blank, identical to the lifecycle token's own convention.

**The browser sends only `{decision, comment?}` — never an
`expected_status`.** The BFF derives `expected_status` itself from a
fresh `GET` of the real, current, durable proposal immediately before
deciding, so a stale browser-held status value can never be used as the
optimistic-concurrency guard the backend's own `decide()` method
enforces; a value smuggled into the request body is simply ignored.

**This route must not call resume, and never does.** Approving or
rejecting a proposal is a real, independently meaningful write (on
approve, the backend atomically transitions the owning incident
`investigating → remediating` in the same DB transaction; on reject, it
touches only the proposal row, never the incident — both enforced by
control-plane itself, never re-implemented here) — but it must never
itself execute anything. Continuing the workflow past the interrupt is
a **separate, explicit** operator action.

The UI (`RemediationDecisionControl`) reflects this split exactly:

- While the real proposal is `pending_approval`: Approve / Reject
  buttons (with an optional, 1000-character-bounded comment), shown
  only inside the existing `waiting_for_approval` banner.
- Once decided (`approved` or `rejected`) but the AgentRun has not yet
  been resumed past its interrupt: a distinctly-labeled **"Continue
  workflow"** button — calling the *same* Gate B resume route, but
  never automatically, and never from the decision route itself.
- Otherwise: nothing — the run has already moved past this interrupt.

No automatic retry here either, and the same `router.refresh()`-on-any-
outcome reconciliation convention as Gate B.

## 13. The completion pass: bounded live polling and live-vs-durable incident state (Gate D)

`/agent-runs/[runId]` now polls, bounded and read-only, via a single
Client Component (`LiveRunPolling`) that calls `router.refresh()` on a
plain `setInterval` — no WebSockets, SSE, or client-state library. It
never calls `fetch` itself; every tick is a re-render of the owning
Server Component's own GETs. Exactly one timer exists at a time,
always cleared on unmount or when the polling cadence itself changes.
Cadence is derived purely from state, never from time elapsed:

- `running` → ~2.5s (a human is actively watching progress).
- `waiting_for_approval` → ~5s (waiting on a human decision, or on
  tool-gateway/recovery verification after a resume).
- `completed` / `failed` **and** the incident is still `remediating` →
  ~5s (waiting for Alertmanager's own natural resolution).
- `completed` / `failed` and the incident is anything else (including
  when the live incident fetch itself failed) → no polling at all.

The page also renders a **"Live incident state"** section, fetched via
a fresh, independent `getIncident(agentRun.incident_id)` call — deliberately
separate from the AgentRun's own durable `incident_snapshot`, which is
frozen at whatever point the graph last captured it. A failure in this
fetch is scoped (`BackendFailure` inside that one section only) and
never hides the rest of the page. The two sections are visually and
textually distinct (`"Live incident state"` vs. `"Incident snapshot
(durable, as captured during this run)"`) specifically so an operator
never confuses a stale embedded snapshot with the real current state.

## 14. Monitoring remains authoritative (absolute, re-affirmed)

No code anywhere in this console transitions `remediating → resolved`,
PATCHes the lifecycle to `resolved` after recovery verification, or
infers resolution from `execution_result.status`,
`recovery_verification.*`, or tool-gateway's own success. **Only a real
control-plane `GET /api/v1/incidents/{id}` reporting `status: "resolved"`
may ever say so** — and Gate F's own acceptance test explicitly proves
the console shows the real intermediate truth (`remediating`, not yet
`resolved`) immediately after a verified-successful remediation, and
only shows `resolved` once Alertmanager's own real resolved webhook has
independently caused it.

## 15. Partial-success / no-rollback semantics (the complete set)

Preserved at every mutation boundary, by design, never accidentally:

- **Start**: lifecycle PATCH succeeds, `createAgentRun` fails → no
  rollback PATCH is attempted (§10 above).
- **Resume**: an ambiguous response (timeout/network/malformed) → no
  automatic retry; the caller reconciles via a fresh read, and may
  explicitly retry only after seeing the real current state.
- **Decision**: approval succeeds, a later resume fails → the approval
  stays `approved`; there is no rollback to `pending_approval`. Reject
  never touches the incident, by the backend's own construction.
- **Remediation**: whatever failure behavior Phase 8's tool-gateway/
  control-plane already implement (e.g. a failed execution rolling the
  incident `remediating → investigating`) is observed, never
  reimplemented or special-cased by this console.
- **Monitoring**: remediation verified successful but the alert has not
  yet naturally recovered → the incident stays `remediating`, and the
  UI shows exactly that — never a guessed `resolved`.

**No mutation in this console ever retries itself automatically** —
`createAgentRun`, `resumeAgentRun`, and `decideRemediationProposal` each
make **at most one** real backend call per browser request, for the
same reason in all three cases: none of the underlying endpoints has a
request-level idempotency key, so a blind retry could create a
duplicate run, race a still-in-flight execution, or re-apply a decision
against state that has since changed. Reconciliation is always a fresh
read (a `router.refresh()`), never a second write.

## 16. Final security model (the complete set)

Web-console's server may hold **exactly** these two credentials, both
server-only, both reused from an existing secret (never duplicated):
`CONTROL_PLANE_LIFECYCLE_TOKEN` (§10) and
`CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN` (§12). It must never hold
`CONTROL_PLANE_WEBHOOK_TOKEN`, `CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN`,
`CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN`, `TOOL_GATEWAY_EXECUTION_TOKEN`,
`PAYMENT_FAULT_INJECTION_TOKEN`, or `PAYMENT_REMEDIATION_TOKEN` — all
six remain exclusively test-harness/Alertmanager/agent-runtime-service/
tool-gateway credentials, confirmed absent from the web-console
container by direct inspection (Gate E) and confirmed absent from every
browser-shipped static JavaScript bundle and server-rendered HTML
response, by content scan, not merely by code review (Gate E; the two
allowed tokens' env-var *names* legitimately appear in web-console's
server-only Next.js chunks, since that is where `process.env.*` is
read, but never in any `.next/static` file the browser actually
downloads, and never as a literal value anywhere). The browser holds
zero protected credentials under any circumstance — not in
`NEXT_PUBLIC_*`, a Client Component prop, rendered HTML, a BFF JSON
response, a URL/query string, or a log/error message.

## 17. End-to-end acceptance (Gate F)

`services/web-console/e2e/phase9-workflow.spec.ts` (Playwright,
Chromium-only) is the ONE real, mutating, browser-driven acceptance
test, run against the live Compose stack — never a mocked backend.
`services/web-console/e2e/support/backend.ts` creates the test's own
**fresh** incident via the same Phase 8 controlled payment-authorization
fault mechanism `scripts/verify-remediation.sh` already proved
(`PAYMENT_FAULT_INJECTION_TOKEN` to enable, `PAYMENT_REMEDIATION_TOKEN`
to clear/read — test-harness-only credentials, called directly from
the test runner's own process, never routed through web-console or
seen by the browser), captures a freshness checkpoint before inducing
anything, and never inserts into PostgreSQL directly or fabricates an
alert.

The test drives the complete real workflow through actual browser
clicks: open the fresh incident → Start AI Investigation → verify
navigation to the durable `/agent-runs/{run_id}` with the run genuinely
unexecuted → click "Run investigation" → wait for the real
`waiting_for_approval` interrupt → verify the real investigation
report/evidence/RAG context and the real pending proposal → click
Approve → independently verify (via direct control-plane/agent-runtime
reads, not the browser) that the proposal is `approved`, the incident is
`remediating`, and remediation has **not** executed yet → click
"Continue workflow" (a separate click, a separate request) → verify
real tool-gateway execution succeeded and real recovery-verification
fields → verify the incident is still **not** `resolved` immediately
after → wait for `CheckoutServerErrors`' real, un-shortened recovery
window → verify the SAME incident naturally becomes `resolved` via
Alertmanager's own webhook → verify the complete incident and
remediation audit trails. On a failed acceptance run, trusted test-harness cleanup attempts to clear the fault and independently verifies it is inactive. On a successful run, cleanup only independently reads and verifies the fault is already inactive, without issuing a redundant clear. Cleanup never forces incident resolution. Rejection coverage lives in the
focused unit/component/route test suites (`tests/*.test.ts(x)`), not in
a second expensive E2E.

`scripts/verify-web-console.sh` wraps this spec for both local and CI
use: it starts web-console if not already running, forces
investigator-service into the same deterministic stub LLM provider
Phase 5-8 already use (restored and verified afterward, regardless of
where the run fails), forces `PAYMENT_FAULT_INJECTION_ENABLED=true` for
the duration of the run only (also restored and verified afterward),
installs the Chromium browser (idempotent), and runs `npm run e2e`.

## 18. CI integration (Gate G)

`.github/workflows/ci.yml` runs `scripts/verify-web-console.sh` as one
step (`Verify web console (Phase 9)`), placed immediately after the
existing Phase 8 `Verify remediation` step — not because of an ordering
dependency (this test creates its own fresh incident and never reuses
Phase 8's), but because every other backend service this test also
depends on is already confirmed healthy and exercised by that point.
web-console's own Node 24 install/typecheck/lint/unit-test/build steps
remain unchanged and still run early, before the Compose stack even
starts (Stage 1's original placement). The job's overall
`timeout-minutes` was raised from 65 to 90 to accommodate this one
additional real, multi-minute (~8 minutes measured locally) step; no
existing Phase 0-8 coverage was removed, shortened, or weakened.

## 19. A known, documented limitation (not resolved by this pass)

The `investigating`-status duplicate-run limitation recorded in §10
remains real and unresolved: there is still no list-agent-runs-by-
incident endpoint, so this console still cannot prove whether an
`investigating` incident already has a run in flight. This is an
explicit, named trade-off, not an oversight — resolving it would mean
adding a new backend endpoint, which is out of this phase's frozen
scope (§9).

## 20. Origin/CSRF guard (independent-review correction)

All three mutation Route Handlers (`/api/incidents/[incidentId]/investigations`,
`/api/agent-runs/[runId]/resume`, `/api/remediation-proposals/[proposalId]/decision`)
now call a shared guard, `lib/server/origin-guard.ts`'s
`rejectCrossOriginMutation(request)`, as the FIRST statement in each
handler, before any parameter/body parsing or backend call. It
compares the request's real, browser-set `Origin` header against an
**explicitly configured trusted origin** (`WEB_CONSOLE_TRUSTED_ORIGIN`,
defaulting to `http://127.0.0.1:3101` — the exact origin
`docker-compose.yml` publishes this container at, which remains bound
to `127.0.0.1` only, unchanged) — never against the request's own
`Host` or `X-Forwarded-Host` header, both of which an attacker fully
controls and neither of which this guard ever reads. A missing,
empty, or mismatched `Origin` fails closed with a safe, bounded `403
{"error": "forbidden", "message": "This request was rejected."}` —
never a raw header echo, stack trace, or backend detail — and no
backend call is ever attempted. A genuine same-origin click from this
console's own UI is unaffected: a browser's `fetch()` always attaches
its own real `Origin` header on a same-origin POST, and page
JavaScript cannot override or spoof it.

**This is NOT user authentication, and must never be treated as
such.** It is a defense-in-depth CSRF/cross-origin mitigation for a
console that still has no user login/RBAC system (§3, §16) — it
proves a request came from a browser tab that believes it is talking
to this console's own origin, never that the person driving that
browser is an authorized operator. **This console must never be
deployed anywhere an untrusted party can reach it without first adding
real authentication, authorization, and CSRF controls on top of this
guard, not instead of them.** No login/RBAC architecture was
introduced by this fix, by explicit instruction.
