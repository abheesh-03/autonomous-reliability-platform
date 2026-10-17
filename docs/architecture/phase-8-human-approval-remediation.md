# Phase 8: human approval, safe remediation, and recovery verification

## 1. Purpose

Phase 7 gave this platform a durable, read-only orchestration layer:
load an incident, investigate it, assess the investigation, finalize —
never mutating anything. Phase 8 adds this platform's first MUTATING
operational capability: a durable LangGraph run can now *propose* a
remediation action, pause for a REAL human decision, and — only once a
human has genuinely approved it — have exactly one allowlisted,
independently-verified action executed against one downstream
service (payment-service's own controlled demo fault), with the
result durably recorded and the owning incident's lifecycle updated
atomically.

The goal of this phase is not "an agent that can fix things." It is a
**safe architecture for a system that will eventually be trusted to
act** — one where every trust boundary is explicit, every credential is
narrow, and a compromised or simply wrong model output can never, by
itself, cause a real mutation.

## 2. Threat model

The component this platform trusts least is the LLM. Phase 5/6 already
established that its output is evidence-grounded but never assumed
correct; Phase 8 extends that distrust to the one place it now
matters most — action selection. The specific threats this phase
defends against:

- **A hallucinated or manipulated investigation suggesting a dangerous
  action.** Defense: the LLM never selects an executable action at
  all (see §3). `propose_remediation` evaluates a small, fixed,
  deterministic policy over structured fields; it never parses
  hypothesis prose to decide what to do.
- **A compromised or buggy agent-runtime-service trying to execute
  something without real approval.** Defense: `TOOL_GATEWAY_EXECUTION_TOKEN`
  alone never authorizes an action. tool-gateway independently
  re-fetches the proposal from control-plane on every single execute
  call and checks its real, current status (§8, §13).
- **A caller trying to bypass approval through the agent-run API
  itself** (e.g. `POST .../resume {"approved": true}`). Defense: the
  resume endpoint has no decision field at all. The trusted decision
  is fetched from control-plane, never accepted from the caller
  (§7).
- **Privilege creep through a new service.** Defense: tool-gateway has
  no Docker socket, no shell/subprocess execution, no database
  credential, and a hard, compiled-in allowlist of exactly one
  action (§9, §10).
- **A crash duplicating a real-world side effect.** Defense: the one
  allowlisted action is itself idempotent, and every durable
  bookkeeping transition is idempotent too (§11, §12).
- **A failed remediation leaving the incident permanently stuck.**
  Defense: a failed execution atomically rolls the incident back to
  `investigating` (§6, §14).

## 3. Why model output cannot directly execute

Investigator-service's own LLM call (Phase 5/6, unchanged by this
phase) produces observations, hypotheses, and suggested checks — all
of it evidence-grounded, none of it an instruction to actually do
anything. `propose_remediation` (agent-runtime-service) reads the
investigation's STRUCTURED fields only (whether any hypothesis has a
non-empty `supporting_evidence_ids`, Phase 6's own retrieval
`context_id`s) to build the proposal's bounded `supporting_evidence_ids`/
`supporting_context_ids` — it never reads `statement` text to decide
*what* to do. The actual decision of *whether* to propose anything,
and *which* action/target to use, is three fixed boolean checks
against structured fields (§5) plus one independent, real,
non-LLM-derived signal: tool-gateway's own read-only report of whether
the controlled payment fault is currently active. There is exactly one
possible proposal shape (`clear_payment_authorization_fault` /
`payment-service`) the whole platform can ever produce; there is no
code path from "the model said X" to "the system executed X".

## 4. Control-plane remediation domain

Two new tables, owned exclusively by Flyway
(`database/migrations/V6__create_remediation_schema.sql`, additive —
V1–V5 untouched):

```
reliability.remediation_proposals
  id, incident_id, agent_run_id, idempotency_key (UNIQUE),
  action_type, target (both CHECK-constrained to the one allowed pair),
  reason, supporting_evidence_ids[], supporting_context_ids[],
  status, proposed_at, updated_at, decided_at, decision_comment,
  execution_started_at, execution_completed_at

reliability.remediation_events   -- append-only, same trigger pattern
  id, proposal_id, event_type, actor_type, occurred_at, metadata
```

`remediation_events` is append-only the same way `incident_events` is
(V3/V4): `BEFORE UPDATE/DELETE/TRUNCATE` triggers that raise, covering
all three from the very first migration (incident_events needed V4 to
retrofit TRUNCATE; this table never had that gap). Same honest
limitation as always stated for `incident_events`: a real application
guarantee against this service's own normal connection role, never a
tamper-proof claim against a sufficiently privileged table owner.

`repositories/remediation_repository.py` is the single place every
transition is implemented — the same "centralized state machine, never
scattered across routes" discipline `domain/lifecycle.py` already
established for incidents. `api/remediation.py`'s routes are thin:
validation and response shaping only.

## 5. Deterministic action policy

`propose_remediation` (agent-runtime-service) creates a proposal only
if ALL of the following hold:

1. `incident_snapshot.source == "alertmanager"`
2. `incident_snapshot.severity == "critical"`
3. `incident_snapshot.title` exactly matches the `CheckoutServerErrors`
   alert rule's own `annotations.summary` text (a module-level
   constant in `graph/nodes.py`, mirrored from
   `observability/prometheus/rules/alerts.yml`)
4. an investigation report exists in state
5. tool-gateway's own `GET /api/v1/remediation-capabilities` reports
   `precondition_met: true` — the controlled payment-service fault is
   genuinely active right now, independently observed, never assumed

Honest, stated limitation: condition 3 is a title-text coupling to the
alert rule's own annotation, because `reliability.incidents` does not
persist the Alertmanager `alertname` label as its own column. If the
rule's `summary` text ever changes, this constant must change with it.
This is a real, acknowledged gap, not something hidden behind a vaguer
check.

If any condition fails, `propose_remediation` creates nothing and the
run finalizes normally with `remediation_status="not_applicable"` —
exactly the same, unmodified Phase 7 pipeline for every incident this
policy doesn't match.

## 6. Proposal lifecycle

```
pending_approval --(human approves)--> approved --(tool-gateway starts)--> executing
      |                                                                       |
      +--(human rejects)--> rejected                            +-----------+-----------+
                                                                  |                       |
                                                           succeeded (terminal)    failed (terminal)
```

Enforced entirely in `RemediationRepository` via optimistic
compare-and-swap UPDATEs (`WHERE status = :expected`), the same idiom
`IncidentRepository.transition_incident_status` already uses — never a
DB-level trigger graph. Approval is additionally atomic with the
OWNING INCIDENT's own `investigating -> remediating` transition (§7).
A failed execution is additionally atomic with the incident's own
`remediating -> investigating` rollback (§14).

## 7. LangGraph interrupt/resume design

Verified directly against the installed, pinned `langgraph==1.2.15`
source before writing any of this (never assumed from documentation
alone): `interrupt(value)` raises `GraphInterrupt` on its first call
within a node's task, durably pausing the graph (`StateSnapshot.next`
points at that node; `StateSnapshot.interrupts` holds the real pending
`Interrupt(value=..., id=...)`). **The node RE-EXECUTES FROM ITS START
on every resume attempt** — confirmed in source, not assumed — which
is why `await_human_approval` does nothing but read already-set state
fields before calling `interrupt(...)`: no side effect can safely
happen before an interrupt call that might re-run.

Resuming uses `graph.ainvoke(Command(resume=<value>), config=config,
durability="sync")` — the real, current API (not a deprecated
`update_state`-based workaround). `Command(resume=...)` accepts a
single value for the next pending interrupt, which is exactly this
graph's shape (one interrupt site, ever).

**Human decision source of truth** (`api/agent_runs.py::resume_agent_run`):
the resume endpoint has **no decision field in its request body at
all**. When a real pending interrupt exists
(`snapshot.interrupts` is non-empty — never merely checking
`next == ("await_human_approval",)`, a correction-round fix: a node
NAME is not proof of a real pending interrupt), the handler
independently fetches the proposal from control-plane (unauthenticated
GET, same read-only policy every other control-plane GET follows):

- `pending_approval` → `409 approval_pending`, the interrupt is NEVER
  touched
- `approved` → `Command(resume={"decision": "approved", "proposal_id": ...})`,
  built entirely from the TRUSTED control-plane record
- `rejected` → `Command(resume={"decision": "rejected", ...})`
- anything else (an inconsistent state) → `409`, fails safely

The view layer (`AgentRun.status`) reports `"waiting_for_approval"`
only when `StateSnapshot.interrupts` is genuinely non-empty — the same
correction-round fix applied symmetrically on the read side.

## 8. tool-gateway architecture

The ninth backend service, Go, pure standard library (no external
dependencies at all — `go.mod` has none), distroless non-root runtime,
no Docker socket, no shell/`os/exec`. Three packages:

- `internal/allowlist` — the hard, compiled-in allowlist: one constant
  pair, `clear_payment_authorization_fault` / `payment-service`. No
  map keyed by a caller string, no reflection-based dispatch.
- `internal/controlplane` — reads/writes control-plane's remediation
  API only (GET the proposal; POST execution/start and
  execution/result, authenticated with
  `CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN`). Cannot create or
  approve/reject a proposal — those calls don't exist in this package.
- `internal/payment` — calls payment-service's fault-control endpoints
  only, authenticated with `PAYMENT_REMEDIATION_TOKEN`. Has no method
  that could call the ENABLE endpoint.

`POST /api/v1/remediation-actions/execute` accepts **only**
`{"proposal_id": "<uuid>"}` — decoded with `json.Decoder.DisallowUnknownFields()`,
so a caller attempting to also supply a URL, hostname, shell command,
container id, or any other field is REJECTED with 400, never silently
ignored. Every downstream URL (control-plane, payment-service) comes
from trusted, compiled-in configuration, never from a request.

`GET /api/v1/remediation-capabilities` (the read-only
precondition/capability endpoint agent-runtime-service's
`propose_remediation` calls) is guarded by the SAME
`TOOL_GATEWAY_EXECUTION_TOKEN` as execute — a correction-round fix; it
is never public/unauthenticated. This cannot be used to bypass
approval: it reports a precondition only, and execute always
independently re-verifies the real control-plane proposal state
regardless of what this endpoint ever reported.

## 9. Why there is no Docker socket

Mounting `/var/run/docker.sock` into tool-gateway, even behind an
application-level allowlist, would hand the process host-level
capability far broader than "clear one payment fault" — the socket
itself has no concept of an allowlist; anything with access to it can
control every container on the host. Phase 8 establishes the SAFE
architecture now — a tightly-scoped, independently-verified,
application-level recovery action — so that real Docker/Kubernetes
restart/rollback capability can be added LATER behind this SAME
Tool Gateway boundary, once real RBAC/namespacing exists to scope it
the way this phase scopes its one payment-service action. This phase
does not build that generic command runner, and the architecture does
not assume it ever will without equivalent scoping.

## 10. The initial allowlisted action

Exactly one: `clear_payment_authorization_fault` against
`payment-service`. Enforced in four independent places simultaneously
(defense in depth, never relying on any single one):
`internal/allowlist/allowlist.go` (Go, compiled-in constant),
`database/migrations/V6__create_remediation_schema.sql`'s own CHECK
constraints (`action_type =`/`target =` a literal, not an enum
column — a future second action requires a new migration, never a
data change alone), `graph/nodes.py`'s own
`REMEDIATION_ACTION_TYPE`/`REMEDIATION_TARGET` constants
(agent-runtime-service), and `domain/remediation.py`'s closed
`Literal` types (control-plane).

## 11. Fault-injection mechanism

payment-service's controlled authorization fault
(`fault_state.py`) is the simplest mechanism that can produce a real,
demonstrable, recoverable incident: one boolean, held in process
memory, guarded by a plain `threading.Lock` (payment-service's route
handlers are synchronous FastAPI functions — this is the correct
Python primitive here, not an asyncio lock).

- `PAYMENT_FAULT_INJECTION_ENABLED` defaults to `false`. A correctly-held
  injection token alone is not enough to enable the fault; Compose/CI
  must explicitly opt in (`scripts/verify-remediation.sh` does this
  itself, for the duration of its own run only, restored afterward).
- `POST /internal/v1/faults/authorization/enable` — test/operator-only,
  `PAYMENT_FAULT_INJECTION_TOKEN`.
- `POST /internal/v1/faults/authorization/clear` — the ONE endpoint
  tool-gateway may call, `PAYMENT_REMEDIATION_TOKEN`, idempotent
  (`{"active": false, "changed": bool}`).
- `GET /internal/v1/faults/authorization` — read-only, authenticated
  with the SAME remediation token as clear (never the injection
  token) — this is what lets tool-gateway independently verify the
  fault is gone using only the one credential it holds.

When active, `POST /payments/authorize` returns a fixed HTTP 502 —
confirmed directly against checkout-service's own `PaymentClient`
source: its `RestClient.retrieve()` throws for ANY non-2xx, caught and
reported as the EXISTING, real `downstream_failure` contract
(`{"error": "downstream_failure", "service": "payment-service", ...}`)
— never a fabricated error path invented for this phase. Honest,
stated limitation: this state is process-local, single-process demo
state; it is never persisted to PostgreSQL and resets on any
payment-service process restart.

## 12. Idempotency semantics

**Proposal creation** (`POST /internal/v1/remediation-proposals`):
`idempotency_key` is mandatory, derived deterministically as
`"phase8-proposal:<run_id>"` — never random. Backed by a real
`UNIQUE` constraint (`ON CONFLICT DO NOTHING ... RETURNING`, then a
field-by-field comparison on conflict): the same key + the same
semantic request returns the existing row; the same key + a
conflicting request is `409`.

**Approval** (`POST .../decision`): the same `(decision, comment)`
replayed against an already-decided proposal returns the existing row
unchanged, no duplicate event. A replay with a DIFFERENT comment is
`409` — the original human decision/comment is never silently
overwritten. Correction round (finding #4): an approval's own lineage
does not stop at `approved` — it legitimately continues through
`executing`, `succeeded`, and `failed` as execution progresses, and the
decision has already been durably applied in every one of those
statuses. A replay of the SAME approve decision arriving AFTER
execution has begun is still an idempotent, read-only replay of the
CURRENT row (never a 409, never a regression back to `approved`); only
a genuinely conflicting comment, a reject-after-approval-lineage, or an
approve-after-rejected is `409`. A `reject` decision has no equivalent
lineage — `rejected` is always terminal.

**Execution** (tool-gateway + control-plane's executor endpoints):
`approved -> executing` is idempotent (a retried `execution/start`
call on an already-`executing` proposal returns it unchanged, no
duplicate event) — this is the documented crash-retry re-entry point:
a prior attempt already started execution and crashed before a result
was ever recorded; a fresh `execute()` call retries the SAME
idempotent action and tries recording a result again.
`executing -> succeeded|failed` is likewise idempotent: an
already-terminal proposal returns its existing result for the SAME
outcome, and `409`s for a CONFLICTING one.

**The one allowlisted action itself** is inherently idempotent at the
application level: clearing an active fault transitions it to
inactive; clearing an already-inactive fault is an equally safe
200 no-op (`changed: false`).

## 13. At-least-once execution reality (honest, not hidden)

Tool-gateway's own execute handler can itself crash between the real
action succeeding and the durable result being recorded — the SAME
honest limitation Phase 7 already states for its own external calls.
This phase does not claim exactly-once invocation of the real action;
it claims:

```
at-least-once invocation  +  idempotent action semantics  +  idempotent durable bookkeeping  =  safe to retry
```

A retried `execute()` call (approved/executing both route through the
same code path) always re-runs the SAME idempotent clear+verify and
tries recording a result again — it never duplicates a real-world
side effect and never creates a duplicate durable event.

tool-gateway's own transient-vs-terminal split mirrors Phase 7's
TRANSIENT/RETRYABLE-vs-TERMINAL discipline exactly: control-plane or
payment-service being genuinely UNREACHABLE is transient (`503`,
nothing recorded, the proposal stays `executing`, safely retryable);
control-plane/payment-service being REACHABLE but giving a definitively
bad result (the clear request itself failing, or the independent
post-clear verification failing) is terminal (`409`, a real
`execution_failed` is recorded, the incident rolls back).

## 14. Recovery verification

Tool-gateway NEVER reports success merely because the HTTP clear
request returned 2xx. After calling `POST .../clear`, it independently:

1. re-fetches the fault's own status (`GET .../authorization`,
   `PAYMENT_REMEDIATION_TOKEN`) and confirms `active: false`
2. re-fetches payment-service's EXISTING health contract (`GET
   /health` — not `/health/ready`, which payment-service has never
   exposed; this phase reuses the contract that already exists rather
   than inventing one) and confirms the exact documented shape,
   `status == "UP" and service == "payment-service"`

Only if both hold does it record `execution_succeeded`; otherwise it
records `execution_failed` (and, in the same control-plane
transaction, rolls the incident back `remediating -> investigating` —
§6).

**`verify_recovery` independently re-proves all three facts itself**
(correction round, finding #2) — it never merely re-asserts
`execute_remediation`'s own synchronous HTTP response, and never trusts
durable bookkeeping alone either:

1. re-fetches the proposal from control-plane's own durable record and
   confirms `status == "succeeded"`
2. re-fetches tool-gateway's own authenticated
   `GET /api/v1/remediation-capabilities` (extended with a
   `target_healthy` field alongside the existing `precondition_met`)
   and confirms `precondition_met == false` (the fault is independently
   observed inactive)
3. the SAME fresh read confirms `target_healthy == true`

All three must hold before `remediation_status` is ever reported as
`"succeeded"`; the bounded `recovery_verification` state field records
all three booleans (`proposal_succeeded`, `fault_inactive`,
`target_healthy`), never collapsed into one. If any is false,
`remediation_status` is `"failed"` even though control-plane's own
bookkeeping says the execution succeeded — a rare, honest signal that
something regressed between execution and this independent re-check,
never papered over. A temporary tool-gateway/control-plane outage while
verifying (as opposed to a confirmed bad result) remains
TRANSIENT/RETRYABLE, exactly like every other dependency call in this
graph. The acceptance script's own stronger proof is a REAL fresh
checkout request returning 200/COMPLETED after remediation (§16).

**Ambiguous execute() responses are reconciled, never blindly
terminalized** (correction round, finding #1): a malformed/lost
tool-gateway response, or an HTTP 502, does not prove the mutation
never happened — `execute_remediation` independently re-fetches the
proposal from control-plane before concluding anything. If control-
plane's own durable record already says `succeeded`/`failed`, that REAL
outcome is reported (never re-executed). If it still says
`approved`/`executing` — genuinely unknown/in-flight — the node raises
`ToolGatewayAmbiguousExecutionError`, left deliberately UNCAUGHT so the
checkpoint is never committed and the run stays resumable at the exact
same node, the same TRANSIENT/RETRYABLE convention as every other
dependency outage in this graph.

## 15. Incident lifecycle integration

Reuses the EXISTING lifecycle state machine
(`domain/lifecycle.py`, unmodified) exactly:
`investigating -> remediating` is already a legal transition; nothing
new was added to the matrix. A human/operator first transitions the
fresh incident `open -> investigating` via the EXISTING lifecycle
endpoint and token. When that same human approves a proposal, the
approval transaction ATOMICALLY performs, in one database transaction
(`RemediationRepository.decide`):

- proposal `pending_approval -> approved`
- incident `investigating -> remediating`
- a `remediation_events` `approved` row
- an `incident_events` `status_transition` row

If the incident is not currently `investigating` at that moment (it
drifted — a human already moved it, or an independent automatic
resolution beat the approval), the WHOLE approval fails `409`, touching
NOTHING — agent-runtime-service never holds the lifecycle token and
never calls `PATCH /api/v1/incidents/{id}/status` directly; the human
approval operation itself is what authorizes entering `remediating`.
Rejecting a proposal never transitions the incident at all.

A SUCCEEDED remediation leaves the incident in `remediating` — it does
NOT fake a resolution. The EXISTING Alertmanager-driven automatic
resolution path (Phase 3D, unmodified) is what eventually transitions
it `remediating -> resolved`, once the real `CheckoutServerErrors`
condition genuinely clears.

## 16. Audit trails

Both the incident's own `incident_events` (Phase 3E, unmodified
schema) and the new `remediation_events` are real, append-only
PostgreSQL tables (§4). A complete Phase 8 acceptance run produces:

```
incident:    created -> investigating -> remediating -> resolved
remediation: proposed -> approved -> execution_started -> execution_succeeded
```

The one necessary exception to "never widen an existing vocabulary":
`incident_events.actor_type` (V3, never modified) only distinguishes
`alertmanager` (fully-automatic ingestion) from `operator`
(authenticated non-Alertmanager write). A FAILED remediation's own
incident rollback (`remediating -> investigating`, §6) is control-plane's
own authenticated, executor-triggered transition — categorically
closer to `operator` than to raw alert ingestion — recorded as
`actor_type='operator'` with `metadata.resolution_source =
"remediation_execution_failed"` disambiguating it honestly, the same
"use metadata for nuance the bare vocabulary can't express" convention
the existing Alertmanager-resolution path already uses
(`metadata.resolution_source = "alertmanager_webhook"`).

## 17. Credential boundaries

| Credential | Held by | Capability |
|---|---|---|
| `CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN` | agent-runtime-service only | create a proposal only |
| `CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN` | human/operator only (or a CI script simulating one) | approve/reject only |
| `CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN` | tool-gateway only | record execution start/result only |
| `TOOL_GATEWAY_EXECUTION_TOKEN` | agent-runtime-service (caller) + tool-gateway (verifier) | ask tool-gateway to act; alone never sufficient |
| `PAYMENT_FAULT_INJECTION_TOKEN` | test/operator path only | enable the fault only |
| `PAYMENT_REMEDIATION_TOKEN` | tool-gateway only | clear/read the fault only |

None of the five Bearer-style tokens is ever interchangeable with any
other — `resolve_write_tokens` (control-plane) performs a full
pairwise check across all five control-plane tokens (plus the two
pre-existing webhook/lifecycle ones) at startup, clearing only the
colliding pair if any two are ever configured identically, same
fail-closed philosophy as Phase 3D's original two-token guard.
Structural tests (`test_read_only_guarantees.py`,
`test_remediation_auth.py`, tool-gateway's own Go tests) assert these
boundaries directly against source/behavior, not merely by convention.

`scripts/init-remediation-secrets.sh` generating distinct secrets is
defense-in-depth, not the authoritative boundary — an operator can
hand-edit `.env` or wire up a different deployment system entirely that
never ran it. Correction round (finding #3) adds a RUNTIME, fail-closed
guard at each remaining credential boundary the initializer cannot
enforce after the fact:

- **payment-service**: if `PAYMENT_FAULT_INJECTION_TOKEN` and
  `PAYMENT_REMEDIATION_TOKEN` are ever configured identically, BOTH are
  disabled (neither endpoint can ever authenticate) rather than letting
  the recovery credential also create the fault it is supposed to only
  clear — logged by variable name only, never by value.
  `POST /payments/authorize` is completely unaffected, since this
  service must keep serving normal payment traffic regardless.
- **tool-gateway**: a dedicated, single-purpose mutation service with
  no unrelated functionality to preserve — `ValidateNoTokenCollisions`
  checks all three of its own tokens pairwise and REFUSES TO START
  (never logging a value) if any two collide, since a compromised
  inbound `TOOL_GATEWAY_EXECUTION_TOKEN` must never implicitly also be
  a valid outbound credential.

## 18. Acceptance flow

`scripts/verify-remediation.sh` (sourcing `verify-agent-runtime.sh` ->
`verify-rag.sh` -> `verify-investigator.sh`, and `simulate-failure.sh`
for `do_checkout`/`assert_checkout_failed_with`) proves, against the
real running stack, with its OWN fresh incident:

1. every involved service healthy; the fault initially OFF;
   `CheckoutServerErrors` initially inactive (never reused from an
   earlier run)
2. a freshness checkpoint, then the fault enabled (injection token
   only)
3. real checkout requests genuinely fail through payment-service;
   sustained until the real alert fires
4. the real Alertmanager webhook creates a fresh incident after the
   checkpoint
5. a human/operator transitions it `open -> investigating`; a durable
   agent run is created and resumed to the REAL interrupt
6. the proposal is independently visible in PostgreSQL via
   control-plane, with the correct action/target and audit event, and
   from the SAME AgentRun safe view
7. tool-gateway execution BEFORE approval is refused; the run survives
   a real agent-runtime-service restart WHILE waiting, still showing
   the SAME proposal; a normal resume before approval is `409`
8. a simulated human approval (the real control-plane approver
   endpoint) atomically moves the proposal to `approved` and the
   incident to `remediating`, with both audit events
9. resuming the SAME run makes tool-gateway independently verify
   approval, execute the ONE allowlisted action, clear the real fault,
   verify recovery, and record `execution_succeeded`; the graph
   reaches `verify_recovery`/`finalize`
10. the real fault is OFF, the action was not duplicated, a REAL fresh
    checkout now returns 200/COMPLETED
11. the real alert naturally recovers; the SAME incident naturally
    transitions `remediating -> resolved` via Alertmanager's own real
    resolved webhook
12. the complete audit trail, on both sides, is intact; historical
    data was never deleted; the ONLY rows mutated/created are this
    run's own scoped incident and proposal (never a blanket
    "zero mutation elsewhere" claim — Phase 8 is SUPPOSED to mutate
    its own incident/remediation rows)

A separate, smaller rejection-path test (real PostgreSQL via
`test_remediation_transactions.py` and the real LangGraph interrupt via
`test_remediation_durability.py`) proves: pending proposal -> human
rejects -> LangGraph resumes -> no execute request -> no payment call
-> no incident `remediating` transition -> proposal `rejected` -> run
finalizes reflecting rejection.

`EXIT` cleanup ALWAYS attempts to clear the controlled fault and
confirm payment-service healthy, even when the script fails midway —
a failed acceptance run must never leave payment-service deliberately
broken for whatever runs next.

## 19. Known limitations (honest, not hidden)

- Exactly one executable remediation action exists.
- The action is a local-development, application-level recovery
  mechanism — no Docker restart, no deployment rollback, no scaling,
  no Kubernetes, no AWS.
- No frontend approval UI yet (Phase 9) — human approval happens
  through the typed API or the `make remediation-approve`/
  `remediation-reject` helpers.
- At-least-once action invocation around a crash boundary; safety
  relies entirely on the action's own idempotence (§13), not on any
  exactly-once delivery guarantee.
- The controlled payment fault's state is in-memory and resets on a
  payment-service process restart.
- Concurrent approval/execution races are bounded by real database
  optimistic concurrency (compare-and-swap UPDATEs); genuine
  distributed multi-region execution is out of scope.
- The real OpenAI investigator provider still requires a user
  credential for a real (non-stub) smoke test — unchanged from Phase 5.
- `reliability.incidents` still does not persist the Alertmanager
  `alertname` label itself (§5's own stated coupling).

## 20. Future Kubernetes Tool Gateway evolution

The Tool Gateway boundary this phase establishes — a small service
with no direct infrastructure credential, a hard allowlist, and
independent re-verification of every approval before acting — is
designed to be the SAME boundary a future phase extends with real
Kubernetes/Docker capability (pod restart, deployment rollback,
horizontal scaling), once real RBAC/namespace scoping exists to bound
that capability the way this phase's allowlist bounds its one action.
Nothing in this phase's execute/capability API shape (`proposal_id`
only in, a bounded structured result out) needs to change for that —
only the allowlist and the downstream client package grow.
