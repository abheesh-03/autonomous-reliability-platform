# Phase 4 — Controlled Failure Injection and Deterministic Incident Simulation

Phase 4 adds a safe, repeatable, opt-in capability to deliberately
break one real dependency of the real Docker Compose checkout
application, observe the real symptom, verify the expected safe
behavior, restore the environment, and — for the payment-service
scenario — prove the complete existing Phase 2/3 platform reacts to
it correctly end to end.

This phase does **not** rebuild anything from Phase 3A–3F (incident
persistence, the control-plane API, Alertmanager ingestion, the
lifecycle state machine, or the audit trail). It reuses all of it
unchanged, and reuses `scripts/verify-alerting.py` and
`scripts/verify-ingestion.py` from Phase 2B.4/3C exactly as they
already existed — neither file was modified.

## 1. Purpose and architecture

| Piece | File | Role |
|---|---|---|
| Scenario runner | `scripts/simulate-failure.sh` | All scenario logic: safety allowlisting, fault injection, assertions, restoration, reporting. Usable directly by a developer. |
| Focused tests | `scripts/test-simulate-failure.sh` | Scenario-selection/safety/restoration-behavior tests. No Docker required. |
| Real acceptance gate | `scripts/verify-failure-simulation.sh` | Thin CI/Make-facing wrapper: prepares prerequisites, then runs both scenarios via `simulate-failure.sh`. |
| Downstream timeout fix | `services/checkout-service/.../config/DownstreamRestClientCustomizer.java` | Bounds every downstream RestClient's connect/read timeout — see §6, a real gap this phase's own testing discovered. |

`simulate-failure.sh` defines its functions unconditionally but only
*runs* the scenario when executed directly (guarded by a
`[[ "${BASH_SOURCE[0]}" == "${0}" ]]` check at the bottom) — this is
what lets the test script `source` it and unit-test
`restore_target()`/the allowlist logic without touching Docker.

No new database schema, no new control-plane endpoint, and no change
to `database/migrations/V1`–`V4` were needed or added.

## 2. Supported scenarios

### A. `payment-outage`

1. Establish a healthy baseline (all four application services
   healthy; one real `POST /checkouts` succeeds with `status=COMPLETED`).
2. *(`--full-acceptance` only)* confirm `CheckoutServerErrors` is
   genuinely `inactive` first (via `scripts/verify-alerting.py state`,
   never assumed), and capture the freshness timestamp used later —
   both **before** the fault below is induced, so a pre-existing
   pending/firing alert can never be mistaken for proof of this run.
3. Stop `payment-service` (`docker compose stop payment-service`).
4. Issue a real checkout request; assert HTTP `502` with body
   `{"error": "downstream_failure", "service": "payment-service", "message": "Downstream service request failed"}`.
5. *(`--full-acceptance` only, see §4)* sustain real failing traffic
   until the real `CheckoutServerErrors` Prometheus rule fires —
   **every single attempt** in that loop re-asserts the exact same
   502/`downstream_failure`/`service=payment-service` contract, not
   just the first one, and aborts immediately if any attempt ever
   violates it — and confirm a real, persisted incident via the real
   Alertmanager webhook.
6. Restore `payment-service`; verify it is healthy again.
7. Issue a fresh checkout request; assert HTTP `200` /
   `status=COMPLETED`.
8. *(`--full-acceptance` only)* wait for real recovery and confirm
   genuine automatic resolution with a correctly-attributed audit
   trail.

### B. `inventory-outage`

1, 3. Same baseline + stop, targeting `inventory-service` (step 2's
   pre-fault alert check is specific to `payment-outage
   --full-acceptance` and never runs here).
4. Snapshot `payment-service`'s and `notification-service`'s own
   Prometheus request counters (after a settle wait — see §7).
5. Issue a real checkout request; assert HTTP `502` with
   `service: "inventory-service"`.
6. Assert `payment-service`'s counter **increased** (the payment step
   genuinely completed before the failure).
7. Assert `notification-service`'s counter stays **unchanged across a
   full, repeated post-failure observation window** (5 observations,
   5s apart — not a single immediate check; see §7's rationale) — the
   orchestration short-circuited before ever reaching notification,
   proven from the outside via real telemetry, not by reading
   checkout-service's internal call order.
8–9. Restore and verify a fresh checkout succeeds, same as scenario A.

`inventory-outage` never accepts `--full-acceptance` — it does not
need, and is refused if given, a second expensive full-alert
simulation (see §4).

## 3. Exact safety boundaries

- **Allowlisted targets only.** The scenario name is matched against
  exactly two `case` arms (`payment-outage`, `inventory-outage`); any
  other value is refused *before* any Docker or network call, with a
  redundant, explicit `postgres`-is-never-a-target guard on top. There
  is no code path that derives a Compose service name from arbitrary
  input.
- **Only application services, never infrastructure.** The two
  allowlisted targets are `payment-service` and `inventory-service`.
  `postgres`, `otel-collector`, and every other Compose service are
  never touched by this script.
- **No volumes, ever.** Nothing in this phase issues `docker compose
  down -v`, `docker volume rm`, or any equivalent. Only `stop`/`start`
  against two application containers.
- **No deleted history.** No incident row and no
  `reliability.incident_events` row is ever deleted by anything in
  this phase (and the append-only triggers from Phase 3E would reject
  an attempt regardless).
- **Restoration on every exit path this shell can observe — stated
  honestly, not oversold.** `NEEDS_RESTORE` is set `true` **before**
  `docker compose stop` is even issued, not after it returns, so a
  stop that fails partway through or is interrupted mid-command is
  still treated as needing cleanup (`docker compose start` against an
  unaffected or already-running container is a safe, idempotent
  no-op/recovery either way). Exactly ONE place ever calls
  `restore_target`: the single `EXIT` trap (`on_exit`). The `INT`/`TERM`
  traps only set the conventional exit code and `exit` — that `exit`
  itself triggers the `EXIT` trap, so cleanup never runs twice (no
  recursive cleanup) and a signal is never silently swallowed.
  `NEEDS_RESTORE` is cleared **only** once `wait_healthy` actually
  confirms the dependency healthy again — never merely because `start`
  was issued. If health can never be confirmed, `restore_target`
  returns failure, `on_exit` reports it explicitly, and forces a
  nonzero exit status even if the scenario had otherwise reached a
  clean one — a run is never reported as `PASS`, and the process never
  exits `0`, while a dependency is left down. If the scenario was
  already failing, that original (nonzero) exit status is preserved
  rather than overwritten.
  **Honestly out of scope, not a gap in the implementation:** `SIGKILL`
  (`kill -9`) and power loss cannot be trapped by any shell script —
  this script makes no claim otherwise. If either happens while a
  dependency is stopped, it stays stopped until a human runs
  `docker compose start <service>` manually.
- **Bounded timeouts everywhere.** Every wait loop is a bounded `seq
  1 N` retry with a fixed sleep — never an unbounded `while true`.
  Every `curl` call (including `prom_count`'s Prometheus queries) has
  an explicit `--connect-timeout`/`--max-time`.
- **The full-acceptance alert rule cannot be redirected by the
  environment.** `payment-outage --full-acceptance` always targets
  `CheckoutServerErrors` via a `readonly` shell constant
  (`PAYMENT_OUTAGE_ALERT_NAME`), not an environment-overridable
  variable — unlike `CHECKOUT_URL`/`PROMETHEUS_URL`/etc., there is no
  way to point this specific check at a different, unrelated alert.
- **No credentials printed.** Every endpoint this script touches
  (checkout-service, Prometheus, Alertmanager, and control-plane's
  existing unauthenticated `GET` API via `scripts/verify-ingestion.py`)
  is unauthenticated or already read-only/public; nothing here needs,
  reads, or prints a Bearer token.
- **No narrow privileged mechanism.** Fault injection is exactly
  `docker compose stop <allowlisted-service>` against this
  repository's own Compose project — no chaos-engineering sidecar, no
  `tc`/`iptables` network manipulation, no privileged container, and
  no HTTP endpoint that could be reached from outside this script.
- **Normal behavior is unaffected when idle — with one stated
  exception.** This phase adds no new always-on component, middleware,
  or background process. The one change to a running service's
  *behavior* is the connect/read timeout fix in §6/§8: it correctly
  turns an already-broken downstream call's unbounded hang into a
  bounded, fast failure, and has no effect on a request that completes
  within the new 5s read timeout. It is **not** limited to
  already-broken calls, though — a downstream response that is merely
  unusually slow (but would otherwise have succeeded) now also fails
  with a `502` if it takes longer than 5s. See §8 for the full,
  honest framing of this trade-off.

## 4. How to run each scenario

```bash
make db-up && make db-migrate   # once, if the stack isn't already up

make simulate-payment-outage                      # basic (fast, ~30s)
FULL_ACCEPTANCE=true make simulate-payment-outage  # full chain (~8-9 min, see §7)

make simulate-inventory-outage                     # basic only

make test-failure-simulation      # focused tests, no Docker needed
make verify-failure-simulation    # the full CI-equivalent acceptance gate
```

Or directly:

```bash
./scripts/simulate-failure.sh payment-outage [--full-acceptance]
./scripts/simulate-failure.sh inventory-outage
```

Every run prints a final `SUMMARY` block: scenario selected, healthy
baseline, fault applied, the actual observed failure, recovery
performed, and (for `--full-acceptance`) the real incident id(s) and
Alertmanager fingerprint(s) involved. Nothing is reported as
successful unless it was actually observed — every line in that
summary corresponds to an assertion that already passed earlier in
the same run; the script `fail()`s and exits before ever reaching it
otherwise.

## 5. Expected failure and recovery behavior

| Step | Expected result |
|---|---|
| Baseline checkout | `200`, `status=COMPLETED` |
| `payment-outage --full-acceptance` pre-fault check | `CheckoutServerErrors` state is `inactive` (asserted, not assumed) — a run started while a prior run's alert is still decaying refuses to proceed with ambiguous evidence rather than silently reusing it |
| Checkout during `payment-outage` | `502`, `service=payment-service` — asserted on **every** attempt during the sustained-traffic loop, not just the first |
| Checkout during `inventory-outage` | `502`, `service=inventory-service`; payment's own counter increased; notification's own counter stays unchanged across a full, repeated observation window (not one immediate check) |
| Fresh checkout after restoration | `200`, `status=COMPLETED` |
| `payment-outage --full-acceptance`: traffic sustained | Prometheus `CheckoutServerErrors` reaches `firing` (observed locally after ~130s of sustained, individually-verified real 5xx traffic — the rule's `for: 2m` plus scrape/evaluation lag) |
| `payment-outage --full-acceptance`: after firing | A real `reliability.incidents` row, matched by Alertmanager's own fingerprint, with a `created` audit event attributed to `alertmanager` |
| `payment-outage --full-acceptance`: after restoration | `CheckoutServerErrors` returns to `inactive` (observed locally after ~4.5 minutes — see §7) and the *same* incident resolves with a `status_transition` audit event, also attributed to `alertmanager` |
| Dependency cannot be verified restored (any scenario) | The run exits nonzero and prints an explicit `FAIL: cleanup could not verify ... healthy` — never reported as `PASS`, regardless of how far the scenario itself had otherwise progressed |

## 6. How real incidents are generated

Exactly the same real mechanism Phase 3C/3D/3E already proved for
`TelemetryPipelineUnavailable` (`scripts/verify-alert-lifecycle.sh`),
reused unmodified here for a *different* alert rule and a *different*
real failure:

1. `simulate-failure.sh` stops `payment-service` — a genuine Docker
   Compose container stop, not a simulated condition.
2. Real `POST /checkouts` requests against the still-running
   checkout-service genuinely fail with `502` (its real
   `DownstreamServiceException` -> `CheckoutExceptionHandler` path),
   producing genuine `http_response_status_code="502"` metric samples.
3. Prometheus's existing `CheckoutServerErrors` rule
   (`observability/prometheus/rules/alerts.yml`, unmodified — see §7
   on why its threshold/`for:` was never touched) evaluates this real
   telemetry and transitions to `firing`.
4. Alertmanager receives it from Prometheus and delivers its own real
   webhook to control-plane's existing
   `POST /internal/v1/alertmanager/webhook` — the exact same endpoint
   Phase 3C built, authenticated the exact same way.
5. Control-plane's existing ingestion path atomically upserts a real
   `reliability.incidents` row and records a real, append-only
   `created` audit event — the exact Phase 3A/3E code, untouched.
6. `scripts/verify-ingestion.py incident-from-alert` (unmodified, Phase
   3C/3F) independently confirms this by reading Prometheus's and
   Alertmanager's own APIs and cross-checking the persisted incident —
   never by inserting anything itself.
7. After `payment-service` is restored and real traffic resumes
   succeeding, the alert naturally clears and Alertmanager's own real
   resolved webhook drives the same existing automatic-resolution path
   Phase 3D built, producing a resolving audit event. `confirm-resolved`
   (unmodified) confirms this the same way.

No step anywhere inserts a SQL row directly or POSTs a synthetic
alert to Alertmanager — every incident this phase produces is a
byproduct of a genuinely broken application reacting to genuinely
failing real HTTP traffic.

## 7. Verification evidence

A full local run of `make verify-failure-simulation` (2026-10-03),
after the restoration-safety, sustained-traffic, and short-circuit
corrections below, passed end to end:

- `payment-outage --full-acceptance`: the pre-fault check confirmed
  `CheckoutServerErrors` genuinely `inactive` before the fault was
  induced; `CheckoutServerErrors` reached `firing` after 26 of 40
  bounded polling attempts (~130s of sustained real 5xx traffic, with
  every single attempt re-verified as a genuine
  502/`downstream_failure`/`service=payment-service` response); the
  real webhook delivery produced a persisted incident matched to
  Alertmanager's real fingerprint (`f5429f5dc378f6c8`) within 3
  attempts; after restoring `payment-service` (verified healthy),
  recovery (`CheckoutServerErrors` back to `inactive`) took 56 of 90
  bounded attempts (~4.9 minutes — see the note on `rate()` decay
  below); the same incident id resolved with a correctly-attributed
  `created`→`status_transition(alertmanager, resolved)` audit trail.
- `inventory-outage`: payment's counter genuinely increased (`2.0 ->
  3.0`), notification's counter was observed unchanged across all 5
  repeated post-failure observations (`8.0` throughout), and a fresh
  checkout succeeded after restoration.
- A prior run in the same local session left `CheckoutServerErrors` in
  `pending`/`firing` for several minutes afterward (the real `rate()`
  decay described below, triggered by that run's own deliberate 5xx
  traffic) — the new pre-fault `inactive` check correctly refused to
  start a fresh full-acceptance run on top of that ambiguous state
  until it had genuinely decayed, rather than silently proceeding.
  This is the check working as designed, not a flake.

**Why recovery takes several real minutes, and why that was not
"fixed":** `CheckoutServerErrors`'s expression is
`sum(rate(http_server_request_duration_seconds_count{...,
http_response_status_code=~"5.."}[5m])) > 0`. `rate()` over a 5-minute
window does not drop to exactly zero the instant failing requests
stop — it only reaches zero once the last failing sample ages out of
that trailing 5-minute window. This is a deliberate real characteristic
of the *existing*, already-reviewed alert rule, not a flaw in the
simulation. The instructions for this phase were explicit that the
threshold must never be altered merely to make a test faster, so the
recovery-wait loop is simply sized generously (90 attempts × 5s = up
to 7.5 minutes of budget) rather than the rule being changed.

## 8. Known limitations

- **Real wall-clock cost.** The full-acceptance run takes roughly
  8–9 minutes end to end, dominated by `CheckoutServerErrors`'s real
  `for: 2m` firing delay and, especially, its real `[5m]` `rate()`
  recovery decay. This is inherent to proving the real, unmodified
  alert rule, not a flaw to be optimized away; the CI job's timeout
  was raised accordingly.
- **Repeated, not infinite, observation — an honest, bounded
  guarantee.** `inventory-outage`'s notification check now observes
  the counter 5 times, 5s apart (sized from this stack's real 5s OTel
  export + 15s Prometheus scrape cycle), asserting "still unchanged"
  on every observation rather than checking once immediately. This
  proves notification stayed uncalled for that ~25s window, which is a
  materially stronger guarantee than a single snapshot — but it is
  still a bounded window, not a claim that notification can never be
  called at any point in the future. Both this check and the
  payment-increase check assume no *other* real traffic is hitting
  those two services concurrently during the test window (a reasonable
  assumption for CI and for a developer not simultaneously
  load-testing the same stack by hand).
- **A fixed settle delay, not a perfect synchronization.** The 20s
  wait before `inventory-outage`'s "before" snapshot (sized from this
  stack's own 5s OTel export interval + 15s Prometheus scrape interval
  plus margin) is a bounded heuristic, not a guarantee — an unusually
  slow CI runner could theoretically still race it. It has not been
  observed to fail in any local or expected CI run.
- **The full-acceptance pre-fault check adds a real precondition.**
  Running `payment-outage --full-acceptance` twice in quick succession
  (or shortly after any other test that generates real checkout 5xx
  traffic) can now correctly refuse to start until
  `CheckoutServerErrors` has genuinely decayed back to `inactive` —
  observed locally to take several minutes after an unrelated prior
  run's traffic. This is intentional (see §7) and not something a
  future change should "fix" by weakening the check.
- **Two scenarios, not every dependency.** `notification-service` has
  no outage scenario (the orchestration already always calls it last,
  so an outage there cannot demonstrate short-circuiting the way
  inventory's can) and `otel-collector`/`postgres` outages are
  deliberately out of this phase's scope (already covered by Phase
  2B.4's own Collector-outage test; postgres is explicitly never a
  target per the safety boundaries in §3).
- **The downstream timeout fix is a real, if narrowly-scoped,
  application change — and it changes more than the outage case.**
  Phase 4's own testing discovered that checkout-service's downstream
  `RestClient`s had no explicit connect/read timeout: a dependency
  stopped *while* a keep-alive connection to it was already pooled
  left requests hanging (measured: still unresolved past 90 seconds)
  rather than failing fast, because no `RST` is ever sent for an
  already-established connection whose peer simply vanishes. A fresh
  connection attempt (no pooled connection to reuse) already failed in
  well under 100ms, so this was specifically a connection-reuse gap.
  Fixed with one new `RestClientCustomizer` bean
  (`DownstreamRestClientCustomizer`, 3s connect / 5s read timeout),
  applied automatically to all three downstream clients — no change to
  `PaymentClient`, `InventoryClient`, or `NotificationClient`
  themselves. **Stated honestly:** the 5s read timeout is not
  scoped to "unavailable" dependencies only — it now also applies to
  any downstream call that is merely *unusually slow but otherwise
  healthy* (e.g. a genuinely overloaded `payment-service` taking
  longer than 5s to respond would now also receive a `502` it would
  not have received before this fix). This is the correct, intended
  behavior for a production-style timeout (an unbounded wait is never
  actually safe), but it is a real behavior change beyond the narrow
  "stopped dependency" case this phase set out to test, and is
  reported here rather than left implicit. This is exactly the kind of
  real reliability gap controlled failure injection exists to surface;
  it is reported here rather than left undiscovered.
- **No chaos engineering, AI investigation, remediation, approval
  workflow, frontend, or deployment infrastructure** — all explicitly
  out of scope for this phase; see README.md's Phase 4 entry for the
  full implemented-vs-planned split.
