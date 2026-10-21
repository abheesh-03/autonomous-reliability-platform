# Phase 11B: unified autonomous failure discovery

Four labels are used throughout this document and must never be
confused: **IMPLEMENTED** (real code exists and runs), **TESTED
OFFLINE** (covered by `detectors/tests/`, synthetic data, no network),
**VERIFIED AGAINST REAL STACK** (actually run against the live Compose
stack this session, with real observed output -- see section 14), and
**PLANNED** (not built, explicitly future work). A capability is never
described with a stronger label than it has actually earned.

## 1. Actual architecture

A new, separate Python package, `detectors/`, alongside `catalog/`
(reused, never duplicated) and the existing services (untouched):

```
detectors/
  clients/       bounded, read-only Prometheus/Tempo/control-plane HTTP clients
  anomaly/       Gate B: statistical anomaly detectors + robust statistics
  traces/        Gate C: OTLP-JSON span parser + cycle detection
  dependencies/  Gate C: dependency-graph builder + candidate-propagation reasoning
  invariants/    Gate D: plugin registry + the real lifecycle-consistency checker
  correlation/   Gate E: deterministic multi-signal correlation engine
  pipeline/      Gate F: orchestrator (I/O) + findings (pure) + run (entry point)
  schemas/       pydantic contracts for every stage above
  cli/           Gate J: `python -m detectors {analyze,replay,verify}`
  tests/         101 tests, all against synthetic data (+5 new real,
                 evidence-backed detector-family entries now live in
                 catalog/registry/detector_families.py)
```

No file under `services/**`, `database/**`, `observability/**`,
`knowledge/**`, or `evals/**` was modified. `catalog/registry/
detector_families.py` and `catalog/tests/test_registry.py` were
updated (5 `implemented` flags flipped, evidence-backed -- section 16)
-- no other `catalog/**` file changed.

## 2. Detector inputs

| Input | Source | Client |
|---|---|---|
| HTTP request/error/latency metrics | Prometheus `/api/v1/query_range` | `clients/prometheus_client.py` |
| Distributed traces | Tempo `/api/search`, `/api/v2/traces/{id}` | `clients/tempo_client.py` |
| Incident + audit-event history | control-plane `/api/v1/incidents`, `/api/v1/incidents/{id}/events` | `clients/control_plane_client.py` |

## 3. Real Prometheus query contracts

Verified directly against `docker-compose.yml`'s own `OTEL_SERVICE_NAME`
entries and `services/investigator-service/src/investigator_service/
clients/prometheus.py` (the existing, already-production-reviewed
client) before writing any code: **only** checkout-service,
payment-service, inventory-service, and notification-service are
OTel-instrumented with `http_server_request_duration_seconds_count`/
`_bucket` -- control-plane, investigator-service, retrieval-service,
agent-runtime-service, tool-gateway, and web-console emit none of
these metrics. `ALLOWED_SERVICES` is exactly, and only, that verified
four-service set. Fixed query templates (service name is the only
substitution point, always checked against the allowlist first):

- `error_count_query(service)` -- 5xx count rate
- `total_count_query(service)` -- all-status count rate (the volume guard)
- `p95_latency_query(service)` -- `histogram_quantile(0.95, ...)`
- `collector_scrape_up_query()` / `collector_refused_telemetry_query()`
  -- the exact `up{job=~"otel-collector|..."}` /
  `otelcol_receiver_refused_*` queries already used by investigator-service

No arbitrary or LLM-supplied PromQL exists anywhere in this package.

## 4. Anomaly detection algorithm

Robust **median + median absolute deviation (MAD)**, a standard,
explainable statistic (Iglewicz & Hoaglin's modified z-score,
constant 0.6745) -- never an opaque ML model, never an LLM-decided
threshold. `error_rate_deviation` and `latency_deviation` additionally
require a **persistence fraction** (default 60% of observation samples
must exceed the z-score threshold, not merely the single highest one)
and a **minimum request-volume guard** (shared `total_count_query`
traffic, default 1 req/s) before any ratio/latency judgment is trusted.
`telemetry_pipeline_health` uses a deliberately different,
threshold+persistence method (never MAD) because `up` is an inherently
binary signal -- "choose methodology based on observed data shape" was
followed literally, not just as a phrase.

Four explicit `DetectionResult` values: `ANOMALY_DETECTED`,
`NO_ANOMALY`, `INSUFFICIENT_DATA` (too few samples or too little
traffic -- never conflated with "healthy"), `TELEMETRY_UNAVAILABLE`
(the query itself failed -- never evidence the app is unhealthy).

## 5. Baseline requirements

Default: 60 one-minute baseline samples (1 hour) + 10 observation
samples (10 minutes), both bounded by the client's own `MAX_LOOKBACK`
(24h) / `MAX_WINDOW` (6h). Fewer than `min_baseline_samples=12` or
`min_observation_samples=3` real (aligned, finite) samples ->
`INSUFFICIENT_DATA`, never a forced judgment on too little evidence.

## 6. Dependency graph construction

`detectors/traces/parser.py` extracts `SpanRecord`s (trace/span/parent
ids, service name, start/end time, error status) from Tempo's real
`GET /api/v2/traces/{traceID}` response, reusing the EXACT
base64-to-hex / resourceSpans-flattening logic already independently
proven in `scripts/verify-tempo-trace.py` (extended additively to also
read timing/status -- see section 7's own limitation). Cycle detection
is bounded (never hangs on a corrupted trace); a cyclic trace is
skipped entirely from graph-building, never partially trusted.
`detectors/dependencies/graph.py` builds `OBSERVED_DEPENDENCY` edges
**only** from real cross-service parent-child span pairs, aggregated
across however many parsed traces exhibit them -- never from an
imagined static service list, never from two services merely
co-occurring in the same window.

`detectors/dependencies/propagation.py` then proposes
`CANDIDATE_PROPAGATION`/`POSSIBLE_ROOT_CAUSE`-style explanations
(`PropagationPath.candidate_root_cause_service`, confidence always
< 0.95) **only** when a real observed edge exists AND (the
downstream/callee service is itself anomalous, OR the connecting spans
themselves recorded an error) -- an edge existing alone is never
sufficient. Orientation is explicit and was caught by testing, not
assumed: the SYMPTOM is expected on the upstream/calling service (e.g.
checkout-service), and the CANDIDATE root cause is the downstream/
callee it depends on (e.g. payment-service) -- matching the phase's
own "a failing downstream payment authorization may cause checkout to
fail" example exactly.

## 7. Distributed tracing limitations (stated honestly)

- Tempo search is a time + service-root search, never a guaranteed
  causal link to any specific incident -- a candidate trace, same
  caveat `investigator_service.clients.tempo` already documents.
- The `startTimeUnixNano`/`endTimeUnixNano`/`status.code` field
  extraction added in this phase (beyond what
  `scripts/verify-tempo-trace.py` itself reads) was **NOT**
  independently re-verified against a live Tempo response this round
  -- it is grounded in the documented, stable OTLP-JSON spec, but this
  is TESTED OFFLINE (synthetic fixtures), not VERIFIED AGAINST REAL
  STACK for these specific fields.
- A missing/absent `status` object is reported as `error=None`
  (unknown), never coerced to `False` -- confirmed by test.
- Duplicate span ids within one trace are not deduplicated (last one
  wins in internal lookups); confirmed not to crash, but not a
  claimed-correct resolution of the ambiguity.

## 8. Business invariant definitions

One real checker, `incident_lifecycle_event_consistency`
(`detectors/invariants/lifecycle_checker.py`), against control-plane's
real `GET /api/v1/incidents(/{id}/events)`. Event semantics were
inspected directly in `incident_repository.py`/`domain/lifecycle.py`
before writing anything (never assumed): `created` always
`(None, 'open')`; `observed` always `previous==new`; `status_transition`
always a real, matrix-legal change. `ALLOWED_TRANSITIONS`/
`VALID_STATUSES` are a deliberate, cited COPY of control-plane's own
constants (no shared-library import boundary exists) -- if control-
plane's matrix ever changes, this copy must be updated to match.

**Payment-service and inventory-service were evaluated and explicitly
excluded**: neither persists any queryable history (inventory-service's
own package docstring: "simulated inventory reservation... does not
persist anything"; payment-service returns only a synchronous
response, no stored ledger) -- Gate D's own instruction not to impose
an invented invariant was followed, not routed around with a synthetic
stand-in presented as real.

`detectors/invariants/framework.py` is a genuine plugin registry (one
async callable + one `InvariantDefinition` per invariant); a test
demonstrates a second, clearly-labeled SYNTHETIC-only example
(`synthetic_payment_authorization_contract_shape`) co-existing with
the real checker, proving the registry needs no engine rewrite to add
one.

## 9. Incident correlation logic

Deterministic union-find over `CorrelationInput` items, linked **only**
by: a shared trace id, a matching incident-source fingerprint, or an
overlapping time window **plus** (shared service identity OR an actual
`OBSERVED_DEPENDENCY` edge). Pure temporal proximity between unrelated
services never links anything (tested explicitly: two real, genuinely
independent anomalies in the same window with no edge/trace/fingerprint
stay in two separate findings -- see section 11). `correlation_group_id`
is a stable hash of the sorted member ids -- reproducible regardless of
input order (tested with `random.shuffle`). Root-cause language is
always "may share a common cause via X", never "proven"/"confirmed".

## 10. Unknown-incident handling

Every stage was built catalog-optional from the start, not bolted on:
`AnomalyDetectionResult`/`InvariantCheckReport`/`CorrelationGroup` carry
no scenario_id field at all; `FailureFinding` (reused from Phase 11A,
never duplicated) always sets `candidate_known_scenario_matches=[]`
and `unresolved_classification=True` for every Phase 11B finding --
confirmed structurally (`pipeline/findings.py` never constructs a
`CandidateScenarioMatch`, grepped and tested) and behaviorally (Gate G).

## 11. Evidence and provenance model

Every `AnomalyDetectionResult`/`FailureFinding`/`Observation` carries
its own `EvidenceProvenance` (source system, the exact query/
identifier, collected-at time). `FailureFinding.evidence_provenance`
and `Observation.measured_signals` trace every claim back to a real
Prometheus query or control-plane event id -- never a bare assertion.

## 12. Integration boundaries

- **Reuses** `catalog.schemas.finding.FailureFinding` and its six
  sub-models directly (Gate F's own instruction) -- no second,
  incompatible incident schema was invented.
- **Reuses** (honestly updates) `catalog.registry.detector_families`:
  5 of 19 starting families flipped to `implemented=True`, each
  change backed by real code + a real test file reference (section 16).
- **Does not** import, call, or modify `services/investigator-service`,
  `services/control-plane`, `services/tool-gateway`, or any other
  production service. The investigator's own citation validation and
  approval flow are completely untouched -- Phase 11B exposes no
  investigator-integration path in this round at all (PLANNED, not
  built; see section 19).
- **Does not** touch `catalog/coverage/verification.py`'s trust
  boundary -- confirmed by a structural test that `detectors/` never
  even imports that module.

## 13. Security restrictions (all verified by test, not just asserted)

Read-only, always: no database driver import anywhere in `detectors/`;
`ControlPlaneClient` only ever issues GET (tested by capturing every
real HTTP method sent); no `PATCH`/`POST`/`PUT`/`DELETE` method exists
on it; no tool-gateway client or URL exists; no `subprocess`/
`os.system`/`shell=True`/`eval`/`exec` anywhere in the package (AST-
walked, not just grepped); no `Authorization` header ever sent (tested
by capturing real request headers); no credential-shaped string
literal in source; every HTTP call target is exactly the caller-
supplied `base_url`, nothing else. `FailureFinding.remediation_proposals`
always empty in every finding Phase 11B produces. `RemediationProposal.
requires_human_approval`/`DiagnosticCheck.read_only` remain
`Literal[True]` (Phase 11A's own correction, unmodified, re-confirmed
by Phase 11B's tests still passing unchanged).

## 14. Test results

**193/193 tests pass** (92 Phase 11A `catalog/tests`, unmodified in
behavior except the 5 honest `implemented` flag updates + their
dependent test fixes; 101 new Phase 11B `detectors/tests`).

TESTED OFFLINE (all of the above): anomaly detectors (30), Prometheus
client (12), trace parser + dependency graph + propagation (17),
lifecycle invariant checker (11), invariant framework (3), correlation
engine (11), pipeline reality-check end-to-end (4 -- cascading
failure, healthy control, unrelated-failures control, self-check),
safety controls (16), CLI (6), coverage integration (3), catalog
registry/coverage updates (consolidated into the 92 catalog tests).

VERIFIED AGAINST REAL STACK (this session, read-only, against the
already-running Compose environment -- see
`scripts/verify-detectors-real-stack.sh`):
- Prometheus (`http://localhost:9090`): reachable, `up` query returned
  3 real series.
- Tempo (`http://localhost:3200`): reachable, 5 real candidate traces
  found in the prior 10 minutes.
- control-plane (`http://localhost:8000`): reachable, 121 real
  incidents on record.
- `python -m detectors analyze` ran end to end against all three real
  endpoints: 9 anomaly checks executed (8 `INSUFFICIENT_DATA`, 1
  `NO_ANOMALY` -- this quiet development environment does not
  currently have sustained traffic above the volume guard, which is
  the CORRECT, honest result, not a bug), the real
  `incident_lifecycle_event_consistency` invariant ran against all 121
  real incidents' real audit history and found **zero violations** (a
  genuine, meaningful confirmation of control-plane's own real audit
  trail), 0 dependency edges were observed in that specific 10-minute
  window (20 traces considered, honestly reported as zero rather than
  fabricated), and 0 findings were produced -- correctly, since nothing
  anomalous was observed.

This real-stack run is a single, point-in-time observation. It is
**not** claimed to prove sustained production coverage, and the
synthetic Gate G scenario is explicitly documented, in its own test
module, as never proving production coverage either.

## 15. CI checks

`.github/workflows/ci.yml`: 3 new steps inserted immediately after
Phase 11A's own offline gate, still before the expensive Docker/
Compose section (same placement rationale, same job,
`timeout-minutes: 90` unchanged). No existing step removed or
weakened. `Makefile`: `detectors-validate`, `detectors-replay`,
`verify-detectors-real-stack` (opt-in, documented as such).

## 16. Actual live capabilities

Exactly what section 14's real-stack run demonstrates, nothing more:
read-only connectivity + a real, meaningful invariant check against
121 real incidents. The anomaly/dependency/correlation algorithms ran
for real against real endpoints but found no anomalies in that
specific 10-minute window (an honest "nothing to report", not a
capability gap).

## 17. Offline-only capabilities

The full Gate G unknown-cascading-failure demonstration (detection +
dependency attribution + correlation + evidence-grounded hypotheses,
end to end) has only been exercised against synthetic data so far --
the mechanism is real and tested, but a genuinely anomalous real-stack
run has not yet been observed/captured this session.

## 18. False-positive limitations

- The MAD/z-score method is a real, principled statistic, but its
  specific thresholds (3.5 z-score, 60% persistence, 1 req/s volume
  floor) are initial, reviewed defaults, not empirically tuned against
  real incident history yet.
- `telemetry_pipeline_health`'s persistence fraction (50%) is likewise
  a reasonable starting default, not empirically validated.
- Correlation confidence scores (0.5-0.9) are fixed, reviewed weights,
  not a calibrated probability.
- The dependency graph only sees traces rooted at checkout-service
  (mirroring the existing Tempo client's own search root) -- a failure
  that never produces a checkout-rooted trace in the search window is
  invisible to the dependency/propagation stages (though NOT to the
  anomaly/invariant stages, which are per-service/per-source
  independent).

## 19. Future improvements (PLANNED, not built)

- Optional, explicitly opt-in, read-only investigator-service
  integration (consuming `FailureFinding`s) -- Gate F allowed this but
  it was not built this round; investigator's existing API/citation
  validation remains completely untouched either way.
- Calibrating thresholds against real incident history once enough of
  it exists.
- A resource-saturation/process-health/deployment-regression detector
  family (14 of 19 registry families remain honestly
  `implemented=False`).
- A real acceptance-pipeline or review-database verifier so
  `ACCEPTANCE_RESULT`/`REVIEWED_POLICY_IDENTIFIER` evidence kinds could
  ever leave `UNVERIFIABLE` in `catalog/coverage/verification.py`.
- A continuous/scheduled run mode (see section 20).

## 20. What Phase 11B does NOT implement

- **No continuous autonomous monitoring.** `python -m detectors
  analyze`/`replay` are manually (or CI-) triggered, point-in-time
  commands -- there is no daemon, scheduler, or background loop in
  this round. A single triggered run is explicitly NOT the same thing
  as continuous monitoring, and no part of this phase claims otherwise.
- No remediation execution of any kind (structurally impossible --
  section 13).
- No database migration, no change to `reliability.incidents` or any
  other schema.
- No modification to any existing service's business logic, API
  contract, or test suite.
- No investigator-service integration (planned, not built -- section 19).
- No payment/inventory business invariant (no real source exists --
  section 8).
- No resource-saturation, process-health, deployment-regression, DB-
  performance/integrity, concurrency, data-freshness, async-event,
  queue-saturation, auth-anomaly, upstream-dependency, configuration-
  credential, or monitoring-blind-spot detector -- these 14 registry
  families remain exactly what Phase 11A left them: honest capability
  descriptions, `implemented=False`.

## 21. Independent review correction round

Four correctness problems, reproduced directly against the actual
code, were fixed in one pass. 124/124 `detectors/tests` pass (up from
101); 216/216 combined with `catalog/tests` (92).

1. **First-ever HTTP 5xx spike was missed
   (`detectors/anomaly/detector.py`).** Root cause: `detect_error_rate_
   deviation` aligned ratio samples by iterating the ERROR series
   only. Prometheus's own semantics mean a label combination (5xx)
   that never fired produces NO data point, not a literal zero -- so
   a genuinely healthy, zero-error baseline (confirmed by real,
   positive total traffic) produced ZERO aligned samples and was
   misreported `INSUFFICIENT_DATA` instead of the true 0%-error
   baseline. **Fix:** the alignment loop now walks the TOTAL series
   (confirmed real traffic) and derives a zero-error observation only
   where total traffic is itself present and positive; missing total
   traffic is never treated as zero traffic (that timestamp
   contributes nothing, in either direction), and a wholly-unavailable
   total series still correctly falls through to
   `INSUFFICIENT_DATA`. `DataCompleteness.derived_zero_error_sample_
   count` makes every such derivation explicit, never silently folded
   into the sample counts with no trace of which were real vs.
   derived. 4 new tests: the exact reproduction (now `ANOMALY_
   DETECTED`), a negative control confirming a derived-zero baseline
   still requires real total traffic (not fabricated from nothing), a
   transient-spike-against-derived-baseline persistence-guard check,
   and a low-traffic-with-derived-baseline volume-guard check. The
   statistical detector itself was not replaced with a hardcoded
   threshold.

2. **Discontinuous incident history passed
   (`detectors/invariants/lifecycle_checker.py`).** Root cause: each
   event's `(previous_status, new_status)` pair was validated against
   the abstract transition matrix in isolation -- `investigating ->
   resolved` is individually legal, so a history with NO recorded
   transition into `investigating` at all (e.g. `created: None->open`
   immediately followed by `status_transition: investigating->
   resolved`) was reported `SATISFIED`. **Fix:** `_check_one_incident`
   now replays the ordered history while tracking `expected_status` as
   a running value; every `observed`/`status_transition` event's own
   `previous_status` must match it, not merely be some abstractly
   legal prior status. 6 new tests: the exact reproduction (now
   `VIOLATED`), a discontinuous `observed` event, a correct multi-step
   history, equal-timestamp continuity, a partial-history case
   (confirmed to stay `INSUFFICIENT_EVIDENCE`, never judged), and
   legitimate auto-resolution. This checker was already confirmed (in
   the prior round) to never compare a separately-fetched incident
   snapshot against the event history -- it uses only the one,
   already-fetched event list -- so no race-driven comparison exists
   to correct here.

3. **Weak correlation merged unrelated incidents
   (`detectors/correlation/engine.py`).** Root cause: "overlapping
   time window + shared service identity" and "a dependency edge
   exists somewhere in the graph" were both treated as sufficient to
   MERGE two findings. **Fix:** `correlate()` now returns `(groups,
   tentative_associations)` -- only a shared validated trace id, a
   matching exact fingerprint, or an `OBSERVED_DEPENDENCY` edge that
   itself carries incident-relevant evidence (an observed error, or a
   trace id it shares with one of the two findings) drives an actual
   merge; shared-service-only or an unevidenced structural edge is
   recorded as a `TentativeAssociation` (low, fixed confidence) and
   NEVER merged, and never transitively collapses an unrelated cluster
   (confirmed by a dedicated test: a weak pair stays separate even
   when one of its members is ALSO strongly linked to a third item).
   9 new/updated tests covering every negative control the correction
   named (same-service/same-window/unrelated-traces, different
   failure types, two independent downstream failures, an unevidenced
   shared dependency, weak-does-not-collapse-transitively), plus the
   existing genuine-cascade/reproducibility/no-fabricated-root-cause
   tests updated to use properly EVIDENCED fixtures rather than merely
   structurally-present ones. `detectors/pipeline/orchestrator.py`,
   `pipeline/run.py`, and `cli/commands.py` were updated to carry the
   new `tentative_associations` output through end to end (visible in
   both the JSON report and the human-readable summary). Correlation
   was not disabled to pass the negative controls -- the Gate G
   cascading-failure demonstration (section 14/17) still produces a
   genuine, strongly-evidenced merged group, confirmed unchanged by
   this fix.

4. **Malformed or mismatched Tempo traces
   (`detectors/traces/parser.py`).** Two root causes: (A) `rs.get(
   "resource", {})` returned the ACTUAL non-dict value when the key
   existed-but-held-a-string (the `{}` default is only used when the
   key is absent, not when it is a wrong type), so calling `.get(
   "attributes", ...)` on that string raised `AttributeError`. (B) no
   span was ever checked against the trace id it was actually
   requested for, so a response returning spans belonging to a
   DIFFERENT trace id was silently trusted as evidence for the
   requested one. **Fix:** every nested shape (`resource`, `value`,
   `scopeSpans`, `spans`, each individual attribute/span) is now
   explicitly type-checked before use, with a final per-span `try/
   except` as an absolute backstop (never allowed to raise out of this
   module); every span's own decoded `traceId` is compared against the
   requested trace id, and a mismatch is rejected and counted in the
   new `TraceParseResult.trace_id_mismatch_count` field, never trusted
   as evidence (confirmed: zero dependency edges can ever be built
   from a trace-id-mismatched span). 8 new tests covering both exact
   reproductions plus every named negative control (malformed
   service.name value, wrong nested list/object types, invalid
   base64/length ids, partially-valid-trace, valid-multi-service
   non-regression, and pipeline continuation when one trace in a batch
   is malformed). Fixing this ALSO surfaced and corrected a latent bug
   in the Phase 11B test suite itself: `test_unrelated_trace_in_same_
   window_contributes_independent_edges_only` had been requesting
   `parse_trace_detail("trace-1", ...)`/`"trace-2"` while every span's
   own embedded `traceId` used the same hardcoded test constant
   regardless -- an inconsistency the new mismatch check correctly
   caught; the fixture now uses two distinct, consistently-embedded
   trace ids.

**Scope discipline:** all four fixes are confined to `detectors/**`
(plus this doc); no file under `services/**`, `database/**`,
`observability/**`, `knowledge/**`, `evals/**`, `catalog/source/**`,
or `docker-compose.yml` was touched. Phase 10 (`scripts/verify-evals-
offline.sh`, 97/97) and Phase 11A (`catalog/tests`, 92/92) were
re-confirmed unaffected.

## 22. Final evidence-integrity correction round

Two remaining issues, reproduced directly, were fixed. 129/129
`detectors/tests` pass (up from 124); 221/221 combined with
`catalog/tests` (92).

**Issue A (`detectors/correlation/engine.py`):** a dependency edge's
generic `error_observed=True` was sufficient, on its own, to strongly
correlate two findings, even when the edge's own evidence belonged to
an unrelated third trace. Fixed: `_edge_has_incident_relevant_evidence`
now requires the edge's `related_trace_ids` to be attributable to
**both** findings' own trace ids (never a one-sided match, never
`error_observed` alone). A direct consequence, confirmed correct: real
aggregate Prometheus anomalies (which the orchestrator never attaches
trace ids to) can no longer reach a strong merge via a dependency edge
at all -- their dependency association is honestly reported as
`TentativeAssociation` instead (updated in `test_pipeline_reality_
check.py` and `test_cli.py`'s fixture-based tests, preserving every
other assertion -- findings, hypotheses, measurements, zero catalog
matches, no remediation -- unchanged). 9 new/updated correlation tests.

**Issue B (`detectors/invariants/lifecycle_checker.py`):** one
complete, clean incident alongside one genuinely incomplete incident
in the same request produced `SATISFIED`, silently dropping the
unresolved incomplete-history gap. Fixed: `SATISFIED` now requires
`incomplete_count == 0` AND zero violations; a mix of complete-clean +
incomplete now reports `INSUFFICIENT_EVIDENCE` naming both counts
explicitly; a mix of complete-violated + incomplete still reports
`VIOLATED`, with the incomplete gap appended to the explanation rather
than lost. 4 new tests (one-valid+one-incomplete, one-violated+one-
incomplete, all-complete-valid, all-incomplete).

Scope: both fixes confined to `detectors/**` plus this doc; Phase 10
(97/97) and Phase 11A (92/92) re-confirmed unaffected; no live-stack
check was re-run this round (no fault injection, no Compose/volume
changes).
