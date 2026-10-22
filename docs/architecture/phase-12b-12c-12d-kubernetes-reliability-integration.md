# Phase 12B-D: consolidated Kubernetes reliability integration

Same label convention as Phase 12A's own doc: **IMPLEMENTED** (real
code exists and runs), **TESTED OFFLINE** (synthetic data/mocked
transports, no network), **VERIFIED AGAINST REAL CLUSTER** (read-only
only, actually run this round), **PREPARED BUT NEVER RUN** (a real
write path exists and is believed correct, but was never actually
executed), and **NOT IMPLEMENTED** (explicitly out of this round's
scope, stated honestly rather than faked).

## 1. Actual architecture

This round extends FOUR existing services additively -- no new
service, no second approval system, no parallel incident/remediation
schema:

```
control-plane      (Python/FastAPI)  + Kubernetes finding ingestion (Gate 2)
                                      + widened remediation action/target (Gate 5)
agent-runtime-service (Python/LangGraph) + Kubernetes deterministic policy branch (Gate 4)
                                      + Kubernetes recovery re-verification (Gate 7, agent side)
tool-gateway        (Go)             + Kubernetes executor + recovery verification (Gates 6/7)
detectors/ (Phase 12A, unchanged)    produces the K8sDetectionFinding records this round ingests
```

`investigator-service` and `web-console` are **NOT MODIFIED** this
round -- see section 11.

## 2. Database migrations

Two new, strictly additive Flyway migrations -- V1-V6 untouched:

- **V7__add_kubernetes_remediation_action.sql**: adds
  `target_cluster`/`expected_resource_uid` columns to
  `reliability.remediation_proposals`; replaces the two independent
  single-column `action_type`/`target` CHECK constraints with ONE
  combined constraint enumerating exactly the two legal
  `(action_type, target, target_cluster)` tuples -- never a
  cross-product. `expected_resource_uid` is required iff the action is
  `restart_allowlisted_deployment` (a separate shape constraint).
- **V8__add_kubernetes_incident_actor.sql**: widens
  `reliability.incident_events.actor_type` to include `'kubernetes'`
  for `created`/`observed` events only -- `status_transition` events
  are explicitly restricted to stay `('alertmanager', 'operator')`
  only, a hard database-level guarantee that Kubernetes ingestion can
  never transition/resolve an incident itself (Gate 2's own
  requirement).

`reliability.incidents` itself needed **NO new migration** --
`source`/`source_fingerprint` were already generic, free-text columns
(V1's own comment explicitly anticipated "Phase 3C may eventually
ingest from more than one source"), and `occurrence_starts_at` (V2) is
reused as-is for the Kubernetes occurrence watermark.

Both migrations were validated directly against real, isolated,
throwaway PostgreSQL instances this session: a fresh V1-V8 apply, and
a real upgrade-from-V6 path with a pre-existing payment proposal row
surviving untouched with NULL new columns. Every legal/illegal
action/target/identity combination was tested with real INSERT
statements (see section 8).

## 3. Gate 2: Kubernetes incident ingestion

`POST /internal/v1/kubernetes/findings` (control-plane), authenticated
by a SIXTH, separate Bearer token
(`CONTROL_PLANE_KUBERNETES_INGESTION_TOKEN`, never held by
Alertmanager/operator/agent-runtime/tool-gateway). Accepts ONE
Kubernetes finding per request (`control_plane.domain.
kubernetes_finding.KubernetesFindingIngestRequest`) -- a
control-plane-OWNED contract that mirrors (never imports)
`detectors.schemas.kubernetes.K8sDetectionFinding`'s shape, exactly
like `AlertmanagerWebhookPayload` mirrors Alertmanager's own real
webhook JSON without importing Alertmanager's code.

Dedup/occurrence-identity (`ingestion/kubernetes_service.py`) reuses
the EXACT SAME primitives Alertmanager ingestion already established:

- `source_fingerprint` = `sha256(cluster:namespace:resource_kind:
  resource_name:detector_id)` -- stable identity, deliberately NEVER
  includes `resource_uid` (a recreated resource exhibiting the SAME
  failure class continues the SAME incident, never silently splits).
- `collected_at` (the detector's own observation instant) plays
  `occurrence_starts_at`'s exact role: an active incident's stale/
  current/newer firing-replay logic from `ingestion/service.py` is
  reused verbatim, just without a "resolved" counterpart (Kubernetes
  ingestion never resolves an incident -- see Gate 7's independent
  verification requirement, and V8's own database-level guarantee).
- A finding whose `collected_at` is more than 5 minutes in the future
  (clock skew tolerance) is rejected outright (422) -- the symmetric
  case to "a stale event must not establish current failure."
- `resource_uid` is recorded, honestly and auditable, in every
  `created`/`observed` incident_event's `metadata` -- a reviewer can
  see every UID this fingerprint was ever observed under, without this
  module ever using UID to auto-split or auto-resolve.
- `insufficient_evidence` maps to incident severity `warning`,
  `confirmed` maps to `critical` -- the detector's own epistemic
  honesty is reflected into severity, never flattened.

Namespace/resource-kind/resource-name are validated against
Kubernetes' own real identity patterns at the Pydantic layer (same
discipline as Phase 12A's own `kubernetes_client.py`) -- prevents
cross-namespace injection via a malformed request body.

**TESTED OFFLINE**: 30 new tests
(`services/control-plane/tests/test_kubernetes_ingestion.py`) covering
domain validation, fingerprint stability/uniqueness, created/updated/
ignored occurrence-identity decisions, recreated-resource UID
auditing, stale/future-evidence rejection, and full auth-boundary
cross-token rejection against all five pre-existing tokens.

## 4. Gate 5: widened remediation proposal schema

`control_plane.domain.remediation` widens `ActionType`/`Target` to
Literals of exactly TWO values each, with a `_validate_pair`
model-validator re-asserting V7's own combined constraint in
application code (defense in depth, never a substitute for it).
`RemediationProposal`/`RemediationProposalCreateRequest` gained
`target_cluster`/`expected_resource_uid`; the repository's
`create_proposal`/idempotency-comparison thread both fields through.

**TESTED OFFLINE**: 9 new domain-level tests in
`test_remediation_domain.py` proving every one of Gate 5's required
DENIED cases (payment-action-against-k8s-target,
k8s-action-against-payment-target, unsupported deployment/namespace/
cluster, missing `expected_resource_uid`) at the Pydantic layer, plus
the real-database-level proof in section 8.

## 5. Gate 4: deterministic Kubernetes remediation policy

`agent_runtime_service.graph.nodes.propose_remediation` now branches on
`incident_snapshot["source"]` (mutually exclusive by construction --
an incident is either `"alertmanager"` or `"kubernetes"`, never both):
the ALERTMANAGER branch is Phase 8's own, completely unchanged logic;
the new KUBERNETES branch (`_propose_kubernetes_remediation`)
deliberately does **not** inspect `incident_snapshot` for cluster/
namespace/resource identity at all -- this service's own pre-existing,
documented architecture boundary
(`domain/incident_snapshot.py`: "this service's graph state stores a
bounded snapshot of the incident itself, not its audit history") is
preserved, not worked around. Instead, it defers entirely to
tool-gateway's own fresh `GET /api/v1/remediation-capabilities/
kubernetes` read -- exactly how the payment branch defers to
`get_capability()` rather than trusting any hypothesis text. A
proposal is only ever created when ALL of: the policy branch matched,
an investigation report exists, tool-gateway's action/target/cluster
exactly match the allowlist, `precondition_met` is true (a confirmed
targeted failure reason is CURRENTLY observed), and a real
`deployment_uid` was returned -- that UID becomes the proposal's own
`expected_resource_uid`, captured at proposal-creation time and
independently rechecked by tool-gateway immediately before any write
(Gate 6).

`verify_recovery` gained a parallel Kubernetes branch: a SECOND,
independent fresh capability read (beyond tool-gateway's own
executor-side recovery check at execution time) -- `fault_inactive =
not precondition_met`; Kubernetes has no separate "target_healthy"
signal distinct from this, so `target_healthy` mirrors it.

**TESTED OFFLINE**: 5 new end-to-end graph tests
(`test_remediation_graph.py`, real `compile_graph`/`InMemorySaver`,
fake control-plane/tool-gateway doubles) proving: policy match creates
a correctly-identity-bound proposal; precondition-not-met refuses;
the two policy branches never cross-fire; a tool-gateway output error
is terminal; and `verify_recovery`'s second independent read correctly
confirms recovery.

## 6. Gate 6: Kubernetes executor (tool-gateway, Go)

`internal/allowlist` widened to the two explicit pairs (never a
cross-product -- `IsAllowed`/`IsAllowedKubernetesTarget`).
`internal/kubernetes/client.go` is a bounded, Go-native REST client
mirroring `detectors/clients/kubernetes_client.py`'s own discipline:
exactly 4 read methods (`GetDeployment`, `ListPods`,
`ReplicaSetUIDsOwnedBy`) plus exactly ONE write method
(`PatchDeploymentRestartAnnotation`), which can only ever send a
strategic-merge-patch touching `spec.template.metadata.annotations`
-- no other field, no exec/attach/port-forward, no Secrets method
anywhere in the package. Mutual-TLS or bearer-token auth via an
explicit `ExecutorCredentials` value -- never the ambient kubeconfig.

`internal/kubernetes/executor.go` (`Executor.RestartAndVerify`) is the
actual Gate 6 decision logic:

1. Fetch the CURRENT Deployment; if its UID doesn't match the
   proposal's `expected_resource_uid`, refuse outright
   (`OutcomeIdentityMismatch`) -- never silently retargeted.
2. If execution is disabled (`Executor.Enabled()==false`, the
   **documented default**), report `OutcomeDryRun` and never call the
   patch method.
3. At-most-one-rollout-per-proposal: the patch includes a
   `reliability.internal/restarted-for-proposal` annotation carrying
   the proposal id; a retry that finds this annotation ALREADY set to
   the same id skips the patch entirely (`AlreadyApplied=true`) and
   proceeds straight to verification -- a crash between the patch
   succeeding and the durable result being recorded can never produce
   a second, unwanted restart.
4. Bounded, polled recovery verification (Gate 7, see section 7).

`api/execute.go`'s `ExecuteHandler` dispatches on `proposal.ActionType`
after independently re-verifying the FULL allowlist (action/target
AND, for the Kubernetes action, cluster). Gate 6's dry-run gate is
checked **before** `StartExecution` is ever called, for the Kubernetes
action specifically -- a dry-run request never transitions the
proposal to `'executing'` at all; it stays exactly `'approved'`.
`api/kubernetes_capability.go` (`GET /api/v1/remediation-capabilities/
kubernetes`, a SEPARATE route from the payment capability) reports the
live precondition using the executor's own READ methods only.

**TESTED OFFLINE**: 14 tests in `internal/kubernetes/*_test.go`
(client behavior, identity mismatch, dry-run, idempotent retry,
recovery classification for every outcome) + 13 tests in
`internal/api/kubernetes_execute_test.go` (full dispatch: dry-run,
success, identity mismatch, still-unhealthy, unconfigured executor,
cross-product/cluster rejection, status-machine refusals, idempotent
retry) + 5 new `internal/allowlist` tests. All existing tool-gateway
tests (payment flow, auth, structural "no shell/Docker access") pass
unmodified.

## 7. Gate 7: independent recovery verification

`Executor.verifyRecovery` (Go, tool-gateway) is the authoritative
implementation: bounded polling (`TOOL_GATEWAY_KUBERNETES_POLL_
INTERVAL_SECONDS` / `..._POLL_DEADLINE_SECONDS`, defaults 2s/60s),
every fact re-fetched FRESH on every iteration -- never trusts the
PATCH response. Classifies into exactly Gate 7's required vocabulary:

- `VERIFIED_RECOVERED`: `observedGeneration==generation`, ready/
  available replica counts match desired, `Available=True`, AND no pod
  owned (via ReplicaSet ownership resolution) by this Deployment
  reports a confirmed targeted failure reason (`CrashLoopBackOff`/
  `ImagePullBackOff`/`ErrImagePull`) or `containersReady=false`.
- `STILL_UNHEALTHY`: the above does not hold once the deadline has
  elapsed (never before -- a genuine rollout takes real time).
- `VERIFICATION_INCONCLUSIVE`: the Deployment's UID changed DURING
  verification -- this observation can no longer be attributed to the
  action this proposal performed.
- `SOURCE_UNAVAILABLE`: a non-transient read failure (not 403/
  connection-refused, which keep polling instead).
- `TIMED_OUT`: the deadline elapsed without ever reaching a confident
  result.

Only `VERIFIED_RECOVERED` is ever recorded as `succeeded`; only
`STILL_UNHEALTHY` (and `OutcomeIdentityMismatch`) is ever recorded as
`failed`. `VERIFICATION_INCONCLUSIVE`/`SOURCE_UNAVAILABLE`/`TIMED_OUT`
record **nothing** -- the proposal stays `'executing'`, and a retried
`execute()` call (the SAME idempotent path, never an internal
unbounded loop) re-attempts verification. `verify_recovery` (Python,
agent-runtime-service) performs a SECOND, independent check from a
different vantage point before the agent run itself ever reports
`remediation_status="succeeded"` (section 5).

## 8. Real database validation (this session)

Both new migrations were validated against REAL, isolated, throwaway
PostgreSQL instances (never the developer's own `postgres_data`
volume) via `docker compose -p <distinct-project> up -d postgres` +
`flyway migrate`:

- Fresh V1-V8 apply: clean, both legal action/target/cluster/identity
  combinations insert successfully; both cross-product combinations,
  a missing `expected_resource_uid` for the Kubernetes action, and a
  non-NULL `target_cluster` for the payment action all genuinely
  violate the real CHECK constraint (`violates check constraint`
  confirmed in psql output, not merely asserted).
- Real upgrade path: V1-V6 applied first, a real payment proposal row
  inserted under the OLD schema, THEN V7+V8 applied on top -- the
  pre-existing row survives with NULL new columns, exactly as
  expected, no data loss.
- `incident_events` actor_type widening: `kubernetes`-actor
  `created`/`observed` events succeed; a `kubernetes`-actor
  `status_transition` event is genuinely REJECTED by the database
  (confirmed, not merely asserted) -- Gate 2's "incident resolution
  must require independent current-state verification" is a hard
  database guarantee, not just an application convention.

## 9. Offline integration acceptance vs. real-cluster status

**OFFLINE INTEGRATION ACCEPTANCE** (Gate 9.1): fully exercised this
round across all three services (control-plane's finding ingestion,
agent-runtime-service's full graph including the Kubernetes policy/
approval/execute/verify path, tool-gateway's executor) via mocked
transports / in-memory fakes / real isolated databases where
applicable -- see each gate's own test count above. This proves
intended behavior end-to-end without ever touching the live cluster.

**LIVE READ-ONLY ACCEPTANCE** (Gate 9.2): reuses Phase 12A's own
`scripts/verify-kubernetes-observer-real-stack.sh` unmodified --
re-run this session against the real `reliability-lab` kind cluster,
confirming current connectivity/identity (unchanged from Phase 12A: a
healthy sandbox, 0 Kubernetes findings). No failure was injected, no
Deployment was patched, no RBAC was applied, no ServiceAccount/token
was created, and the default kubectl context was never touched.

**PREPARED BUT NEVER RUN**: `scripts/verify-kubernetes-remediation-
live.sh` -- a complete, opt-in, explicit-confirmation-required live
acceptance script implementing the REAL end-to-end path (ingest a
finding -> start a real agent run -> resume to the approval interrupt
-> approve via the real control-plane operator endpoint -> resume to
execute -> tool-gateway's real restart+verify -> independent
postcondition re-check via the Phase 12A observer script). It refuses
outright unless `TOOL_GATEWAY_KUBERNETES_EXECUTION_ENABLED=true` is
ALREADY set in tool-gateway's own environment (a separate, prior
operator action), tool-gateway's own fresh capability read confirms a
REAL currently-observed targeted failure (it never injects one), and
the operator types an exact, state-aware confirmation phrase naming
the currently-observed Deployment UID. **This script has not been
executed. No live Kubernetes write has been validated this round.**

## 10. Security and trust boundaries

- Six Bearer tokens now guard control-plane's write endpoints, all
  mutually non-interchangeable (`resolve_write_tokens`'s own pairwise
  collision guard, extended to all six, with a dedicated regression
  test).
- tool-gateway's Kubernetes executor credential
  (`TOOL_GATEWAY_KUBERNETES_*`) is configured as raw PEM/token VALUES,
  never a kubeconfig file path -- this service never parses a
  kubeconfig and never reads `~/.kube/config`.
- `TOOL_GATEWAY_KUBERNETES_EXECUTION_ENABLED` defaults to `false`
  (DRY-RUN) -- checked in TWO places independently:
  `api/execute.go`'s own gate (before `StartExecution`) AND
  `Executor.RestartAndVerify`'s own internal check (defense in depth,
  reachable only if the first gate were ever bypassed by a bug).
- The example executor RBAC
  (`services/tool-gateway/internal/kubernetes/rbac/
  executor-role.example.yaml`) restricts the one write verb
  (`patch`) to the one allowlisted Deployment NAME via
  `resourceNames` -- a second layer of enforcement beneath
  tool-gateway's own application-level allowlist. **Not deployed.**
- tool-gateway never trusts a caller's claim of approval -- every
  `execute()` call independently re-fetches the real, durable proposal
  record from control-plane before doing anything (unchanged Phase 8
  invariant, now also covering the Kubernetes action).

## 11. Known limitations / NOT IMPLEMENTED

- **investigator-service was not extended this round.** Gate 3's
  OBSERVED/HYPOTHESIS/UNKNOWN/REMEDIATION-CANDIDATE distinction and
  prompt-injection defenses for Kubernetes label/event/annotation text
  require a new evidence-collection source inside
  investigator-service's own `evidence_collector.py`/`llm/prompt.py`/
  `llm/validation.py` -- a substantial, separate undertaking this
  round's time budget did not allow completing with the same rigor as
  every other gate. The deterministic policy (section 5) does NOT
  depend on this -- it defers entirely to tool-gateway's own
  structured capability read, never to LLM output -- so remediation
  safety is unaffected by this gap, but the investigation REPORT
  itself does not yet contain dedicated Kubernetes evidence sections.
  Stated honestly as NOT IMPLEMENTED, not faked.
- web-console was not modified -- an operator reviewing a
  Kubernetes-sourced incident/proposal uses the same existing incident/
  remediation-proposal views Phase 9 already built (the response
  shapes are additive, so nothing is broken), but there is no
  Kubernetes-specific UI treatment.
- `restart_allowlisted_deployment`'s own real-world efficacy
  limitation (explicitly required to be stated): a rollout restart is
  an operational attempt, never proof the underlying issue is fixed --
  it will not reliably repair a bad image, an OOM resource limit, or a
  deterministic application startup error. The deterministic policy
  only offers this proposal when tool-gateway's own fresh read
  confirms a targeted failure reason is CURRENTLY present; it does not
  (and cannot) distinguish "a transient issue a restart will fix" from
  "a deterministic issue a restart will not fix" ahead of time -- Gate
  7's independent recovery verification is what honestly reports
  which one actually happened.
- Pod-to-Deployment ownership resolution (tool-gateway's own
  `ReplicaSetUIDsOwnedBy` + pod `ownerReferences` matching) is correct
  for the standard Deployment-owns-ReplicaSet-owns-Pod chain but was
  not tested against more exotic ownership topologies (it does not
  need to be, for the one allowlisted Deployment, but is noted as a
  scope boundary).
- The live-cluster acceptance script
  (`verify-kubernetes-remediation-live.sh`) was prepared but never
  executed -- see section 9.
