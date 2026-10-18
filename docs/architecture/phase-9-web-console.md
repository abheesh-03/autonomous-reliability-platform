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

## 10. Stage 1 scope (this document's current reality)

Stage 1 implements only the foundation: a minimal Next.js App Router
service (`services/web-console`) with a product-identity homepage, a
static navigation shell listing the sections later stages will fill in,
and `GET /api/health` for container healthchecking. It makes no
backend call, holds neither operator token, and has no `depends_on` on
control-plane/agent-runtime-service in `docker-compose.yml` — a
dependency it does not yet need. Later stages will add, in order: the
read-only `/incidents`, `/incidents/[id]`, `/agent-runs/[runId]`, and
`/system` pages against real backend data; then the two BFF mutations
(§7); then polling (§4); then the layered test/acceptance strategy
described in §8.
