# Phase 12A: Kubernetes observer and failure detectors

Four labels are used throughout this document, same convention as
Phase 11B's own doc: **IMPLEMENTED** (real code exists and runs),
**TESTED OFFLINE** (covered by `detectors/tests/`, synthetic data, no
network), **VERIFIED AGAINST REAL CLUSTER** (actually run against the
live `reliability-lab` kind cluster this session, with real observed
output -- see section 8), and **PLANNED** (not built, explicitly
future work). This phase is **read-only observation only** -- no
remediation, rollback, scaling, or autonomous Kubernetes operation of
any kind exists anywhere in this code.

## 1. Actual architecture

A new subpackage alongside Phase 11B's existing `detectors/anomaly/`,
`detectors/traces/`, `detectors/invariants/` (all untouched):

```
detectors/
  clients/kubernetes_client.py   Gate B: bounded, read-only, 4-method GET client
  kubernetes/
    __init__.py
    parser.py                    Gate B: defensive, never-raising JSON -> typed-object parsing
    collector.py                 Gate B: I/O + CollectionOutcome classification
    detectors.py                 Gate D: 5 pure classification functions
    findings.py                  Gate E: K8sDetectionFinding -> FailureFinding (reused, never duplicated)
    rbac/observer-role.example.yaml   Gate 6: EXAMPLE RBAC, never applied
  schemas/kubernetes.py          Gate B: the Kubernetes observation contract
  tests/test_kubernetes_*.py     97 tests across 8 files, all offline/synthetic
                                 (includes the correction-round pagination/
                                 partial-collection and recovered-pod/
                                 stale-generation regression tests, section 13)
```

`detectors/pipeline/orchestrator.py` and `detectors/pipeline/run.py`
were extended **additively** with a new "KUBERNETES OBSERVATION" stage
inserted between invariant checks and correlation (section 5).
`detectors/cli/commands.py` gained `--kubeconfig`/`--kube-context`/
`--kube-namespace` on `analyze` (live mode only -- `replay` stays
fully offline and never touches Kubernetes, section 7).
`catalog/registry/detector_families.py` had 3 existing-but-previously-
unimplemented families (`resource_saturation`, `process_service_health`,
`deployment_regressions`) flipped to `implemented=True`, with their
`gaps_and_limitations` text naming exactly which Phase 12A
detector(s) back that flip and what remains unimplemented within each
family. No file under `services/**`, `database/**`, `observability/**`,
`knowledge/**`, `evals/**`, or `catalog/source/**` was touched.

## 2. Why no Kubernetes SDK

Same discipline as `prometheus_client.py`/`tempo_client.py`/
`control_plane_client.py`: a small, fixed set of GET-only REST calls
does not justify adopting the official `kubernetes` Python SDK (a
large, generated, far-higher-privilege-capable client). `kubernetes_
client.py` talks to the stable, versioned Kubernetes REST API
directly via `httpx`.

## 3. The real client-cert bug this phase caught (and fixed)

This is the one correctness-critical finding from Gate 2's real-cluster
testing. `KubernetesClient` originally passed the client certificate
to httpx via its `cert=(certfile, keyfile)` convenience parameter.
Against the real `reliability-lab` cluster, this silently failed: the
API server authenticated the connection as `system:anonymous` instead
of the configured mutual-TLS identity, which produced an honest, but
misleadingly-labeled, `403 Forbidden` on every resource (NEVER a false
healthy result -- the `CollectionOutcome.FORBIDDEN` discrimination did
its job). Confirmed via a side-by-side `httpx.Client(cert=...)` vs.
manually-built `ssl.SSLContext.load_cert_chain(...)` comparison
against the real API server (the former produced
`system:anonymous`/403, the latter `200` with real pod data). Fixed in
`_build_client()` by constructing the `ssl.SSLContext` explicitly --
confirmed against the real cluster (section 8) and covered by a
dedicated regression test (`test_client_cert_is_loaded_into_a_real_
ssl_context_not_passed_as_a_bare_tuple`) that would fail again if this
regressed back to the bare-tuple form.

## 4. Collection + classification layering

- `detectors/kubernetes/parser.py`: pure, defensive, never-raising
  JSON -> typed Pydantic object parsing (`PodObservation`,
  `DeploymentObservation`, `ReplicaSetObservation`, `EventObservation`).
  Malformed items are counted and skipped, never raised.
- `detectors/kubernetes/collector.py`: the one I/O layer. Every call
  returns `(CollectionResult, items)`; `CollectionResult.outcome` is
  always one of `SUCCESS` / `EMPTY` / `MALFORMED` / `UNAVAILABLE` /
  `FORBIDDEN` / `NOT_FOUND` -- a failed or forbidden collection is
  NEVER silently treated as "zero objects exist."
- `detectors/kubernetes/detectors.py`: pure classification over
  already-collected, already-parsed objects (no I/O). Returns `[]`
  for a healthy resource -- never a noisy per-object "NOT_PRESENT"
  entry.

## 5. The 5 detectors

| Detector | CONFIRMED requires | INSUFFICIENT_EVIDENCE when |
|---|---|---|
| `image_pull_backoff` | `waiting.reason` is `ImagePullBackOff`/`ErrImagePull` | (never -- this signal is unambiguous) |
| `crash_loop_backoff` | `waiting.reason=="CrashLoopBackOff"` OR (`restart_count>=3` AND a nonzero-exit-code last termination AND the container is NOT currently `running=True`+`ready=True`, section 13.3) | `restart_count>=3` with no termination evidence to corroborate it, OR the same restart/termination evidence but the container has RECOVERED (currently running+ready) |
| `oom_killed` | `terminated.reason=="OOMKilled"` explicitly | `exit_code==137` without that explicit reason (137 alone is never sufficient) |
| `deployment_rollout_failure` | `Progressing=False` with `reason=ProgressDeadlineExceeded` AND `observedGeneration==generation` (section 13.4) | `observedGeneration==generation` AND `Available=False` AND not actively `Progressing=True` but no `ProgressDeadlineExceeded` yet, OR a `ProgressDeadlineExceeded` condition whose generation is stale/unknown |
| `pod_readiness_degradation` | phase is `Running`/unset AND `Ready` condition is `False` | (always CONFIRMED as an observed fact; cause is deliberately never inferred -- see `uncertainty_notes`) |

Every finding instance carries real evidence fields read directly off
the collected object (timestamps, exit codes, condition reasons,
resource identity) plus a `decision_rationale` string and, where
applicable, `uncertainty_notes` -- never a fabricated cause.

## 6. Pipeline integration boundaries

- `kubernetes_client` is an **optional** keyword argument to
  `collect_and_detect`/`run_pipeline`, exactly like the existing
  Prometheus/Tempo/control-plane clients. `None` -> `("kubernetes_
  observation", "no Kubernetes client was supplied")` in `checks_not_
  executed`; the rest of the pipeline is completely unaffected.
- A FORBIDDEN/UNAVAILABLE/MALFORMED/NOT_FOUND pod collection means
  `kubernetes_pod_detectors` is itself recorded as NOT EXECUTED --
  classification is never attempted against a failed collection.
  Events are best-effort supporting evidence only: a failed events
  collection still lets pod-based classification proceed, with empty
  (never fabricated) `supporting_event_reasons`.
- **Kubernetes findings are deliberately NOT submitted to the existing
  cross-system `correlate()` engine in this round.** The kind sandbox
  and the docker-compose Prometheus/Tempo stack are genuinely separate
  environments with no real shared trace id, fingerprint, or observed
  dependency edge -- correlating them would fabricate evidence that
  does not exist. Proven by a dedicated pipeline-integration test
  (`test_kubernetes_and_prometheus_findings_are_never_auto_correlated`).
- `build_findings_from_kubernetes` reuses `catalog.schemas.finding.
  FailureFinding` directly (never a second incident schema). Findings
  are grouped by `(kind, namespace, name)`: a pod flagged by multiple
  detectors gets ONE `FailureFinding` with multiple `Observation`s.
  `candidate_known_scenario_matches` is always `[]` and
  `unresolved_classification` is always `True` -- a Kubernetes
  observation never requires, and never claims, a match against one
  of the 800 catalogued reference scenarios.
- No remediation, rollback, scaling, or write call exists anywhere in
  this stage; `remediation_proposals` on every produced finding stays
  empty (inherited from `FailureFinding`'s own default).

## 7. CLI integration

`python -m detectors analyze` gained `--kubeconfig`/`--kube-context`/
`--kube-namespace`: all three must be supplied together, or all
omitted (never a partial/ambiguous configuration); `--kube-context` is
always explicit, never defaulting to "whatever is currently active."
`_report_to_dict` now serializes `k8s_collection_results`/`k8s_
findings`. `python -m detectors replay` (the fully offline, fixture-
driven mode) does **not** gain Kubernetes fixture support in this
round -- Kubernetes observation is live-`analyze`-only for Phase 12A;
`replay`'s report always carries empty `k8s_collection_results`/`k8s_
findings` lists (covered by `test_replay_report_includes_empty_k8s_
fields`... see `test_cli.py`). Extending `replay` with a Kubernetes
fixture format is explicitly PLANNED, not built.

## 8. VERIFIED AGAINST REAL CLUSTER

Run this session via `make verify-kubernetes-observer-real-stack`
(`scripts/verify-kubernetes-observer-real-stack.sh`) against the real
`reliability-lab` kind cluster, namespace `reliability-sandbox`, using
the existing `~/kubernetes-reliability-lab/kubeconfig` (explicit path
and context, never the developer's own `~/.kube/config` or active
kubectl context). Real, observed output:

```
Kubernetes collection: Pod=success, Deployment=success, ReplicaSet=success, Event=empty
Kubernetes findings: 0 (0 CONFIRMED, 0 INSUFFICIENT_EVIDENCE)
  collection: Pod          outcome=success    detail=3 item(s) parsed successfully
  collection: Deployment   outcome=success    detail=3 item(s) parsed successfully
  collection: ReplicaSet   outcome=success    detail=5 item(s) parsed successfully
  collection: Event        outcome=empty      detail=the API call succeeded; zero items were returned
```

This is an **honest** result: the cluster's 3 sandbox pods
(`healthy-web`, `image-pull-demo`, `crashloop-demo` -- note the
deployment names do NOT reflect their current state) were all
confirmed, via direct `kubectl` inspection before and after this run,
to be `1/1 Running` with `restartCount=0` at the time this script ran.
The previously-captured OOM evidence (`~/kubernetes-reliability-lab/
evidence/oom-demo/`) is from an earlier, now-deleted Job and was never
treated as a current live failure. Zero events is also honest: the
cluster's event TTL had already expired them. This result is **not** a
substitute for the offline test suite's exercised failure scenarios --
it proves live connectivity, authentication, and classification-on-
healthy-data; it does not exercise the failure-pattern code paths
(section 5), which are only exercised offline (section 9) because
recreating a real failure in the shared sandbox was out of this
phase's scope.

The real captured OOM evidence (`pod.yaml`: `terminated.reason=
OOMKilled`, `exitCode=137`, `limits.memory=48Mi`; `describe.txt`:
Events section has no explicit "Killing" event in this snapshot -- an
honest real-world incompleteness) directly grounds
`test_oom_killed_confirmed_via_explicit_reason` and is also used by
`detectors/tests/test_catalog_coverage_integration.py`'s
`test_phase_12a_kubernetes_oom_evidence_is_also_unverifiable_not_
verified` to re-confirm Phase 11A/11B's own coverage-verification
trust boundary still holds: real, evidence-backed detector-implemented
status is still never conflated with an independently re-verified
`VERIFIED` coverage claim.

## 9. TESTED OFFLINE

319 tests pass (`catalog/tests` + `detectors/tests` combined; 299
before the correction round, section 13). 97 are Kubernetes-specific,
across 8 test files, plus 7 more Kubernetes-specific cases added to 3
pre-existing Phase 11B test files:

| File | Tests | Covers |
|---|---|---|
| `test_kubernetes_client.py` | 15 | outcome discrimination, namespace validation, bounded item count, structural 4-GET-method proof, mutual-TLS cert-chain regression |
| `test_kubernetes_kubeconfig_loader.py` | 6 | kubeconfig parsing, explicit-context requirement, credential-material cleanup |
| `test_kubernetes_parser.py` | 16 | defensive parsing of all 4 object types, malformed-item tolerance |
| `test_kubernetes_detectors.py` | 28 | all 5 detectors' CONFIRMED/INSUFFICIENT_EVIDENCE paths, including the real-evidence-grounded OOM case and the correction-round recovered-pod/stale-generation cases (section 13) |
| `test_kubernetes_findings.py` | 6 | grouping, provenance, empty scenario-match/remediation invariants |
| `test_kubernetes_pipeline_integration.py` | 6 | end-to-end `run_pipeline()`, no-client/healthy/forbidden/unavailable/non-correlation cases |
| `test_kubernetes_rbac_example.py` | 4 | the example RBAC manifest's own least-privilege structure |
| `test_kubernetes_pagination_and_partial_collection.py` | 11 | correction-round Issues 1 + 2: pagination, item/page caps, mixed valid/malformed items |
| `test_cli.py` (+2 new cases) | -- | `analyze`'s partial-kube-args validation error, `replay`'s report always carrying empty `k8s_*` fields |
| `test_safety_controls.py` (+4 new cases) | -- | no secrets/exec/attach/portforward path, exactly 4 GET-only methods, no hardcoded credential, namespace-string rejection |
| `test_catalog_coverage_integration.py` (+1 new case) | -- | the real OOM evidence still resolves to `UNVERIFIABLE`, never `VERIFIED` |

A separate, no-Docker shell regression test,
`scripts/test-verify-kubernetes-observer-quoting.sh` (`make
test-verify-kubernetes-observer-quoting`), proves the Issue 5 fix
(section 13.5) -- not a pytest file, since it tests shell-quoting
behavior directly.

Representative fixtures exercised offline: healthy pod/deployment,
`ImagePullBackOff`, `ErrImagePull`, `CrashLoopBackOff`, repeated
exit-1 failures without a crash-loop waiting reason, `OOMKilled`
(including the real-evidence-grounded case), exit-137-without-OOM,
rollout-in-progress (never flagged), `ProgressDeadlineExceeded`,
readiness degradation, missing events, missing termination data, 403
Forbidden, connection-refused (UNAVAILABLE), malformed/non-JSON
responses, multiple unrelated failures on distinct resources, and
determinism (two runs of the same fixture produce identical results).

## 10. RBAC design (PLANNED deployment, IMPLEMENTED example)

`detectors/kubernetes/rbac/observer-role.example.yaml`: a namespace-
scoped `ServiceAccount` + `Role` + `RoleBinding` (never `ClusterRole`/
`ClusterRoleBinding`), granting only `get`/`list`/`watch` on exactly
`pods`, `events`, `deployments`, `replicasets` -- no write verb, no
`secrets`/`configmaps` access, no `pods/exec`/`attach`/`portforward`
subresource, no `impersonate`/`bind`/`escalate`. Structurally proven
by `test_kubernetes_rbac_example.py`, which also confirms this file is
referenced by no script or Make target in this repo -- **it is not
deployed**. Applying it and minting its ServiceAccount token is an
explicitly separate, future, human-approved step; this phase's
real-cluster verification (section 8) used the existing cluster-admin
kind kubeconfig for read-only connectivity testing only, never this
Role.

## 11. Known limitations

- Kubernetes findings are never correlated with Prometheus/Tempo
  findings (section 6) -- a deliberate scope boundary for this round,
  not an oversight, since the two environments share no real
  evidence.
- `ReplicaSetObservation` collection exists but is not yet consumed by
  any detector -- no ReplicaSet-based classification logic (e.g.
  distinguishing a Deployment's own rollout failure from a stuck old
  ReplicaSet) was built this round.
- The real captured Events evidence (`describe.txt`) had no explicit
  "Killing" event at the time it was captured -- Kubernetes' Events
  API is inherently TTL'd/best-effort and this project's detectors
  correctly never depend on any single specific event existing.
- `replay` (fully offline fixture mode) has no Kubernetes fixture
  format yet -- Kubernetes observation is live-`analyze`-only.
- This phase's real-cluster verification (section 8) observed a
  healthy cluster; it did not exercise a live, currently-occurring
  real Kubernetes failure end-to-end (the sandbox's prior OOM Job was
  already deleted, and recreating a failure was out of this phase's
  explicit scope -- see the Gate 2 real-environment constraints this
  phase was given).

## 12. Security / read-only verification

`KubernetesClient` has exactly 4 public methods, all GET-only
(`test_kubernetes_client_has_exactly_four_get_only_resource_methods`);
no write/exec/attach/port-forward/secrets method exists anywhere in
this package (`test_kubernetes_client_never_references_secrets_exec_
attach_or_portforward`, `test_no_tool_gateway_client_or_remediation_
execution_path_exists`, `test_detectors_package_has_no_subprocess_or_
eval_exec_calls`). Namespace input is validated against Kubernetes'
own DNS-1123 label regex at construction time
(`test_kubernetes_client_rejects_arbitrary_namespace_strings`).
Credential material (certs/keys) is written only to a private
(0700/0600) temporary directory for the duration of one `with` block
and always removed afterward, and is never included in any exception
message, log line, or finding this module produces -- the one
legitimate `Authorization: Bearer {token}` header is built from a
variable, never a hardcoded literal
(`test_kubernetes_client_never_hardcodes_a_credential_value`). No
authentication material is committed to this repository.

## 13. Correction round: five targeted fixes

An independent review of this phase (still uncommitted at the time)
reproduced five edge-case defects against the original 76
Kubernetes-specific tests, all of which had been passing. Each is
fixed below with the smallest effective change; no unrelated
refactor, no Phase 12B/C/D work, and no cluster mutation was done.

### 13.1 New completeness semantics: `CollectionOutcome.PARTIAL`

`detectors/schemas/kubernetes.py` gained a sixth `CollectionOutcome`
member: `PARTIAL` -- some real evidence was collected and is
preserved, but collection is KNOWN INCOMPLETE. `PARTIAL` is included
in the pipeline's usable-outcome set (`detectors/pipeline/
orchestrator.py`'s `_USABLE_K8S_OUTCOMES`), so classification still
runs on whatever evidence exists (never discarded), but the
orchestrator ALSO appends a distinct `..._complete_coverage` entry to
`checks_not_executed` carrying the incompleteness reason -- "did
detection run" and "was coverage complete" are now two separate,
honest signals, never conflated. `PARTIAL` is produced by
`detectors/kubernetes/collector.py` in exactly these cases, never
SUCCESS or EMPTY:
- a continuation page (`metadata.continue`) remains uncollected after
  the bounded page-fetch limit (5 pages) was reached;
- the bounded item cap (`MAX_ITEMS`=500) was reached while a
  continuation page still remained, or a single non-compliant page
  itself exceeded the cap;
- a later page failed (connection error, 403, 404, or a malformed
  body) -- the FIRST page's own evidence is still preserved and
  returned, never discarded;
- any item(s) on an otherwise-200 response could not be parsed
  (Issue 2) -- a mix of valid and malformed items, or ALL items
  malformed, is never reported as a clean SUCCESS or EMPTY.

### 13.2 Issue 1 -- paginated results

**Before:** `{"metadata": {"continue": "tok"}, "items": []}` ->
`CollectionOutcome.EMPTY` (a false "nothing exists" result, even
though a continuation page was known to remain).

**After:** the collector follows continuation pages (bounded to 5)
before deciding an outcome; an empty-looking first page with a
`continue` token is never treated as complete until the pages that
actually exist have been fetched. If a non-compliant server returns
more than `MAX_ITEMS` in one page, or a later page cannot be fetched,
the result is `PARTIAL`, preserving whatever real items were
collected. See `detectors/tests/test_kubernetes_pagination_and_
partial_collection.py` (11 tests) for all required scenarios: empty
first page + continuation, nonempty first page + continuation, a
fully completed list, item-cap exceeded (with and without a
continuation token), a forbidden/unavailable subsequent page, a
first-page failure (still its own specific outcome, not PARTIAL), and
the page-fetch bound itself (proves an adversarial always-paginating
server can never cause an unbounded loop).

### 13.3 Issue 2 -- malformed items misreported as healthy

**Before:** a 200 response with 2 malformed Pods and 0 valid ones ->
`outcome=SUCCESS, items_count=0` (a clean "healthy, zero pods" result
built entirely from data this process could not even parse).

**After:** any malformed item on an otherwise-successful page forces
`PARTIAL` (never SUCCESS/EMPTY), whether 0 or some items were valid;
valid items are still preserved and returned. Covered by
`test_all_items_malformed_on_a_200_response_is_never_success_or_empty`
and `test_mixed_valid_and_malformed_items_discloses_partial_coverage`.

### 13.4 Issue 3 -- recovered pod falsely confirmed as crash-looping

**Before:** `running=True, ready=True, restart_count=5,
last_terminated={reason: Error, exit_code: 1}` -> CONFIRMED
`crash_loop_backoff` (a currently-healthy container was reported as
an ACTIVE crash loop based entirely on history).

**After:** `detect_crash_loop_backoff` (`detectors/kubernetes/
detectors.py`) now requires the container's CURRENT state to be
unhealthy or uncertain (NOT simultaneously `running=True` and
`ready=True`) before restart/termination evidence alone can CONFIRM.
A recovered container with the exact same historical evidence is now
INSUFFICIENT_EVIDENCE, with the restart count and last-termination
fields still honestly preserved in `evidence` and a `decision_
rationale` that states the container has recovered. A genuinely
active crash loop (same restart/termination evidence, but
`running=False`/`ready` unset or `False`) is still CONFIRMED --
proven by `test_genuine_active_crash_loop_without_waiting_reason_
is_still_confirmed_when_unhealthy`, alongside the new recovered-case
test `test_recovered_running_and_ready_container_is_not_confirmed_
crash_looping`. The direct `waiting.reason=="CrashLoopBackOff"` path
is unchanged (that is already current-state evidence).

### 13.5 Issue 4 -- stale rollout condition confirms new-generation failure

**Before:** `generation=6, observedGeneration=5, Progressing={status:
False, reason: ProgressDeadlineExceeded}` -> CONFIRMED (the condition
carries no generation stamp of its own and could belong to generation
5's already-resolved rollout, not generation 6's).

**After:** `detect_deployment_rollout_failure` only CONFIRMS a
`ProgressDeadlineExceeded` condition when `observedGeneration ==
generation` (the controller has confirmed it processed the current
spec). A stale (`observedGeneration < generation`) or entirely
missing generation pair now produces INSUFFICIENT_EVIDENCE instead,
with a `decision_rationale` explaining the condition may belong to a
prior generation. The genuine, matching-generation case is unchanged
(still CONFIRMED) -- see `test_stale_progress_deadline_exceeded_
condition_is_not_confirmed`, `test_matching_generation_progress_
deadline_exceeded_is_still_confirmed`, and `test_missing_generation_
fields_with_progress_deadline_exceeded_is_not_confirmed`.

### 13.6 Issue 5 -- verification script shell injection

**Before:** `scripts/verify-kubernetes-observer-real-stack.sh` built
its `docker run ... bash -c "..."` invocation by interpolating
`$KUBE_CONTEXT`/`$KUBE_NAMESPACE` directly into a DOUBLE-quoted shell
string (`--kube-context '$KUBE_CONTEXT'`). A value containing a single
quote (e.g. from `K8S_OBSERVER_CONTEXT`) could break out of that
quoting and run arbitrary shell syntax inside a container that has
both `--network host` and a read-write bind mount of this entire
repository. Confirmed exploitable with a minimal reproduction (a
payload ending `'; touch /tmp/marker; echo '` created the marker file
through the same double-quoted-interpolation pattern).

**After:** `KUBE_CONTEXT`/`KUBE_NAMESPACE` are passed as container
ENVIRONMENT VARIABLES (`-e KUBE_CONTEXT=...`, `-e KUBE_NAMESPACE=...`),
and the entire inner script is now SINGLE-quoted, referencing them
only as `"$KUBE_CONTEXT"`/`"$KUBE_NAMESPACE"` -- expanded by the INNER
shell from its own environment at runtime, never re-parsed as outer
shell syntax. The inline Python report-printing step was also moved
out of nested `bash -c` string literals entirely, into its own
tracked file (`scripts/_k8s_report_print.py`), removing a second,
unrelated source of fragile nested-quoting. A malformed/adversarial
context or namespace value still fails safely: it reaches `python -m
detectors analyze` as one inert literal argument, which
`KubernetesClient`'s own namespace-regex validation or an "unknown
context" `KubernetesConfigError` rejects outright -- never executed as
a command. Regression-tested, without Docker, by
`scripts/test-verify-kubernetes-observer-quoting.sh` (`make
test-verify-kubernetes-observer-quoting`): a static check that the
vulnerable interpolation pattern is gone, plus a dynamic reproduction
of the exact fixed quoting mechanism against single-quote,
semicolon, command-substitution, and newline payloads, proving none
of them execute. Re-verified against the real `reliability-lab`
cluster after the fix (section 8's same healthy-cluster result,
unchanged) to confirm the fix preserves read-only behavior.
