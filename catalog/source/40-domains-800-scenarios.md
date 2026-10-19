# Autonomous Reliability Platform — 40 Domains / 800 Production Failure Scenarios

**Purpose:** Seed an incident taxonomy and detection/remediation design for cross-industry services. These are plausible failure hypotheses, not a complete list of all possible production failures.

**Use safely:** Instrument first; run synthetic fault-injection and chaos tests only in authorized environments. Start AI agents in read-only diagnostic mode. Require approval for money movement, destructive data changes, privilege changes, security incidents, legal/compliance determinations, physical controls, and patient or public safety.

**Field guide:** detection signal = observable failure pattern; telemetry/test = instrumentable evidence; likely causes = hypotheses, not conclusions; automation policy = baseline approval gate; verification = independent post-action check. Severity values are starting defaults, to be calibrated to impact and blast radius.

## Shared reliability foundation

Besides these domain cases, implement cross-cutting checks for availability, latency, saturation, errors, distributed traces, queue age/dead-letter queues, duplicate messages, idempotency, DB transaction invariants, backup restore, schema compatibility, feature flags, permissions, data freshness, and secret rotation. A domain checklist alone cannot detect unknown failures.

## FinTech

### D01-F01 — Duplicate payment capture

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: duplicate payment capture.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck duplicate payment capture against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F02 — Payment authorization timeout after issuer approval

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: payment authorization timeout after issuer approval.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payment authorization timeout after issuer approval against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F03 — Ledger debit-credit imbalance

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: ledger debit-credit imbalance.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck ledger debit-credit imbalance against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F04 — Webhook delivered out of order

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: webhook delivered out of order.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck webhook delivered out of order against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F05 — Idempotency key collision or expiry

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: idempotency key collision or expiry.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck idempotency key collision or expiry against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F06 — Refund issued twice

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: refund issued twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck refund issued twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F07 — Payment gateway credential rotation failure

**Class:** Authentication / credentials · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: payment gateway credential rotation failure.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payment gateway credential rotation failure against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F08 — FX rate feed stale during conversion

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: fx rate feed stale during conversion.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck fx rate feed stale during conversion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F09 — Card tokenization service unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: card tokenization service unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck card tokenization service unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F10 — Merchant settlement batch partially committed

**Class:** Scheduling / batch windows · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: merchant settlement batch partially committed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck merchant settlement batch partially committed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F11 — Risk rules incorrectly decline legitimate transactions

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: risk rules incorrectly decline legitimate transactions.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck risk rules incorrectly decline legitimate transactions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F12 — Chargeback event missed

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: chargeback event missed.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck chargeback event missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F13 — Wallet balance cache stale

**Class:** Staleness / cache · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: wallet balance cache stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck wallet balance cache stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F14 — 3-D Secure callback never received

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: 3-d secure callback never received.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck 3-d secure callback never received against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F15 — Payout destination bank validation error

**Class:** Rollout / compatibility · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: payout destination bank validation error.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payout destination bank validation error against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F16 — Recurring subscription charged after cancellation

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: recurring subscription charged after cancellation.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck recurring subscription charged after cancellation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F17 — Fraud model inference latency spike

**Class:** Latency / capacity · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: fraud model inference latency spike.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck fraud model inference latency spike against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F18 — ACH return file not ingested

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: ach return file not ingested.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck ach return file not ingested against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F19 — Card network duplicate clearing record

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: card network duplicate clearing record.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck card network duplicate clearing record against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D01-F20 — PCI-sensitive fields leaked into logs

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: pci-sensitive fields leaked into logs.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected fintech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck pci-sensitive fields leaked into logs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Banking

### D02-F01 — Core banking ledger reconciliation mismatch

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: core banking ledger reconciliation mismatch.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck core banking ledger reconciliation mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F02 — ATM withdrawal debited without cash dispense

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: atm withdrawal debited without cash dispense.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck atm withdrawal debited without cash dispense against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F03 — Deposit posted to wrong account

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: deposit posted to wrong account.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck deposit posted to wrong account against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F04 — Interest accrual calculation drift

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: interest accrual calculation drift.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck interest accrual calculation drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F05 — Loan repayment applied twice

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: loan repayment applied twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck loan repayment applied twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F06 — Overdraft fee assessed incorrectly

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: overdraft fee assessed incorrectly.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck overdraft fee assessed incorrectly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F07 — Account hold not released

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: account hold not released.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck account hold not released against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F08 — Interbank transfer stuck in pending

**Class:** External dependency / integration · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: interbank transfer stuck in pending.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck interbank transfer stuck in pending against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F09 — Know-your-customer screening backlog

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: know-your-customer screening backlog.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck know-your-customer screening backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F10 — Dormant account reactivated without controls

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: dormant account reactivated without controls.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck dormant account reactivated without controls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F11 — Branch transaction sync conflict

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: branch transaction sync conflict.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck branch transaction sync conflict against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F12 — End-of-day batch misses cutoff

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: end-of-day batch misses cutoff.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck end-of-day batch misses cutoff against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F13 — Statement generation omits transactions

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: statement generation omits transactions.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck statement generation omits transactions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F14 — Account balance differs across channels

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: account balance differs across channels.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck account balance differs across channels against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F15 — Wire payment sanctions screening fails open

**Class:** Rollout / compatibility · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: wire payment sanctions screening fails open.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck wire payment sanctions screening fails open against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F16 — Cheque image processing corrupts amount

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: cheque image processing corrupts amount.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck cheque image processing corrupts amount against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F17 — Scheduled payment executes on bank holiday

**Class:** Scheduling / batch windows · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: scheduled payment executes on bank holiday.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck scheduled payment executes on bank holiday against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F18 — Multi-factor authentication outage

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: multi-factor authentication outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck multi-factor authentication outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F19 — Rate change not propagated to loan engine

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: rate change not propagated to loan engine.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck rate change not propagated to loan engine against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D02-F20 — Sensitive account data exposed via API

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: sensitive account data exposed via api.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck sensitive account data exposed via api against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Investment Banking

### D03-F01 — Market data feed freezes

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: market data feed freezes.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck market data feed freezes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F02 — Order execution duplicate after retry

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: order execution duplicate after retry.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck order execution duplicate after retry against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F03 — Trade capture missing fill

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: trade capture missing fill.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck trade capture missing fill against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F04 — Position limits calculated from stale positions

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: position limits calculated from stale positions.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck position limits calculated from stale positions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F05 — Pricing model outputs anomalous valuation

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: pricing model outputs anomalous valuation.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck pricing model outputs anomalous valuation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F06 — Margin calls generated incorrectly

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: margin calls generated incorrectly.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck margin calls generated incorrectly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F07 — Corporate actions adjustment omitted

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: corporate actions adjustment omitted.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck corporate actions adjustment omitted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F08 — Settlement instruction fails matching

**Class:** External dependency / integration · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: settlement instruction fails matching.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck settlement instruction fails matching against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F09 — Trading gateway latency spikes

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: trading gateway latency spikes.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck trading gateway latency spikes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F10 — Market risk VaR job misses deadline

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: market risk var job misses deadline.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck market risk var job misses deadline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F11 — Reference instrument mapping collision

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: reference instrument mapping collision.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck reference instrument mapping collision against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F12 — Trading halt not honored by order router

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: trading halt not honored by order router.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck trading halt not honored by order router against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F13 — Allocation splits exceed executed quantity

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: allocation splits exceed executed quantity.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck allocation splits exceed executed quantity against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F14 — Portfolio P&L differs from general ledger

**Class:** Model / rules drift · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: portfolio p&l differs from general ledger.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck portfolio p&l differs from general ledger against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F15 — Derivative lifecycle event skipped

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: derivative lifecycle event skipped.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck derivative lifecycle event skipped against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F16 — Collateral inventory double-pledged

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: collateral inventory double-pledged.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck collateral inventory double-pledged against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F17 — Best-execution surveillance alert backlog

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: best-execution surveillance alert backlog.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck best-execution surveillance alert backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F18 — Exchange connectivity flaps during auction

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: exchange connectivity flaps during auction.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck exchange connectivity flaps during auction against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F19 — Trade cancellation not propagated downstream

**Class:** Audit / compliance · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: trade cancellation not propagated downstream.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck trade cancellation not propagated downstream against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D03-F20 — Regulatory transaction report rejected

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: regulatory transaction report rejected.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected investment banking entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck regulatory transaction report rejected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## InsurTech

### D04-F01 — Claims adjudication double-pays claim

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: claims adjudication double-pays claim.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck claims adjudication double-pays claim against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F02 — Policy premium rating uses wrong territory

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: policy premium rating uses wrong territory.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck policy premium rating uses wrong territory against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F03 — Coverage eligibility wrongly denied

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: coverage eligibility wrongly denied.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck coverage eligibility wrongly denied against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F04 — Policy renewal job silently skips customers

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: policy renewal job silently skips customers.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck policy renewal job silently skips customers against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F05 — Claims document OCR corrupts field

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: claims document ocr corrupts field.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck claims document ocr corrupts field against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F06 — Fraud scoring flags legitimate claims

**Class:** Latency / capacity · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: fraud scoring flags legitimate claims.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck fraud scoring flags legitimate claims against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F07 — Provider network data outdated

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: provider network data outdated.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck provider network data outdated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F08 — Reinsurance bordereaux export mismatched

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: reinsurance bordereaux export mismatched.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck reinsurance bordereaux export mismatched against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F09 — Claims reserve calculations drift

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: claims reserve calculations drift.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck claims reserve calculations drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F10 — Policy cancellation delayed after request

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: policy cancellation delayed after request.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck policy cancellation delayed after request against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F11 — Accident timestamp falls outside wrong timezone

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: accident timestamp falls outside wrong timezone.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck accident timestamp falls outside wrong timezone against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F12 — Third-party repair estimate feed unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: third-party repair estimate feed unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck third-party repair estimate feed unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F13 — Customer deductible applied twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: customer deductible applied twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck customer deductible applied twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F14 — Underwriting rule version mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: underwriting rule version mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck underwriting rule version mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F15 — Premium collection retries double-charge

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: premium collection retries double-charge.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck premium collection retries double-charge against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F16 — Regulatory disclosure missing from document

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: regulatory disclosure missing from document.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck regulatory disclosure missing from document against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F17 — Claims adjuster work queue starves cases

**Class:** Location / time / units · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: claims adjuster work queue starves cases.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck claims adjuster work queue starves cases against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F18 — Catastrophe claims traffic overwhelms intake

**Class:** Abuse / security detection · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: catastrophe claims traffic overwhelms intake.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck catastrophe claims traffic overwhelms intake against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F19 — Actuarial model feature drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: actuarial model feature drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck actuarial model feature drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D04-F20 — Personally identifiable claims data leaked

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: personally identifiable claims data leaked.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected insurtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck personally identifiable claims data leaked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## HealthTech

### D05-F01 — Electronic health record update lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: electronic health record update lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck electronic health record update lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F02 — Patient identity merge attaches wrong chart

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: patient identity merge attaches wrong chart.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck patient identity merge attaches wrong chart against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F03 — Allergy alert fails to display

**Class:** Alerting / monitoring · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: allergy alert fails to display.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck allergy alert fails to display against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F04 — Clinical lab results mapped to wrong patient

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: clinical lab results mapped to wrong patient.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck clinical lab results mapped to wrong patient against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F05 — Medication ordering interface drops prescription

**Class:** Event ordering / async workflow · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: medication ordering interface drops prescription.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck medication ordering interface drops prescription against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F06 — Appointment schedule double-books clinician

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: appointment schedule double-books clinician.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck appointment schedule double-books clinician against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F07 — FHIR API returns incomplete observations

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: fhir api returns incomplete observations.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck fhir api returns incomplete observations against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F08 — Telehealth session disconnects

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: telehealth session disconnects.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck telehealth session disconnects against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F09 — Bed availability feed stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: bed availability feed stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck bed availability feed stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F10 — Clinical decision alert triggers on bad units

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: clinical decision alert triggers on bad units.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck clinical decision alert triggers on bad units against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F11 — Discharge instructions missing translation

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: discharge instructions missing translation.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck discharge instructions missing translation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F12 — Radiology report delivery delayed

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: radiology report delivery delayed.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck radiology report delivery delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F13 — Insurance eligibility batch fails

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: insurance eligibility batch fails.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck insurance eligibility batch fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F14 — Patient portal exposes another patient record

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: patient portal exposes another patient record.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck patient portal exposes another patient record against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F15 — Critical result acknowledgement not recorded

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: critical result acknowledgement not recorded.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck critical result acknowledgement not recorded against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F16 — Time-zone conversion shifts medication schedule

**Class:** Scheduling / batch windows · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: time-zone conversion shifts medication schedule.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck time-zone conversion shifts medication schedule against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F17 — Clinical audit trail incomplete

**Class:** Audit / compliance · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: clinical audit trail incomplete.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck clinical audit trail incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F18 — Provider directory contains inactive clinician

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: provider directory contains inactive clinician.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck provider directory contains inactive clinician against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F19 — Population health extract excludes cohort

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: population health extract excludes cohort.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck population health extract excludes cohort against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D05-F20 — Hospital interface HL7 messages stuck

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: hospital interface hl7 messages stuck.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected healthtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck hospital interface hl7 messages stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## MedTech

### D06-F01 — Device sensor calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: device sensor calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck device sensor calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F02 — Remote patient monitor stops streaming

**Class:** Alerting / monitoring · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: remote patient monitor stops streaming.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck remote patient monitor stops streaming against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F03 — Infusion pump command acknowledgment missing

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: infusion pump command acknowledgment missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck infusion pump command acknowledgment missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F04 — Firmware upgrade bricks subset of devices

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: firmware upgrade bricks subset of devices.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck firmware upgrade bricks subset of devices against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F05 — DICOM image series truncated

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: dicom image series truncated.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck dicom image series truncated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F06 — Imaging reconstruction artifact introduced

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: imaging reconstruction artifact introduced.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck imaging reconstruction artifact introduced against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F07 — Device battery estimate inaccurate

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: device battery estimate inaccurate.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck device battery estimate inaccurate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F08 — Patient-device pairing assigned wrong patient

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: patient-device pairing assigned wrong patient.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck patient-device pairing assigned wrong patient against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F09 — Alarm notification delayed

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: alarm notification delayed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck alarm notification delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F10 — Device clock desynchronization corrupts sequence

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: device clock desynchronization corrupts sequence.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck device clock desynchronization corrupts sequence against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F11 — Wearable telemetry packet loss

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: wearable telemetry packet loss.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck wearable telemetry packet loss against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F12 — Medical device secure boot verification fails

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: medical device secure boot verification fails.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck medical device secure boot verification fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F13 — Ventilator monitoring dashboard stale

**Class:** Staleness / cache · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: ventilator monitoring dashboard stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck ventilator monitoring dashboard stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F14 — Clinical device Bluetooth disconnect storm

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: clinical device bluetooth disconnect storm.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck clinical device bluetooth disconnect storm against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F15 — Sensor threshold unit conversion defect

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: sensor threshold unit conversion defect.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck sensor threshold unit conversion defect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F16 — Device fleet certificate expiry

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: device fleet certificate expiry.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck device fleet certificate expiry against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F17 — Firmware rollback incompatible with data schema

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: firmware rollback incompatible with data schema.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck firmware rollback incompatible with data schema against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F18 — Diagnostic algorithm model drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: diagnostic algorithm model drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck diagnostic algorithm model drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F19 — Medical equipment maintenance alert missed

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: medical equipment maintenance alert missed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck medical equipment maintenance alert missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D06-F20 — Safety-critical event logs lost

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: safety-critical event logs lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected medtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck safety-critical event logs lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## EdTech

### D07-F01 — Exam timer drift across clients

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: exam timer drift across clients.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck exam timer drift across clients against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F02 — Online proctoring stream drops

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: online proctoring stream drops.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck online proctoring stream drops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F03 — Student grades assigned to wrong roster

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: student grades assigned to wrong roster.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck student grades assigned to wrong roster against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F04 — Learning management system grade sync fails

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: learning management system grade sync fails.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck learning management system grade sync fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F05 — Adaptive learning recommendation stuck

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: adaptive learning recommendation stuck.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck adaptive learning recommendation stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F06 — Exam submission duplicated on reconnect

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: exam submission duplicated on reconnect.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck exam submission duplicated on reconnect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F07 — Course enrollment oversells capacity

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: course enrollment oversells capacity.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck course enrollment oversells capacity against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F08 — Video lessons buffering during peak

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: video lessons buffering during peak.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck video lessons buffering during peak against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F09 — Accessibility caption track missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: accessibility caption track missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck accessibility caption track missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F10 — Assignment due-date timezone error

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: assignment due-date timezone error.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck assignment due-date timezone error against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F11 — Question bank exposes answers before exam

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: question bank exposes answers before exam.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck question bank exposes answers before exam against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F12 — Plagiarism detector false-positive surge

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: plagiarism detector false-positive surge.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck plagiarism detector false-positive surge against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F13 — Learning progress overwritten by stale device

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: learning progress overwritten by stale device.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck learning progress overwritten by stale device against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F14 — School SSO integration fails

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: school sso integration fails.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck school sso integration fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F15 — Certificate issued without course completion

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: certificate issued without course completion.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck certificate issued without course completion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F16 — Teacher permission scope too broad

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: teacher permission scope too broad.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck teacher permission scope too broad against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F17 — Discussion moderation backlog

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: discussion moderation backlog.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck discussion moderation backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F18 — Attendance import duplicates students

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: attendance import duplicates students.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck attendance import duplicates students against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F19 — Tuition billing discount incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: tuition billing discount incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck tuition billing discount incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D07-F20 — Student data leaked in analytics export

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: student data leaked in analytics export.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected edtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck student data leaked in analytics export against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## E-commerce

### D08-F01 — Inventory oversold under concurrent checkout

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: inventory oversold under concurrent checkout.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck inventory oversold under concurrent checkout against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F02 — Cart price differs from checkout price

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: cart price differs from checkout price.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck cart price differs from checkout price against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F03 — Promotion applied twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: promotion applied twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck promotion applied twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F04 — Tax calculation wrong by jurisdiction

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: tax calculation wrong by jurisdiction.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck tax calculation wrong by jurisdiction against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F05 — Order placed but payment not captured

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: order placed but payment not captured.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck order placed but payment not captured against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F06 — Payment captured but order creation failed

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: payment captured but order creation failed.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck payment captured but order creation failed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F07 — Shopping search index stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: shopping search index stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck shopping search index stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F08 — Product variant maps to wrong SKU

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: product variant maps to wrong sku.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck product variant maps to wrong sku against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F09 — Return refund occurs before item verification

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: return refund occurs before item verification.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck return refund occurs before item verification against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F10 — Checkout latency spikes during flash sale

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: checkout latency spikes during flash sale.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck checkout latency spikes during flash sale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F11 — Shipment status never updated

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: shipment status never updated.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck shipment status never updated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F12 — Wishlist/cart data lost after login

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: wishlist/cart data lost after login.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck wishlist/cart data lost after login against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F13 — Order cancellation races fulfillment

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: order cancellation races fulfillment.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck order cancellation races fulfillment against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F14 — Product review spam bypasses filter

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: product review spam bypasses filter.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck product review spam bypasses filter against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F15 — Seller payout calculation incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: seller payout calculation incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck seller payout calculation incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F16 — Recommendation service returns unavailable items

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: recommendation service returns unavailable items.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck recommendation service returns unavailable items against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F17 — Checkout currency conversion mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: checkout currency conversion mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck checkout currency conversion mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F18 — Warehouse allocation stuck

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: warehouse allocation stuck.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck warehouse allocation stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F19 — Gift card redemption double-spend

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: gift card redemption double-spend.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck gift card redemption double-spend against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D08-F20 — Customer address data exposed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: customer address data exposed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected e-commerce entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck customer address data exposed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## RetailTech

### D09-F01 — Point-of-sale works offline then duplicates sale

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: point-of-sale works offline then duplicates sale.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck point-of-sale works offline then duplicates sale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F02 — Card terminal cannot reconnect

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: card terminal cannot reconnect.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck card terminal cannot reconnect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F03 — Store inventory diverges from central system

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: store inventory diverges from central system.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck store inventory diverges from central system against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F04 — Barcode maps to wrong product

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: barcode maps to wrong product.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck barcode maps to wrong product against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F05 — Price label differs from POS

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: price label differs from pos.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck price label differs from pos against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F06 — Loyalty points redeemed twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: loyalty points redeemed twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck loyalty points redeemed twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F07 — Cash drawer reconciliation mismatch

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: cash drawer reconciliation mismatch.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck cash drawer reconciliation mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F08 — Receipt printer queue blocked

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: receipt printer queue blocked.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck receipt printer queue blocked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F09 — Self-checkout scanner false reads

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: self-checkout scanner false reads.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck self-checkout scanner false reads against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F10 — Returns accepted against fraudulent receipt

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: returns accepted against fraudulent receipt.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck returns accepted against fraudulent receipt against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F11 — Store replenishment forecast stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: store replenishment forecast stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck store replenishment forecast stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F12 — Coupon validation backend outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: coupon validation backend outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck coupon validation backend outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F13 — Food delivery POS order missed

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: food delivery pos order missed.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck food delivery pos order missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F14 — Shift close report omits tills

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: shift close report omits tills.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck shift close report omits tills against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F15 — POS device certificate expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: pos device certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck pos device certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F16 — Sales tax override applied incorrectly

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: sales tax override applied incorrectly.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck sales tax override applied incorrectly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F17 — Inventory shrinkage alert false positive

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: inventory shrinkage alert false positive.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck inventory shrinkage alert false positive against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F18 — Employee role grants refund privilege

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: employee role grants refund privilege.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck employee role grants refund privilege against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F19 — Terminal firmware update fails at scale

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: terminal firmware update fails at scale.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck terminal firmware update fails at scale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D09-F20 — Store transaction backlog never syncs

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: store transaction backlog never syncs.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected retailtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck store transaction backlog never syncs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## AdTech

### D10-F01 — Real-time bid response exceeds auction deadline

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: real-time bid response exceeds auction deadline.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck real-time bid response exceeds auction deadline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F02 — Campaign budget overspends due to race

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: campaign budget overspends due to race.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck campaign budget overspends due to race against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F03 — Conversion attribution incorrectly deduplicates

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: conversion attribution incorrectly deduplicates.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck conversion attribution incorrectly deduplicates against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F04 — Ad frequency cap ignored across devices

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: ad frequency cap ignored across devices.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck ad frequency cap ignored across devices against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F05 — Invalid traffic filtering fails

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: invalid traffic filtering fails.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck invalid traffic filtering fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F06 — Creative CDN asset returns error

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: creative cdn asset returns error.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck creative cdn asset returns error against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F07 — Audience segment export becomes stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: audience segment export becomes stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck audience segment export becomes stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F08 — Campaign pacing unexpectedly stalls

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: campaign pacing unexpectedly stalls.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck campaign pacing unexpectedly stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F09 — Consent string not honored

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: consent string not honored.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck consent string not honored against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F10 — Auction clearing price miscalculated

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: auction clearing price miscalculated.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck auction clearing price miscalculated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F11 — Bid floor targeting mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: bid floor targeting mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck bid floor targeting mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F12 — Ad impression counted twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: ad impression counted twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck ad impression counted twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F13 — Click tracking redirect loops

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: click tracking redirect loops.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck click tracking redirect loops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F14 — Brand safety classifier misses unsafe placement

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: brand safety classifier misses unsafe placement.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck brand safety classifier misses unsafe placement against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F15 — Ad exchange request schema changes

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: ad exchange request schema changes.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck ad exchange request schema changes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F16 — Campaign targeting includes excluded geography

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: campaign targeting includes excluded geography.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck campaign targeting includes excluded geography against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F17 — Delayed conversion postback dropped

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: delayed conversion postback dropped.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck delayed conversion postback dropped against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F18 — Reporting differs from billing events

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: reporting differs from billing events.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck reporting differs from billing events against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F19 — Creative policy approval state lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: creative policy approval state lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck creative policy approval state lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D10-F20 — User identifiers leaked through ad request

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: user identifiers leaked through ad request.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected adtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck user identifiers leaked through ad request against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## MarTech

### D11-F01 — Marketing email sends twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: marketing email sends twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck marketing email sends twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F02 — Suppression list not enforced

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: suppression list not enforced.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck suppression list not enforced against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F03 — Customer segment includes wrong users

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: customer segment includes wrong users.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck customer segment includes wrong users against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F04 — CRM sync overwrites newer contact fields

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: crm sync overwrites newer contact fields.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck crm sync overwrites newer contact fields against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F05 — Campaign personalization uses stale attributes

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: campaign personalization uses stale attributes.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck campaign personalization uses stale attributes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F06 — Unsubscribe webhook never ingested

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: unsubscribe webhook never ingested.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck unsubscribe webhook never ingested against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F07 — Email deliverability falls due to domain reputation

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: email deliverability falls due to domain reputation.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck email deliverability falls due to domain reputation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F08 — Journey workflow loops infinitely

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: journey workflow loops infinitely.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck journey workflow loops infinitely against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F09 — A/B experiment assignments shift mid-test

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: a/b experiment assignments shift mid-test.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck a/b experiment assignments shift mid-test against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F10 — SMS provider rate limit blocks campaign

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: sms provider rate limit blocks campaign.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck sms provider rate limit blocks campaign against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F11 — Template merge field exposes another customer

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: template merge field exposes another customer.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck template merge field exposes another customer against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F12 — Event tracking loses attribution tags

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: event tracking loses attribution tags.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck event tracking loses attribution tags against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F13 — Lead scoring model drifts

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: lead scoring model drifts.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck lead scoring model drifts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F14 — Customer consent expires but messaging continues

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: customer consent expires but messaging continues.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck customer consent expires but messaging continues against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F15 — Campaign scheduled in wrong timezone

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: campaign scheduled in wrong timezone.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck campaign scheduled in wrong timezone against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F16 — Webhook retries reorder customer activity

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: webhook retries reorder customer activity.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck webhook retries reorder customer activity against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F17 — Marketing analytics overcounts conversions

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: marketing analytics overcounts conversions.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck marketing analytics overcounts conversions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F18 — Contact deduplication merges unrelated people

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: contact deduplication merges unrelated people.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck contact deduplication merges unrelated people against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F19 — Marketing platform OAuth token expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: marketing platform oauth token expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck marketing platform oauth token expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D11-F20 — Push notification deep links broken

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: push notification deep links broken.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected martech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck push notification deep links broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## SaaS

### D12-F01 — Tenant data isolation breach

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: tenant data isolation breach.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck tenant data isolation breach against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F02 — Subscription entitlement not refreshed

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: subscription entitlement not refreshed.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck subscription entitlement not refreshed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F03 — Plan downgrade leaves privileged features active

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: plan downgrade leaves privileged features active.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck plan downgrade leaves privileged features active against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F04 — API rate limiter globally throttles one tenant

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: api rate limiter globally throttles one tenant.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck api rate limiter globally throttles one tenant against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F05 — Scheduled background jobs starve

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: scheduled background jobs starve.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck scheduled background jobs starve against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F06 — Multi-region failover drops writes

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: multi-region failover drops writes.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck multi-region failover drops writes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F07 — Feature flag rollout breaks tenant subset

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: feature flag rollout breaks tenant subset.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck feature flag rollout breaks tenant subset against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F08 — Tenant migration partly applied

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: tenant migration partly applied.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck tenant migration partly applied against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F09 — Billing usage metering misses events

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: billing usage metering misses events.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck billing usage metering misses events against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F10 — SSO SAML certificate expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: sso saml certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck sso saml certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F11 — Role-based access check bypassed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: role-based access check bypassed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck role-based access check bypassed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F12 — Webhook delivery queue backs up

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: webhook delivery queue backs up.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck webhook delivery queue backs up against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F13 — Customer import corrupts mapping

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: customer import corrupts mapping.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck customer import corrupts mapping against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F14 — Search index tenant filter omitted

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: search index tenant filter omitted.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck search index tenant filter omitted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F15 — Long-running report times out

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: long-running report times out.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck long-running report times out against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F16 — Audit logs silently stop

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: audit logs silently stop.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck audit logs silently stop against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F17 — Account provisioning inconsistent across services

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: account provisioning inconsistent across services.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck account provisioning inconsistent across services against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F18 — Seat count billing race

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: seat count billing race.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck seat count billing race against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F19 — Public API backward compatibility broken

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: public api backward compatibility broken.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck public api backward compatibility broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D12-F20 — Support impersonation session not expired

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: support impersonation session not expired.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected saas entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck support impersonation session not expired against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Cloud Computing

### D13-F01 — Availability zone network partition

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: availability zone network partition.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck availability zone network partition against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F02 — Load balancer health check misroutes traffic

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: load balancer health check misroutes traffic.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck load balancer health check misroutes traffic against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F03 — Auto-scaling scale-out lag

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: auto-scaling scale-out lag.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck auto-scaling scale-out lag against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F04 — Object storage permission regression

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: object storage permission regression.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck object storage permission regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F05 — Kubernetes pod crash loop

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: kubernetes pod crash loop.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck kubernetes pod crash loop against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F06 — Service mesh certificate expiry

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: service mesh certificate expiry.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck service mesh certificate expiry against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F07 — DNS resolution intermittent failure

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: dns resolution intermittent failure.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck dns resolution intermittent failure against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F08 — Cloud IAM policy accidentally overbroad

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: cloud iam policy accidentally overbroad.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck cloud iam policy accidentally overbroad against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F09 — Container image pull throttled

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: container image pull throttled.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck container image pull throttled against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F10 — Distributed cache cluster split-brain

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: distributed cache cluster split-brain.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck distributed cache cluster split-brain against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F11 — Managed database replica lag

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: managed database replica lag.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck managed database replica lag against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F12 — Control plane API rate limit saturation

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: control plane api rate limit saturation.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck control plane api rate limit saturation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F13 — Cloud quota exhaustion blocks provisioning

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: cloud quota exhaustion blocks provisioning.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck cloud quota exhaustion blocks provisioning against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F14 — Cross-region replication stalls

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: cross-region replication stalls.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck cross-region replication stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F15 — Secret manager unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: secret manager unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck secret manager unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F16 — Node disk pressure eviction storm

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: node disk pressure eviction storm.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck node disk pressure eviction storm against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F17 — Queue visibility timeout causes duplicates

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: queue visibility timeout causes duplicates.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck queue visibility timeout causes duplicates against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F18 — Infrastructure as code drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: infrastructure as code drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck infrastructure as code drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F19 — Serverless cold start latency regression

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: serverless cold start latency regression.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck serverless cold start latency regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D13-F20 — Region failover leaves stale DNS

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: region failover leaves stale dns.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected cloud computing entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck region failover leaves stale dns against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Cybersecurity

### D14-F01 — Identity provider authentication outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: identity provider authentication outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck identity provider authentication outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F02 — SIEM ingestion drops security events

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: siem ingestion drops security events.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck siem ingestion drops security events against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F03 — Endpoint agent stops reporting

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: endpoint agent stops reporting.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck endpoint agent stops reporting against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F04 — Detection rules generate false-positive flood

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: detection rules generate false-positive flood.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck detection rules generate false-positive flood against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F05 — Threat intelligence feed outdated

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: threat intelligence feed outdated.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck threat intelligence feed outdated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F06 — Session tokens not revoked at logout

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: session tokens not revoked at logout.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck session tokens not revoked at logout against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F07 — Privilege escalation via broken authorization

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: privilege escalation via broken authorization.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck privilege escalation via broken authorization against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F08 — Certificate authority chain expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: certificate authority chain expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck certificate authority chain expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F09 — Security scanner silently skips assets

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: security scanner silently skips assets.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck security scanner silently skips assets against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F10 — WAF accidentally blocks legitimate users

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: waf accidentally blocks legitimate users.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck waf accidentally blocks legitimate users against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F11 — Secrets exposed in CI logs

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: secrets exposed in ci logs.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck secrets exposed in ci logs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F12 — Firewall rules allow unintended ingress

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: firewall rules allow unintended ingress.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck firewall rules allow unintended ingress against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F13 — Phishing detection model misses campaign

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: phishing detection model misses campaign.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck phishing detection model misses campaign against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F14 — Incident alert routing broken

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: incident alert routing broken.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck incident alert routing broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F15 — Vulnerability remediation misses critical hosts

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: vulnerability remediation misses critical hosts.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck vulnerability remediation misses critical hosts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F16 — Audit event timestamps desynchronized

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: audit event timestamps desynchronized.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck audit event timestamps desynchronized against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F17 — EDR policy deployment incomplete

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: edr policy deployment incomplete.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck edr policy deployment incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F18 — Rate limit evasion by credential stuffing

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: rate limit evasion by credential stuffing.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck rate limit evasion by credential stuffing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F19 — Log retention expires prematurely

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: log retention expires prematurely.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck log retention expires prematurely against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D14-F20 — Encrypted backups cannot be restored

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: encrypted backups cannot be restored.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected cybersecurity entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck encrypted backups cannot be restored against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## AI / ML

### D15-F01 — Model inference latency spikes

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: model inference latency spikes.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck model inference latency spikes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F02 — Feature store offline-online skew

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: feature store offline-online skew.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck feature store offline-online skew against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F03 — Training-serving preprocessing mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: training-serving preprocessing mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck training-serving preprocessing mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F04 — Retrieval index contains stale documents

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: retrieval index contains stale documents.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck retrieval index contains stale documents against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F05 — LLM prompt injection bypasses workflow rules

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: llm prompt injection bypasses workflow rules.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck llm prompt injection bypasses workflow rules against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F06 — Model response leaks private tenant content

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: model response leaks private tenant content.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck model response leaks private tenant content against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F07 — Tool-calling agent enters infinite loop

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: tool-calling agent enters infinite loop.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck tool-calling agent enters infinite loop against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F08 — Model endpoint quota exhausted

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: model endpoint quota exhausted.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck model endpoint quota exhausted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F09 — Embedding dimension mismatch after upgrade

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: embedding dimension mismatch after upgrade.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck embedding dimension mismatch after upgrade against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F10 — Model hallucination falsely executes business action

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: model hallucination falsely executes business action.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck model hallucination falsely executes business action against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F11 — Vector database index rebuild degrades recall

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: vector database index rebuild degrades recall.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck vector database index rebuild degrades recall against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F12 — Inference GPU out-of-memory

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: inference gpu out-of-memory.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck inference gpu out-of-memory against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F13 — Dataset label leakage corrupts evaluation

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: dataset label leakage corrupts evaluation.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck dataset label leakage corrupts evaluation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F14 — Drift monitor misses distribution shift

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: drift monitor misses distribution shift.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck drift monitor misses distribution shift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F15 — Canary deployment changes model output distribution

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: canary deployment changes model output distribution.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck canary deployment changes model output distribution against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F16 — Guardrail classifier blocks benign requests

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: guardrail classifier blocks benign requests.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck guardrail classifier blocks benign requests against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F17 — Training pipeline checkpoint corrupt

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: training pipeline checkpoint corrupt.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck training pipeline checkpoint corrupt against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F18 — Model version registry points to wrong artifact

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: model version registry points to wrong artifact.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck model version registry points to wrong artifact against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F19 — External LLM provider outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: external llm provider outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck external llm provider outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D15-F20 — Agent retries cause duplicate side effects

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: agent retries cause duplicate side effects.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected ai / ml entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck agent retries cause duplicate side effects against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Data & Analytics

### D16-F01 — ETL silently drops records

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: etl silently drops records.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck etl silently drops records against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F02 — CDC replication lags source database

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: cdc replication lags source database.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck cdc replication lags source database against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F03 — Schema evolution breaks downstream job

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: schema evolution breaks downstream job.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck schema evolution breaks downstream job against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F04 — Lakehouse partition pruning regression

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: lakehouse partition pruning regression.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck lakehouse partition pruning regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F05 — Data warehouse compute quota exhausted

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: data warehouse compute quota exhausted.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck data warehouse compute quota exhausted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F06 — Dimension join causes duplicate fact rows

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: dimension join causes duplicate fact rows.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck dimension join causes duplicate fact rows against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F07 — Late-arriving events misaggregate metrics

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: late-arriving events misaggregate metrics.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck late-arriving events misaggregate metrics against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F08 — Snapshot backfill overwrites current partitions

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: snapshot backfill overwrites current partitions.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck snapshot backfill overwrites current partitions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F09 — PII masking absent in data export

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: pii masking absent in data export.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck pii masking absent in data export against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F10 — Data quality threshold incorrectly configured

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: data quality threshold incorrectly configured.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck data quality threshold incorrectly configured against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F11 — Airflow DAG dependency deadlocks

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: airflow dag dependency deadlocks.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck airflow dag dependency deadlocks against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F12 — Streaming watermark stalls

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: streaming watermark stalls.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck streaming watermark stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F13 — Dashboard semantic metric definition changes

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: dashboard semantic metric definition changes.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck dashboard semantic metric definition changes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F14 — Database ingestion connector expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: database ingestion connector expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck database ingestion connector expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F15 — Data lineage metadata missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: data lineage metadata missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck data lineage metadata missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F16 — Object storage file committed partially

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: object storage file committed partially.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck object storage file committed partially against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F17 — Analytics query spills to disk

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: analytics query spills to disk.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck analytics query spills to disk against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F18 — Data catalog access permission regression

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: data catalog access permission regression.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck data catalog access permission regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F19 — Data reconciliation tolerances too permissive

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: data reconciliation tolerances too permissive.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck data reconciliation tolerances too permissive against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D16-F20 — BI cache shows stale financial figures

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: bi cache shows stale financial figures.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected data & analytics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck bi cache shows stale financial figures against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## DevTools

### D17-F01 — CI runner pool exhausted

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: ci runner pool exhausted.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck ci runner pool exhausted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F02 — Build artifact checksum mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: build artifact checksum mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck build artifact checksum mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F03 — Dependency registry unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: dependency registry unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck dependency registry unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F04 — Test suite flaky due to race

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: test suite flaky due to race.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck test suite flaky due to race against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F05 — Deployment pipeline promotes wrong commit

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: deployment pipeline promotes wrong commit.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck deployment pipeline promotes wrong commit against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F06 — Secret printed in build logs

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: secret printed in build logs.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck secret printed in build logs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F07 — Git webhook deliveries dropped

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: git webhook deliveries dropped.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck git webhook deliveries dropped against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F08 — Package signature verification fails

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: package signature verification fails.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck package signature verification fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F09 — Artifact retention deletes required rollback version

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: artifact retention deletes required rollback version.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck artifact retention deletes required rollback version against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F10 — Canary analysis ignores key metric

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: canary analysis ignores key metric.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck canary analysis ignores key metric against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F11 — IDE extension crash on project load

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: ide extension crash on project load.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck ide extension crash on project load against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F12 — Compiler cache serves stale output

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: compiler cache serves stale output.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck compiler cache serves stale output against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F13 — Developer access token expires unexpectedly

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: developer access token expires unexpectedly.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck developer access token expires unexpectedly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F14 — Infrastructure deployment stuck on lock

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: infrastructure deployment stuck on lock.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck infrastructure deployment stuck on lock against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F15 — Container registry throttles pulls

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: container registry throttles pulls.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck container registry throttles pulls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F16 — Source code indexing backlog

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: source code indexing backlog.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck source code indexing backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F17 — Observability trace context propagation broken

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: observability trace context propagation broken.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck observability trace context propagation broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F18 — Feature flag SDK fails to refresh

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: feature flag sdk fails to refresh.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck feature flag sdk fails to refresh against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F19 — Release rollback does not revert migration

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: release rollback does not revert migration.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck release rollback does not revert migration against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D17-F20 — Build provenance metadata missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: build provenance metadata missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected devtools entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck build provenance metadata missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Telecommunications

### D18-F01 — Cell tower sector loses backhaul

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: cell tower sector loses backhaul.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck cell tower sector loses backhaul against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F02 — 5G handover fails at cell boundary

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: 5g handover fails at cell boundary.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck 5g handover fails at cell boundary against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F03 — Subscriber provisioning stuck

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: subscriber provisioning stuck.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck subscriber provisioning stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F04 — SIM activation duplicated

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: sim activation duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck sim activation duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F05 — Billing CDR records missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: billing cdr records missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck billing cdr records missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F06 — Network congestion controller misconfigures QoS

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: network congestion controller misconfigures qos.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck network congestion controller misconfigures qos against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F07 — Fiber link degradation raises packet loss

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: fiber link degradation raises packet loss.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck fiber link degradation raises packet loss against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F08 — Tower battery backup fails during outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: tower battery backup fails during outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck tower battery backup fails during outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F09 — Roaming partner authentication failure

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: roaming partner authentication failure.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck roaming partner authentication failure against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F10 — VoLTE call setup failures spike

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: volte call setup failures spike.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck volte call setup failures spike against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F11 — Mobile data usage metering incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: mobile data usage metering incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck mobile data usage metering incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F12 — Network topology inventory stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: network topology inventory stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck network topology inventory stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F13 — Field work order sync duplicated

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: field work order sync duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck field work order sync duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F14 — Equipment location tracking inaccurate

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: equipment location tracking inaccurate.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck equipment location tracking inaccurate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F15 — DNS caching failure impacts subscribers

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: dns caching failure impacts subscribers.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck dns caching failure impacts subscribers against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F16 — Emergency call routing degraded

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: emergency call routing degraded.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck emergency call routing degraded against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F17 — BGP route leak causes regional outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: bgp route leak causes regional outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck bgp route leak causes regional outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F18 — Base station firmware rollout regression

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: base station firmware rollout regression.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck base station firmware rollout regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F19 — Provisioning certificate expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: provisioning certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck provisioning certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D18-F20 — Customer PII exposed in network diagnostics

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: customer pii exposed in network diagnostics.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected telecommunications entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck customer pii exposed in network diagnostics against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Media & Entertainment

### D19-F01 — Streaming CDN regional outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: streaming cdn regional outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck streaming cdn regional outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F02 — Video transcoding job produces broken rendition

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: video transcoding job produces broken rendition.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck video transcoding job produces broken rendition against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F03 — DRM license delivery fails

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: drm license delivery fails.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck drm license delivery fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F04 — Playback buffering regression

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: playback buffering regression.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck playback buffering regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F05 — Subtitle audio sync drifts

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: subtitle audio sync drifts.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck subtitle audio sync drifts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F06 — Royalty tracking misses listens

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: royalty tracking misses listens.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck royalty tracking misses listens against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F07 — Content geo-rights enforcement wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: content geo-rights enforcement wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck content geo-rights enforcement wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F08 — Recommendation model overexposes removed content

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: recommendation model overexposes removed content.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck recommendation model overexposes removed content against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F09 — Livestream chat moderation backlog

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: livestream chat moderation backlog.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck livestream chat moderation backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F10 — Subscription entitlement delayed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: subscription entitlement delayed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck subscription entitlement delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F11 — Watch-progress sync overwrites newer state

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: watch-progress sync overwrites newer state.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck watch-progress sync overwrites newer state against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F12 — Media upload virus scanning stalls

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: media upload virus scanning stalls.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck media upload virus scanning stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F13 — Live stream ingest packet loss

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: live stream ingest packet loss.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck live stream ingest packet loss against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F14 — Ad insertion causes playback crash

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: ad insertion causes playback crash.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck ad insertion causes playback crash against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F15 — Content takedown not propagated to CDN

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: content takedown not propagated to cdn.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck content takedown not propagated to cdn against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F16 — Creator revenue share miscomputed

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: creator revenue share miscomputed.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck creator revenue share miscomputed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F17 — Playback device codec negotiation fails

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: playback device codec negotiation fails.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck playback device codec negotiation fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F18 — Trending ranking spam manipulation

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: trending ranking spam manipulation.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck trending ranking spam manipulation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F19 — Playback analytics undercounts sessions

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: playback analytics undercounts sessions.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck playback analytics undercounts sessions against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D19-F20 — Private media asset publicly accessible

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: private media asset publicly accessible.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected media & entertainment entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck private media asset publicly accessible against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Gaming

### D20-F01 — Game server tick-rate drops

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: game server tick-rate drops.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck game server tick-rate drops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F02 — Matchmaking queue starvation

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: matchmaking queue starvation.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck matchmaking queue starvation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F03 — Player inventory item duplication exploit

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: player inventory item duplication exploit.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck player inventory item duplication exploit against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F04 — In-game purchase fulfillment delayed

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: in-game purchase fulfillment delayed.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck in-game purchase fulfillment delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F05 — Cross-region gameplay latency spike

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: cross-region gameplay latency spike.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck cross-region gameplay latency spike against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F06 — Anti-cheat false ban wave

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: anti-cheat false ban wave.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck anti-cheat false ban wave against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F07 — Save-game data rolled back

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: save-game data rolled back.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck save-game data rolled back against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F08 — Economy currency balance becomes negative

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: economy currency balance becomes negative.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck economy currency balance becomes negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F09 — Leaderboard scores manipulated

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: leaderboard scores manipulated.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck leaderboard scores manipulated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F10 — Voice chat service unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: voice chat service unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck voice chat service unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F11 — Session reconnection loses match state

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: session reconnection loses match state.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck session reconnection loses match state against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F12 — Patch deployment breaks client compatibility

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: patch deployment breaks client compatibility.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck patch deployment breaks client compatibility against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F13 — Game asset CDN cache mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: game asset cdn cache mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck game asset cdn cache mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F14 — Live event reward delivered twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: live event reward delivered twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck live event reward delivered twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F15 — Player authentication session expires mid-match

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: player authentication session expires mid-match.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck player authentication session expires mid-match against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F16 — Server instance crashes under load

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: server instance crashes under load.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck server instance crashes under load against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F17 — Team assignment races at match start

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: team assignment races at match start.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck team assignment races at match start against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F18 — User-generated content moderation misses abuse

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: user-generated content moderation misses abuse.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck user-generated content moderation misses abuse against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F19 — Tournament scoring synchronization fails

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: tournament scoring synchronization fails.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck tournament scoring synchronization fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D20-F20 — Personal player data exposed via lobby API

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: personal player data exposed via lobby api.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected gaming entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck personal player data exposed via lobby api against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## TravelTech

### D21-F01 — Hotel room inventory oversold

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: hotel room inventory oversold.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck hotel room inventory oversold against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F02 — Flight fare quote expires before booking

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: flight fare quote expires before booking.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck flight fare quote expires before booking against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F03 — Booking confirmed without supplier reservation

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: booking confirmed without supplier reservation.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck booking confirmed without supplier reservation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F04 — Refund status mismatched with payment

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: refund status mismatched with payment.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck refund status mismatched with payment against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F05 — Airline schedule change notifications missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: airline schedule change notifications missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck airline schedule change notifications missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F06 — Property tax calculation incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: property tax calculation incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck property tax calculation incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F07 — Ticket issuance queue stuck

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: ticket issuance queue stuck.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck ticket issuance queue stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F08 — Loyalty points credited twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: loyalty points credited twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck loyalty points credited twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F09 — Check-in QR code invalid

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: check-in qr code invalid.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck check-in qr code invalid against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F10 — Travel search results show canceled routes

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: travel search results show canceled routes.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck travel search results show canceled routes against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F11 — Time zone/daylight saving shifts itinerary

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: time zone/daylight saving shifts itinerary.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck time zone/daylight saving shifts itinerary against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F12 — Third-party global distribution system outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: third-party global distribution system outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck third-party global distribution system outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F13 — Seat assignment conflicts

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: seat assignment conflicts.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck seat assignment conflicts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F14 — Multi-leg trip cancellation partially applied

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: multi-leg trip cancellation partially applied.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck multi-leg trip cancellation partially applied against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F15 — Cancellation policy misquoted

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: cancellation policy misquoted.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck cancellation policy misquoted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F16 — Traveler passport details leaked

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: traveler passport details leaked.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck traveler passport details leaked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F17 — Airport transfer pickup location stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: airport transfer pickup location stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck airport transfer pickup location stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F18 — Travel insurance add-on not activated

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: travel insurance add-on not activated.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck travel insurance add-on not activated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F19 — Dynamic pricing spikes erroneously

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: dynamic pricing spikes erroneously.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck dynamic pricing spikes erroneously against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D21-F20 — Accommodation reviews moderation backlog

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: accommodation reviews moderation backlog.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected traveltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck accommodation reviews moderation backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Logistics & Supply Chain

### D22-F01 — Package scan event lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: package scan event lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck package scan event lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F02 — Route optimizer assigns impossible delivery window

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: route optimizer assigns impossible delivery window.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck route optimizer assigns impossible delivery window against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F03 — Warehouse robot pick queue stalls

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: warehouse robot pick queue stalls.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck warehouse robot pick queue stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F04 — Shipment tracking out of sequence

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: shipment tracking out of sequence.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck shipment tracking out of sequence against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F05 — Customs documentation incomplete

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: customs documentation incomplete.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck customs documentation incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F06 — Cold-chain temperature excursion unnoticed

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: cold-chain temperature excursion unnoticed.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck cold-chain temperature excursion unnoticed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F07 — Carrier API returns stale status

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: carrier api returns stale status.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck carrier api returns stale status against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F08 — Inventory counted twice across warehouses

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: inventory counted twice across warehouses.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck inventory counted twice across warehouses against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F09 — Proof-of-delivery signature missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: proof-of-delivery signature missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck proof-of-delivery signature missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F10 — Freight invoice charge miscalculated

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: freight invoice charge miscalculated.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck freight invoice charge miscalculated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F11 — Dispatch assigns same truck twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: dispatch assigns same truck twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck dispatch assigns same truck twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F12 — GPS tracker goes offline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: gps tracker goes offline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck gps tracker goes offline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F13 — Hazardous goods classification incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: hazardous goods classification incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck hazardous goods classification incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F14 — Supplier ASN mismatches received goods

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: supplier asn mismatches received goods.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck supplier asn mismatches received goods against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F15 — Delivery driver app offline sync conflict

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: delivery driver app offline sync conflict.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck delivery driver app offline sync conflict against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F16 — Warehouse replenishment loop causes shortages

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: warehouse replenishment loop causes shortages.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck warehouse replenishment loop causes shortages against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F17 — Cross-dock package misrouted

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: cross-dock package misrouted.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck cross-dock package misrouted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F18 — Last-mile route geocode wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: last-mile route geocode wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck last-mile route geocode wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F19 — Fleet preventative maintenance not scheduled

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: fleet preventative maintenance not scheduled.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck fleet preventative maintenance not scheduled against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D22-F20 — Customer address exposed in manifest

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: customer address exposed in manifest.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected logistics & supply chain entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck customer address exposed in manifest against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Automotive Tech

### D23-F01 — Vehicle OTA update fails mid-install

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: vehicle ota update fails mid-install.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck vehicle ota update fails mid-install against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F02 — ADAS camera calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: adas camera calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck adas camera calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F03 — Battery management SOC estimate wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: battery management soc estimate wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck battery management soc estimate wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F04 — Connected car command replay

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: connected car command replay.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck connected car command replay against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F05 — Fleet telematics GPS missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: fleet telematics gps missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck fleet telematics gps missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F06 — Vehicle-cloud certificate expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: vehicle-cloud certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck vehicle-cloud certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F07 — Autonomous perception false positive obstacle

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: autonomous perception false positive obstacle.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck autonomous perception false positive obstacle against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F08 — Sensor fusion timestamps misaligned

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: sensor fusion timestamps misaligned.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck sensor fusion timestamps misaligned against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F09 — Charging station handshake fails

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: charging station handshake fails.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck charging station handshake fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F10 — Vehicle diagnostic trouble code misclassified

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: vehicle diagnostic trouble code misclassified.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck vehicle diagnostic trouble code misclassified against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F11 — Brake alert latency regression

**Class:** Latency / capacity · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: brake alert latency regression.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck brake alert latency regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F12 — EV charging session billing duplicate

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: ev charging session billing duplicate.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck ev charging session billing duplicate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F13 — Navigation map tiles out of date

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: navigation map tiles out of date.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck navigation map tiles out of date against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F14 — Vehicle firmware feature flag incompatible

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: vehicle firmware feature flag incompatible.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck vehicle firmware feature flag incompatible against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F15 — Emergency assist call fails

**Class:** Rollout / compatibility · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: emergency assist call fails.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck emergency assist call fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F16 — OTA staged rollout misses hardware variant

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: ota staged rollout misses hardware variant.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck ota staged rollout misses hardware variant against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F17 — Remote lock state desynchronized

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: remote lock state desynchronized.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck remote lock state desynchronized against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F18 — Vehicle telemetry privacy consent ignored

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: vehicle telemetry privacy consent ignored.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck vehicle telemetry privacy consent ignored against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F19 — Autonomy model inference slows in weather

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: autonomy model inference slows in weather.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck autonomy model inference slows in weather against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D23-F20 — Vehicle fault event dropped in gateway

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: vehicle fault event dropped in gateway.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected automotive tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck vehicle fault event dropped in gateway against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Aerospace & Defense

### D24-F01 — Flight telemetry stream packet loss

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: flight telemetry stream packet loss.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck flight telemetry stream packet loss against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F02 — Satellite attitude data stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: satellite attitude data stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck satellite attitude data stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F03 — Ground station link handover failure

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: ground station link handover failure.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck ground station link handover failure against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F04 — Mission planning coordinates transformed incorrectly

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: mission planning coordinates transformed incorrectly.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck mission planning coordinates transformed incorrectly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F05 — Avionics firmware compatibility regression

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: avionics firmware compatibility regression.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck avionics firmware compatibility regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F06 — Sensor redundancy voting inconsistency

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: sensor redundancy voting inconsistency.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck sensor redundancy voting inconsistency against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F07 — Navigation clock synchronization lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: navigation clock synchronization lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck navigation clock synchronization lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F08 — Radar track duplication

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: radar track duplication.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck radar track duplication against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F09 — Aircraft maintenance event omitted

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: aircraft maintenance event omitted.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck aircraft maintenance event omitted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F10 — Telemetry encryption key expiry

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: telemetry encryption key expiry.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck telemetry encryption key expiry against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F11 — Air traffic message routing delayed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: air traffic message routing delayed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck air traffic message routing delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F12 — High-availability mission system failover fails

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: high-availability mission system failover fails.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck high-availability mission system failover fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F13 — Satellite command acknowledgment missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: satellite command acknowledgment missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck satellite command acknowledgment missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F14 — Flight simulation model divergence

**Class:** Model / rules drift · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: flight simulation model divergence.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck flight simulation model divergence against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F15 — Asset configuration baseline mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: asset configuration baseline mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck asset configuration baseline mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F16 — Safety-critical alert suppressed

**Class:** Alerting / monitoring · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: safety-critical alert suppressed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck safety-critical alert suppressed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F17 — Geospatial target map projection error

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: geospatial target map projection error.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck geospatial target map projection error against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F18 — Flight recorder data corruption

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: flight recorder data corruption.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck flight recorder data corruption against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F19 — Command authorization audit gap

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: command authorization audit gap.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck command authorization audit gap against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D24-F20 — Real-time system deadline missed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: real-time system deadline missed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected aerospace & defense entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck real-time system deadline missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## PropTech

### D25-F01 — Property listing remains active after sale

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: property listing remains active after sale.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck property listing remains active after sale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F02 — Rental payment charged twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: rental payment charged twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck rental payment charged twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F03 — Tenant screening vendor times out

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: tenant screening vendor times out.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck tenant screening vendor times out against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F04 — Lease e-signature webhook missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: lease e-signature webhook missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck lease e-signature webhook missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F05 — Maintenance work orders lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: maintenance work orders lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck maintenance work orders lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F06 — Real estate valuation model drifts

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: real estate valuation model drifts.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck real estate valuation model drifts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F07 — Rent adjustment applies wrong escalation

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: rent adjustment applies wrong escalation.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck rent adjustment applies wrong escalation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F08 — Building access code not revoked

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: building access code not revoked.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck building access code not revoked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F09 — Unit availability sync conflicts

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: unit availability sync conflicts.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck unit availability sync conflicts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F10 — Mortgage preapproval status stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: mortgage preapproval status stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck mortgage preapproval status stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F11 — Property tax escrow calculation wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: property tax escrow calculation wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck property tax escrow calculation wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F12 — Utility meter integration missing readings

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: utility meter integration missing readings.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck utility meter integration missing readings against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F13 — Agent lead routing duplicates requests

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: agent lead routing duplicates requests.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck agent lead routing duplicates requests against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F14 — Fair housing compliance rule bypass

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: fair housing compliance rule bypass.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck fair housing compliance rule bypass against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F15 — Virtual tour CDN fails

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: virtual tour cdn fails.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck virtual tour cdn fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F16 — Owner payout allocation incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: owner payout allocation incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck owner payout allocation incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F17 — Applicant documents exposed across properties

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: applicant documents exposed across properties.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck applicant documents exposed across properties against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F18 — Maintenance emergency escalation fails

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: maintenance emergency escalation fails.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck maintenance emergency escalation fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F19 — Security deposit refund processed twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: security deposit refund processed twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck security deposit refund processed twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D25-F20 — Geocoding assigns property to wrong school district

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: geocoding assigns property to wrong school district.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected proptech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck geocoding assigns property to wrong school district against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## EnergyTech

### D26-F01 — Smart meter reads missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: smart meter reads missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck smart meter reads missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F02 — Grid load forecast underestimates demand

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: grid load forecast underestimates demand.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck grid load forecast underestimates demand against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F03 — Inverter trips repeatedly

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: inverter trips repeatedly.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck inverter trips repeatedly against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F04 — Renewable generation telemetry stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: renewable generation telemetry stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck renewable generation telemetry stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F05 — Battery dispatch violates reserve constraint

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: battery dispatch violates reserve constraint.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck battery dispatch violates reserve constraint against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F06 — Electricity market pricing feed wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: electricity market pricing feed wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck electricity market pricing feed wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F07 — Substation event alarm not delivered

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: substation event alarm not delivered.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck substation event alarm not delivered against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F08 — Distributed energy resource control loses connectivity

**Class:** Resource exhaustion · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: distributed energy resource control loses connectivity.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck distributed energy resource control loses connectivity against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F09 — Power quality voltage excursion unseen

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: power quality voltage excursion unseen.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck power quality voltage excursion unseen against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F10 — Demand response command delayed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: demand response command delayed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck demand response command delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F11 — EV charger OCPP session stalls

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: ev charger ocpp session stalls.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck ev charger ocpp session stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F12 — Outage management system misidentifies feeder

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: outage management system misidentifies feeder.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck outage management system misidentifies feeder against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F13 — SCADA historian drops points

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: scada historian drops points.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck scada historian drops points against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F14 — Solar asset inverter firmware regression

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: solar asset inverter firmware regression.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck solar asset inverter firmware regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F15 — Utility billing time-of-use interval incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: utility billing time-of-use interval incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck utility billing time-of-use interval incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F16 — Grid topology model stale

**Class:** Staleness / cache · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: grid topology model stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck grid topology model stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F17 — Energy storage temperature sensor drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: energy storage temperature sensor drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck energy storage temperature sensor drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F18 — Remote breaker command not acknowledged

**Class:** Abuse / security detection · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: remote breaker command not acknowledged.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck remote breaker command not acknowledged against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F19 — Generator maintenance prediction misses fault

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: generator maintenance prediction misses fault.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck generator maintenance prediction misses fault against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D26-F20 — Customer consumption data exposed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: customer consumption data exposed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected energytech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck customer consumption data exposed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## ClimateTech

### D27-F01 — Carbon accounting activity data duplicated

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: carbon accounting activity data duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck carbon accounting activity data duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F02 — Emissions factor dataset outdated

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: emissions factor dataset outdated.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck emissions factor dataset outdated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F03 — Satellite methane detection false positive

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: satellite methane detection false positive.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck satellite methane detection false positive against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F04 — Offset registry double-counts credits

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: offset registry double-counts credits.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck offset registry double-counts credits against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F05 — Facility energy monitoring sensor gaps

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: facility energy monitoring sensor gaps.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck facility energy monitoring sensor gaps against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F06 — Carbon report excludes scope-3 supplier

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: carbon report excludes scope-3 supplier.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck carbon report excludes scope-3 supplier against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F07 — Emission intensity unit conversion wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: emission intensity unit conversion wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck emission intensity unit conversion wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F08 — Climate model bias grows after season shift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: climate model bias grows after season shift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck climate model bias grows after season shift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F09 — Weather ingestion misses severe event

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: weather ingestion misses severe event.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck weather ingestion misses severe event against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F10 — Environmental sensor calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: environmental sensor calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck environmental sensor calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F11 — Carbon credit retirement sync fails

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: carbon credit retirement sync fails.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck carbon credit retirement sync fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F12 — Sustainability audit evidence missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: sustainability audit evidence missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck sustainability audit evidence missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F13 — Greenhouse gas inventory ownership mapping wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: greenhouse gas inventory ownership mapping wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck greenhouse gas inventory ownership mapping wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F14 — Renewable certificate matching incorrect

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: renewable certificate matching incorrect.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck renewable certificate matching incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F15 — Carbon disclosure submission format rejected

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: carbon disclosure submission format rejected.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck carbon disclosure submission format rejected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F16 — Geospatial deforestation alerts delayed

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: geospatial deforestation alerts delayed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck geospatial deforestation alerts delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F17 — Climate risk dashboard stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: climate risk dashboard stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck climate risk dashboard stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F18 — Satellite imagery processing backlog

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: satellite imagery processing backlog.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck satellite imagery processing backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F19 — Lifecycle assessment boundary misconfigured

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: lifecycle assessment boundary misconfigured.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck lifecycle assessment boundary misconfigured against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D27-F20 — Company emissions data exposed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: company emissions data exposed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected climatetech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck company emissions data exposed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## AgriTech

### D28-F01 — Irrigation valve command not executed

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: irrigation valve command not executed.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck irrigation valve command not executed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F02 — Soil moisture sensor drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: soil moisture sensor drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck soil moisture sensor drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F03 — Drone crop imagery georeferencing error

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: drone crop imagery georeferencing error.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck drone crop imagery georeferencing error against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F04 — Pest detection false negative

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: pest detection false negative.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck pest detection false negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F05 — Farm equipment GPS precision loss

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: farm equipment gps precision loss.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck farm equipment gps precision loss against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F06 — Precision fertilizer prescription wrong units

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: precision fertilizer prescription wrong units.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck precision fertilizer prescription wrong units against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F07 — Harvest yield estimate model drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: harvest yield estimate model drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck harvest yield estimate model drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F08 — Livestock wearable tracker offline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: livestock wearable tracker offline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck livestock wearable tracker offline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F09 — Greenhouse climate controller oscillates

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: greenhouse climate controller oscillates.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck greenhouse climate controller oscillates against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F10 — Weather forecast feed stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: weather forecast feed stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck weather forecast feed stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F11 — Crop field boundary overlaps neighbor

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: crop field boundary overlaps neighbor.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck crop field boundary overlaps neighbor against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F12 — Supply-chain lot traceability breaks

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: supply-chain lot traceability breaks.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck supply-chain lot traceability breaks against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F13 — Farm machine firmware update stalls

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: farm machine firmware update stalls.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck farm machine firmware update stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F14 — Seed inventory reconciliation mismatch

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: seed inventory reconciliation mismatch.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck seed inventory reconciliation mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F15 — Automated spraying applied outside geofence

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: automated spraying applied outside geofence.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck automated spraying applied outside geofence against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F16 — Water usage accounting drops meter reads

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: water usage accounting drops meter reads.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck water usage accounting drops meter reads against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F17 — Equipment predictive maintenance alert missed

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: equipment predictive maintenance alert missed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck equipment predictive maintenance alert missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F18 — Drone mission exceeds battery safety margin

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: drone mission exceeds battery safety margin.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck drone mission exceeds battery safety margin against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F19 — Farm management offline sync overwrites edits

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: farm management offline sync overwrites edits.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck farm management offline sync overwrites edits against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D28-F20 — Agricultural worker personal data leaked

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: agricultural worker personal data leaked.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected agritech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck agricultural worker personal data leaked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## FoodTech

### D29-F01 — Food delivery order dispatched twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: food delivery order dispatched twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck food delivery order dispatched twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F02 — Restaurant menu availability stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: restaurant menu availability stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck restaurant menu availability stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F03 — Courier ETA model severely wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: courier eta model severely wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck courier eta model severely wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F04 — Cold food temperature excursions unflagged

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: cold food temperature excursions unflagged.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck cold food temperature excursions unflagged against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F05 — Allergen information incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: allergen information incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck allergen information incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F06 — Meal subscription renewal double-charge

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: meal subscription renewal double-charge.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck meal subscription renewal double-charge against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F07 — Delivery geofence wrongly marks arrival

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: delivery geofence wrongly marks arrival.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck delivery geofence wrongly marks arrival against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F08 — Restaurant tablet fails to receive order

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: restaurant tablet fails to receive order.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck restaurant tablet fails to receive order against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F09 — Kitchen ticket queue reorders priorities

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: kitchen ticket queue reorders priorities.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck kitchen ticket queue reorders priorities against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F10 — Grocery substitution price mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: grocery substitution price mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck grocery substitution price mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F11 — Restaurant inventory recipe depletion incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: restaurant inventory recipe depletion incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck restaurant inventory recipe depletion incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F12 — Food safety recall notice not propagated

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: food safety recall notice not propagated.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck food safety recall notice not propagated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F13 — Tip allocation formula wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: tip allocation formula wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck tip allocation formula wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F14 — Courier app GPS spoofing bypass

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: courier app gps spoofing bypass.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck courier app gps spoofing bypass against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F15 — Promo abuse creates negative order total

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: promo abuse creates negative order total.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck promo abuse creates negative order total against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F16 — Kitchen equipment telemetry unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: kitchen equipment telemetry unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck kitchen equipment telemetry unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F17 — Customer food order sent to wrong kitchen

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: customer food order sent to wrong kitchen.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck customer food order sent to wrong kitchen against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F18 — Supplier batch expiration missed

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: supplier batch expiration missed.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck supplier batch expiration missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F19 — Driver compensation ledger mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: driver compensation ledger mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck driver compensation ledger mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D29-F20 — Customer payment details logged

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: customer payment details logged.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected foodtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck customer payment details logged against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## HRTech

### D30-F01 — Payroll calculation misses overtime

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: payroll calculation misses overtime.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payroll calculation misses overtime against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F02 — Benefits enrollment status unsynced

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: benefits enrollment status unsynced.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck benefits enrollment status unsynced against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F03 — Applicant tracking duplicate profiles

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: applicant tracking duplicate profiles.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck applicant tracking duplicate profiles against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F04 — Time clock punches lost offline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: time clock punches lost offline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck time clock punches lost offline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F05 — Recruiting score model bias drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: recruiting score model bias drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck recruiting score model bias drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F06 — Payroll tax jurisdiction mapping wrong

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: payroll tax jurisdiction mapping wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payroll tax jurisdiction mapping wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F07 — Employee termination leaves access active

**Class:** Staleness / cache · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: employee termination leaves access active.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck employee termination leaves access active against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F08 — Offer letter generated with wrong salary

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: offer letter generated with wrong salary.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck offer letter generated with wrong salary against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F09 — Direct deposit routing changes not verified

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: direct deposit routing changes not verified.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck direct deposit routing changes not verified against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F10 — Performance review permissions expose peers

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: performance review permissions expose peers.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck performance review permissions expose peers against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F11 — Shift scheduling double-books workers

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: shift scheduling double-books workers.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck shift scheduling double-books workers against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F12 — Leave balance accrual incorrect

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: leave balance accrual incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck leave balance accrual incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F13 — SSO provisioning misses new hire

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: sso provisioning misses new hire.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck sso provisioning misses new hire against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F14 — Candidate interview invites wrong timezone

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: candidate interview invites wrong timezone.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck candidate interview invites wrong timezone against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F15 — Payroll batch misses banking cutoff

**Class:** Scheduling / batch windows · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: payroll batch misses banking cutoff.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck payroll batch misses banking cutoff against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F16 — Identity verification provider outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: identity verification provider outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck identity verification provider outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F17 — Background check status overwritten

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: background check status overwritten.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck background check status overwritten against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F18 — Compensation band rule stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: compensation band rule stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck compensation band rule stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F19 — Regulatory pay statement missing fields

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: regulatory pay statement missing fields.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck regulatory pay statement missing fields against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D30-F20 — Employee bank account exposed in export

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: employee bank account exposed in export.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected hrtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck employee bank account exposed in export against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## LegalTech

### D31-F01 — Contract clause extraction misses negation

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: contract clause extraction misses negation.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck contract clause extraction misses negation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F02 — Matter access permissions leak privileged docs

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: matter access permissions leak privileged docs.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck matter access permissions leak privileged docs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F03 — Court filing deadline timezone miscomputed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: court filing deadline timezone miscomputed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck court filing deadline timezone miscomputed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F04 — E-discovery document dedup removes evidence

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: e-discovery document dedup removes evidence.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck e-discovery document dedup removes evidence against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F05 — Legal citation retrieval returns outdated law

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: legal citation retrieval returns outdated law.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck legal citation retrieval returns outdated law against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F06 — Redaction fails to remove embedded text

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: redaction fails to remove embedded text.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck redaction fails to remove embedded text against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F07 — Contract signature workflow stalls

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: contract signature workflow stalls.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck contract signature workflow stalls against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F08 — Legal hold does not suspend deletion

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: legal hold does not suspend deletion.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck legal hold does not suspend deletion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F09 — Billing time entries duplicated

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: billing time entries duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck billing time entries duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F10 — Document version control forks

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: document version control forks.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck document version control forks against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F11 — Case docket feed misses update

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: case docket feed misses update.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck case docket feed misses update against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F12 — Conflict-of-interest screening misses party

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: conflict-of-interest screening misses party.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck conflict-of-interest screening misses party against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F13 — Electronic filing format rejected

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: electronic filing format rejected.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck electronic filing format rejected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F14 — Privilege review model mislabels documents

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: privilege review model mislabels documents.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck privilege review model mislabels documents against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F15 — Client trust accounting reconciliation mismatch

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: client trust accounting reconciliation mismatch.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck client trust accounting reconciliation mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F16 — Contract renewal notice delayed

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: contract renewal notice delayed.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck contract renewal notice delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F17 — Case search index leaks cross-matter records

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: case search index leaks cross-matter records.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck case search index leaks cross-matter records against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F18 — Retention schedule deletes active matter

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: retention schedule deletes active matter.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck retention schedule deletes active matter against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F19 — OCR error changes monetary clause

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: ocr error changes monetary clause.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck ocr error changes monetary clause against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D31-F20 — Audit logs omit document downloads

**Class:** Audit / compliance · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: audit logs omit document downloads.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected legaltech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck audit logs omit document downloads against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## GovTech

### D32-F01 — Public benefits eligibility incorrectly denied

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: public benefits eligibility incorrectly denied.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck public benefits eligibility incorrectly denied against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F02 — Citizen identity verification unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: citizen identity verification unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck citizen identity verification unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F03 — Tax filing portal peak overload

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: tax filing portal peak overload.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck tax filing portal peak overload against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F04 — Permit workflow drops approval

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: permit workflow drops approval.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck permit workflow drops approval against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F05 — Emergency alert reaches wrong geography

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: emergency alert reaches wrong geography.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck emergency alert reaches wrong geography against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F06 — Voter registration data sync conflict

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: voter registration data sync conflict.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck voter registration data sync conflict against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F07 — Public records redaction incomplete

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: public records redaction incomplete.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck public records redaction incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F08 — Grant payments duplicated

**Class:** Consistency / duplicate processing · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: grant payments duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck grant payments duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F09 — Caseworker access not restricted by role

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: caseworker access not restricted by role.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck caseworker access not restricted by role against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F10 — Procurement bid deadline miscomputed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: procurement bid deadline miscomputed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck procurement bid deadline miscomputed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F11 — Government site accessibility regression

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: government site accessibility regression.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck government site accessibility regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F12 — Emergency services dispatch mapping stale

**Class:** Data integrity / mapping · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: emergency services dispatch mapping stale.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck emergency services dispatch mapping stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F13 — License renewal notifications not sent

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: license renewal notifications not sent.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck license renewal notifications not sent against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F14 — School district funding report inaccurate

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: school district funding report inaccurate.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck school district funding report inaccurate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F15 — Civic open data API exposes private fields

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: civic open data api exposes private fields.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck civic open data api exposes private fields against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F16 — Public housing waitlist ranking wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: public housing waitlist ranking wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck public housing waitlist ranking wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F17 — Government audit trail incomplete

**Class:** Audit / compliance · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: government audit trail incomplete.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck government audit trail incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F18 — Multilingual form translation loses meaning

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: multilingual form translation loses meaning.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck multilingual form translation loses meaning against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F19 — Court payment receipt not generated

**Class:** Financial / numeric correctness · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: court payment receipt not generated.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause affected financial mutations; reconcile authoritative ledger and seek authorized approval before reversals, refunds, settlement, or balance changes.
- **Verification:** Recheck court payment receipt not generated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D32-F20 — Interagency records feed missing events

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: interagency records feed missing events.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected govtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck interagency records feed missing events against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Industrial Tech

### D33-F01 — PLC command acknowledgment lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: plc command acknowledgment lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck plc command acknowledgment lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F02 — Factory sensor calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: factory sensor calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck factory sensor calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F03 — MES production counts duplicated

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: mes production counts duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck mes production counts duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F04 — Industrial gateway loses Modbus connection

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: industrial gateway loses modbus connection.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck industrial gateway loses modbus connection against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F05 — Robotic arm collision safety interlock missed

**Class:** Race / concurrent state · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: robotic arm collision safety interlock missed.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck robotic arm collision safety interlock missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F06 — OEE dashboard stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: oee dashboard stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck oee dashboard stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F07 — Assembly recipe pushed to wrong line

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: assembly recipe pushed to wrong line.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck assembly recipe pushed to wrong line against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F08 — Manufacturing quality inspection false negative

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: manufacturing quality inspection false negative.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck manufacturing quality inspection false negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F09 — Digital twin diverges from physical asset

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: digital twin diverges from physical asset.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck digital twin diverges from physical asset against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F10 — SCADA alarm flood hides critical alarm

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: scada alarm flood hides critical alarm.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck scada alarm flood hides critical alarm against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F11 — Equipment predictive maintenance false negative

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: equipment predictive maintenance false negative.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck equipment predictive maintenance false negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F12 — Production batch traceability missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: production batch traceability missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck production batch traceability missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F13 — Industrial IoT certificate expires

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: industrial iot certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck industrial iot certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F14 — Machine uptime events out of order

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: machine uptime events out of order.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck machine uptime events out of order against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F15 — Spare parts consumption inventory inaccurate

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: spare parts consumption inventory inaccurate.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck spare parts consumption inventory inaccurate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F16 — Control system firmware incompatibility

**Class:** Rollout / compatibility · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: control system firmware incompatibility.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck control system firmware incompatibility against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F17 — Hazardous temperature excursion missed

**Class:** Location / time / units · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: hazardous temperature excursion missed.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck hazardous temperature excursion missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F18 — Industrial historian data gap

**Class:** Abuse / security detection · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: industrial historian data gap.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply reversible rate limits and route to security team.
- **Verification:** Recheck industrial historian data gap against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F19 — Manufacturing scheduling deadlock

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: manufacturing scheduling deadlock.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck manufacturing scheduling deadlock against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D33-F20 — Operational technology network segmentation broken

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: operational technology network segmentation broken.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected industrial tech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck operational technology network segmentation broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Robotics

### D34-F01 — Robot localization drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: robot localization drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck robot localization drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F02 — Autonomous navigation route blocked

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: autonomous navigation route blocked.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck autonomous navigation route blocked against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F03 — Arm joint torque limit exceeded

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: arm joint torque limit exceeded.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck arm joint torque limit exceeded against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F04 — Fleet dispatcher assigns same task twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: fleet dispatcher assigns same task twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck fleet dispatcher assigns same task twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F05 — Obstacle detector misses human

**Class:** Model / rules drift · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: obstacle detector misses human.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck obstacle detector misses human against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F06 — Battery low shutdown during mission

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: battery low shutdown during mission.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rotate credential through approved secret pipeline.
- **Verification:** Recheck battery low shutdown during mission against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F07 — Motor encoder sensor mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: motor encoder sensor mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck motor encoder sensor mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F08 — ROS message queue congestion

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: ros message queue congestion.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck ros message queue congestion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F09 — Manipulator grip force miscalibrated

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: manipulator grip force miscalibrated.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck manipulator grip force miscalibrated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F10 — Robot firmware update interrupts operation

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: robot firmware update interrupts operation.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck robot firmware update interrupts operation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F11 — Multi-robot map synchronization conflict

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: multi-robot map synchronization conflict.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck multi-robot map synchronization conflict against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F12 — SLAM loop closure causes map jump

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: slam loop closure causes map jump.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck slam loop closure causes map jump against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F13 — Remote emergency-stop signal delayed

**Class:** Event ordering / async workflow · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: remote emergency-stop signal delayed.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck remote emergency-stop signal delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F14 — Charging dock alignment failure

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: charging dock alignment failure.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck charging dock alignment failure against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F15 — Actuator thermal overload undetected

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: actuator thermal overload undetected.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck actuator thermal overload undetected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F16 — Warehouse robot inventory pickup mismatch

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: warehouse robot inventory pickup mismatch.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck warehouse robot inventory pickup mismatch against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F17 — Robot cloud control certificate expires

**Class:** Availability / timeouts · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: robot cloud control certificate expires.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck robot cloud control certificate expires against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F18 — Mission recovery resumes unsafe state

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: mission recovery resumes unsafe state.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck mission recovery resumes unsafe state against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F19 — Camera inference latency exceeds control deadline

**Class:** Latency / capacity · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: camera inference latency exceeds control deadline.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck camera inference latency exceeds control deadline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D34-F20 — Robot operational logs lost offline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: robot operational logs lost offline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected robotics entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck robot operational logs lost offline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Semiconductors

### D35-F01 — Chip fabrication yield alert misses excursion

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: chip fabrication yield alert misses excursion.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck chip fabrication yield alert misses excursion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F02 — EDA placement tool crashes mid-run

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: eda placement tool crashes mid-run.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck eda placement tool crashes mid-run against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F03 — Wafer lot genealogy incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: wafer lot genealogy incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck wafer lot genealogy incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F04 — Lithography alignment calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: lithography alignment calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck lithography alignment calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F05 — Process control sensor out of tolerance

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: process control sensor out of tolerance.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck process control sensor out of tolerance against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F06 — Mask revision deployed to wrong recipe

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: mask revision deployed to wrong recipe.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck mask revision deployed to wrong recipe against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F07 — Firmware microcode regression

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: firmware microcode regression.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck firmware microcode regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F08 — GPU driver kernel hangs

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: gpu driver kernel hangs.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck gpu driver kernel hangs against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F09 — DRAM memory bit-error spike

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: dram memory bit-error spike.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck dram memory bit-error spike against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F10 — Chip test binning classification wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: chip test binning classification wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck chip test binning classification wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F11 — Foundry capacity allocation conflict

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: foundry capacity allocation conflict.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck foundry capacity allocation conflict against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F12 — Wafer equipment predictive maintenance misses fault

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: wafer equipment predictive maintenance misses fault.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck wafer equipment predictive maintenance misses fault against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F13 — Timing closure result not reproducible

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: timing closure result not reproducible.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck timing closure result not reproducible against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F14 — Thermal throttling model underestimates heat

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: thermal throttling model underestimates heat.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck thermal throttling model underestimates heat against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F15 — FPGA bitstream wrong hardware revision

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: fpga bitstream wrong hardware revision.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck fpga bitstream wrong hardware revision against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F16 — Hardware trace captures incomplete data

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: hardware trace captures incomplete data.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck hardware trace captures incomplete data against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F17 — Supply chain component counterfeit signal missed

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: supply chain component counterfeit signal missed.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck supply chain component counterfeit signal missed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F18 — Semiconductor license server outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: semiconductor license server outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck semiconductor license server outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F19 — Chip packaging defect detection false negative

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: chip packaging defect detection false negative.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck chip packaging defect detection false negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D35-F20 — Design IP access control breach

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: design ip access control breach.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected semiconductors entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck design ip access control breach against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Consumer Technology

### D36-F01 — Mobile OS update causes boot loop

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: mobile os update causes boot loop.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck mobile os update causes boot loop against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F02 — App push notifications silently stop

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: app push notifications silently stop.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck app push notifications silently stop against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F03 — Photo cloud sync duplicates media

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: photo cloud sync duplicates media.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck photo cloud sync duplicates media against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F04 — Device Bluetooth pairing fails

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: device bluetooth pairing fails.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck device bluetooth pairing fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F05 — Phone battery drains after update

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: phone battery drains after update.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck phone battery drains after update against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F06 — Operating system permission prompt bypassed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: operating system permission prompt bypassed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck operating system permission prompt bypassed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F07 — App store purchase restore fails

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: app store purchase restore fails.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck app store purchase restore fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F08 — Personal assistant activates on wrong wake word

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: personal assistant activates on wrong wake word.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck personal assistant activates on wrong wake word against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F09 — Device backup restore corrupts messages

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: device backup restore corrupts messages.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck device backup restore corrupts messages against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F10 — Biometric authentication error rate rises

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: biometric authentication error rate rises.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck biometric authentication error rate rises against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F11 — Cloud clipboard leaks cross-device content

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: cloud clipboard leaks cross-device content.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck cloud clipboard leaks cross-device content against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F12 — Firmware updates leave devices unresponsive

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: firmware updates leave devices unresponsive.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck firmware updates leave devices unresponsive against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F13 — Mobile app crashes on specific device model

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: mobile app crashes on specific device model.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck mobile app crashes on specific device model against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F14 — Keyboard autocorrect model regression

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: keyboard autocorrect model regression.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck keyboard autocorrect model regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F15 — Cross-device handoff session fails

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: cross-device handoff session fails.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck cross-device handoff session fails against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F16 — Location service reports stale coordinates

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: location service reports stale coordinates.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck location service reports stale coordinates against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F17 — Home automation commands go to wrong device

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: home automation commands go to wrong device.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck home automation commands go to wrong device against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F18 — Consumer account takeover due to recovery bug

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: consumer account takeover due to recovery bug.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck consumer account takeover due to recovery bug against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F19 — Screen reader accessibility breaks

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: screen reader accessibility breaks.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck screen reader accessibility breaks against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D36-F20 — Device diagnostics upload private files

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: device diagnostics upload private files.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected consumer technology entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Revoke access/credential; isolate exposure; open security incident.
- **Verification:** Recheck device diagnostics upload private files against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Enterprise IT

### D37-F01 — Active Directory replication lag

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: active directory replication lag.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck active directory replication lag against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F02 — Corporate DNS outage

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: corporate dns outage.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck corporate dns outage against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F03 — VPN concentrator capacity exhausted

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: vpn concentrator capacity exhausted.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck vpn concentrator capacity exhausted against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F04 — Endpoint patch deployment breaks business app

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: endpoint patch deployment breaks business app.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck endpoint patch deployment breaks business app against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F05 — Backup restore fails validation

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: backup restore fails validation.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck backup restore fails validation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F06 — ERP integration event stuck

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: erp integration event stuck.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck erp integration event stuck against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F07 — Employee provisioning leaves orphaned accounts

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: employee provisioning leaves orphaned accounts.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck employee provisioning leaves orphaned accounts against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F08 — Internal database storage fills

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: internal database storage fills.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck internal database storage fills against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F09 — Enterprise email routing rejects messages

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: enterprise email routing rejects messages.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck enterprise email routing rejects messages against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F10 — Disaster recovery failover misconfigured

**Class:** Business continuity / recovery · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Recovery path fails controlled tests; scenario-specific sentinel: disaster recovery failover misconfigured.
- **Evidence / instrumentation:** Backup restore validation; RTO/RPO tests; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken backups; stale failover routing; DR drift
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Run approved restore drills; avoid destructive automatic failover.
- **Verification:** Recheck disaster recovery failover misconfigured against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F11 — Directory group membership stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: directory group membership stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck directory group membership stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F12 — Certificate renewal forgotten

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: certificate renewal forgotten.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck certificate renewal forgotten against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F13 — ITSM incident routing loops

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: itsm incident routing loops.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck itsm incident routing loops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F14 — Corporate asset inventory inaccurate

**Class:** Financial / numeric correctness · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Calculated values violate domain tolerances; scenario-specific sentinel: corporate asset inventory inaccurate.
- **Evidence / instrumentation:** Golden-case validation; reconciliation; threshold drift; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rounding; units; rule/version mismatch
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Stop affected posting and run shadow recomputation.
- **Verification:** Recheck corporate asset inventory inaccurate against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F15 — Legacy SOAP service payload incompatible

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: legacy soap service payload incompatible.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck legacy soap service payload incompatible against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F16 — Internal network firewall rule regression

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: internal network firewall rule regression.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck internal network firewall rule regression against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F17 — Print service outage across campus

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: print service outage across campus.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck print service outage across campus against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F18 — Database failover creates split-brain

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: database failover creates split-brain.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck database failover creates split-brain against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F19 — Enterprise monitoring collector stops

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: enterprise monitoring collector stops.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck enterprise monitoring collector stops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D37-F20 — Admin credentials exposed in ticket attachment

**Class:** Authentication / credentials · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Auth failures spike; token/cert nearing expiration; scenario-specific sentinel: admin credentials exposed in ticket attachment.
- **Evidence / instrumentation:** Auth error code metrics; secret/cert expiry alert; compare affected entity IDs and last-known-good state.
- **Likely causes:** Expired secret; broken identity federation; key rotation
- **Triage:** Identify affected enterprise it entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck admin credentials exposed in ticket attachment against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## SportsTech

### D38-F01 — Live score feed delayed

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: live score feed delayed.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck live score feed delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F02 — Play-by-play event ordering wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: play-by-play event ordering wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck play-by-play event ordering wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F03 — Athlete wearable sensor missing samples

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: athlete wearable sensor missing samples.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck athlete wearable sensor missing samples against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F04 — Ticketing oversells venue section

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: ticketing oversells venue section.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck ticketing oversells venue section against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F05 — Video replay timestamp desync

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: video replay timestamp desync.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck video replay timestamp desync against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F06 — Fantasy points computation incorrect

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: fantasy points computation incorrect.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck fantasy points computation incorrect against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F07 — Sports betting data feed inconsistent

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: sports betting data feed inconsistent.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck sports betting data feed inconsistent against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F08 — Venue gate scanner offline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: venue gate scanner offline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck venue gate scanner offline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F09 — Fan loyalty points credited twice

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: fan loyalty points credited twice.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck fan loyalty points credited twice against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F10 — Athlete training load model drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: athlete training load model drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck athlete training load model drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F11 — Player identity mapping wrong in stats

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: player identity mapping wrong in stats.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck player identity mapping wrong in stats against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F12 — Stadium Wi-Fi saturation

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: stadium wi-fi saturation.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck stadium wi-fi saturation against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F13 — Broadcast tracking camera calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: broadcast tracking camera calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck broadcast tracking camera calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F14 — Team scouting dashboard stale

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: team scouting dashboard stale.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck team scouting dashboard stale against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F15 — Competition standings tie-break miscomputed

**Class:** Rollout / compatibility · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: competition standings tie-break miscomputed.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Halt rollout, canary rollback when backward-compatible.
- **Verification:** Recheck competition standings tie-break miscomputed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F16 — Fan engagement chat moderation backlog

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: fan engagement chat moderation backlog.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck fan engagement chat moderation backlog against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F17 — Ticket transfer QR invalid

**Class:** Location / time / units · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Timestamps, geographies or units inconsistent; scenario-specific sentinel: ticket transfer qr invalid.
- **Evidence / instrumentation:** Clock-offset; timezone test matrix; geofence sanity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Timezone, clock sync, CRS or unit-conversion bug
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Disable incorrect calculation; apply tested normalization.
- **Verification:** Recheck ticket transfer qr invalid against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F18 — Performance analytics query slow during game

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: performance analytics query slow during game.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck performance analytics query slow during game against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F19 — Player medical data exposed

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: player medical data exposed.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck player medical data exposed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D38-F20 — Referee decision event not propagated

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: referee decision event not propagated.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected sportstech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck referee decision event not propagated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Biotech

### D39-F01 — Sequencing read quality drops

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: sequencing read quality drops.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck sequencing read quality drops against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F02 — Genomic sample swapped in pipeline

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: genomic sample swapped in pipeline.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck genomic sample swapped in pipeline against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F03 — Bioinformatics workflow fails reference alignment

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: bioinformatics workflow fails reference alignment.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck bioinformatics workflow fails reference alignment against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F04 — Lab information management barcode collision

**Class:** Latency / capacity · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: lab information management barcode collision.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck lab information management barcode collision against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F05 — Cell assay instrument calibration drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: cell assay instrument calibration drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck cell assay instrument calibration drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F06 — Drug discovery screening model drift

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: drug discovery screening model drift.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck drug discovery screening model drift against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F07 — Clinical trial randomization service unavailable

**Class:** Availability / timeouts · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Availability or completion rate drops; scenario-specific sentinel: clinical trial randomization service unavailable.
- **Evidence / instrumentation:** Error budget burn; synthetic probe; timeout histogram; compare affected entity IDs and last-known-good state.
- **Likely causes:** Unavailable dependency; hung call; retry amplification
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Circuit-break or reroute to healthy dependency; retain work.
- **Verification:** Recheck clinical trial randomization service unavailable against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F08 — Research sample cold-storage excursion

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: research sample cold-storage excursion.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck research sample cold-storage excursion against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F09 — Gene variant annotation database outdated

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: gene variant annotation database outdated.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck gene variant annotation database outdated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F10 — Lab reagent lot traceability broken

**Class:** Race / concurrent state · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Conflicting state transitions detected; scenario-specific sentinel: lab reagent lot traceability broken.
- **Evidence / instrumentation:** Optimistic lock conflicts; state machine invariant monitor; compare affected entity IDs and last-known-good state.
- **Likely causes:** Missing locking, optimistic versioning or atomic writes
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Pause competing writers; use transactional replay after approval.
- **Verification:** Recheck lab reagent lot traceability broken against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F11 — Proteomics pipeline missing spectra

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: proteomics pipeline missing spectra.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck proteomics pipeline missing spectra against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F12 — Molecular simulation checkpoint corrupt

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: molecular simulation checkpoint corrupt.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck molecular simulation checkpoint corrupt against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F13 — Clinical research consent tracking incomplete

**Class:** Event ordering / async workflow · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Workflow state or message sequence invalid; scenario-specific sentinel: clinical research consent tracking incomplete.
- **Evidence / instrumentation:** Sequence-gap counters; consumer lag; DLQ; compare affected entity IDs and last-known-good state.
- **Likely causes:** At-least-once delivery; reorder; offset or checkpoint issue
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Park invalid messages; replay after state validation.
- **Verification:** Recheck clinical research consent tracking incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F14 — Sample chain-of-custody event lost

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: sample chain-of-custody event lost.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck sample chain-of-custody event lost against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F15 — Biohazard monitoring alert delayed

**Class:** Alerting / monitoring · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: biohazard monitoring alert delayed.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Fail to certified safe operating state as designed; alert trained operator; do not let an AI agent directly command safety-critical equipment.
- **Verification:** Recheck biohazard monitoring alert delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F16 — High-throughput assay batch effect unnoticed

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: high-throughput assay batch effect unnoticed.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck high-throughput assay batch effect unnoticed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F17 — Research results database permissions leak

**Class:** Privacy / authorization · **Default severity:** High · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: research results database permissions leak.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck research results database permissions leak against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F18 — Variant calling parameters mismatched by cohort

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: variant calling parameters mismatched by cohort.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck variant calling parameters mismatched by cohort against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F19 — Lab robot pipetting calibration wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: lab robot pipetting calibration wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck lab robot pipetting calibration wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D39-F20 — Regulatory submission data lineage missing

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: regulatory submission data lineage missing.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected biotech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck regulatory submission data lineage missing against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## RegTech

### D40-F01 — AML transaction monitoring rule misses alert

**Class:** Alerting / monitoring · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Expected alerts absent or noisy; scenario-specific sentinel: aml transaction monitoring rule misses alert.
- **Evidence / instrumentation:** Synthetic canary alert; missing heartbeat; compare affected entity IDs and last-known-good state.
- **Likely causes:** Signal routing broken; monitoring blind spots
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Restore telemetry/alert path and validate test alert.
- **Verification:** Recheck aml transaction monitoring rule misses alert against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F02 — Sanctions list update delayed

**Class:** Rollout / compatibility · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Incident correlates with deployed version; scenario-specific sentinel: sanctions list update delayed.
- **Evidence / instrumentation:** Release correlation; canary SLO; version-by-error rate; compare affected entity IDs and last-known-good state.
- **Likely causes:** Incompatible client, schema or firmware revision
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck sanctions list update delayed against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F03 — KYC identity verification falsely rejects users

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: kyc identity verification falsely rejects users.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck kyc identity verification falsely rejects users against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F04 — Regulatory report schema rejected

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: regulatory report schema rejected.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck regulatory report schema rejected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F05 — Suspicious activity case duplicated

**Class:** Consistency / duplicate processing · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Event, request or ledger counts diverge; scenario-specific sentinel: suspicious activity case duplicated.
- **Evidence / instrumentation:** Reconciliation query; idempotency-key collision and uniqueness metrics; compare affected entity IDs and last-known-good state.
- **Likely causes:** Retries without durable idempotency; concurrent updates
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Reconcile against system of record; isolate repeat events.
- **Verification:** Recheck suspicious activity case duplicated against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F06 — Compliance evidence retention gap

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: compliance evidence retention gap.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck compliance evidence retention gap against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F07 — PEP screening fuzzy match false negative

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: pep screening fuzzy match false negative.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck pep screening fuzzy match false negative against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F08 — Risk rating calculated on stale customer data

**Class:** Staleness / cache · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Freshness age exceeds threshold; scenario-specific sentinel: risk rating calculated on stale customer data.
- **Evidence / instrumentation:** Age since last valid update; source-to-read diff; compare affected entity IDs and last-known-good state.
- **Likely causes:** Failed invalidation; delayed replication; stuck refresh
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Invalidate scoped cache and restart verified refresh.
- **Verification:** Recheck risk rating calculated on stale customer data against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F09 — Transaction monitoring ingestion lag

**Class:** Latency / capacity · **Default severity:** Medium · **Automation:** Investigate / propose fix

- **Detection:** Tail latency exceeds service SLO; scenario-specific sentinel: transaction monitoring ingestion lag.
- **Evidence / instrumentation:** p95/p99; queue age; saturation; load test; compare affected entity IDs and last-known-good state.
- **Likely causes:** Queue saturation; excessive fanout; insufficient capacity
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Apply bounded concurrency and capacity scaling within policy.
- **Verification:** Recheck transaction monitoring ingestion lag against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F10 — Regulatory jurisdiction mapping wrong

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: regulatory jurisdiction mapping wrong.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck regulatory jurisdiction mapping wrong against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F11 — Consent record not linked to user

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: consent record not linked to user.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck consent record not linked to user against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F12 — Watchlist provider times out

**Class:** External dependency / integration · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Partner API errors or incompatible payloads rise; scenario-specific sentinel: watchlist provider times out.
- **Evidence / instrumentation:** Dependency status; schema contract tests; DLQ depth; compare affected entity IDs and last-known-good state.
- **Likely causes:** Upstream outage; version change; contract drift
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Use fallback/dead-letter queue; page partner owner.
- **Verification:** Recheck watchlist provider times out against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F13 — Policy exception approval not recorded

**Class:** Audit / compliance · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Required evidence, status or reports missing; scenario-specific sentinel: policy exception approval not recorded.
- **Evidence / instrumentation:** Audit completeness; report checksum; retention monitors; compare affected entity IDs and last-known-good state.
- **Likely causes:** Lost audit hook; retention misconfiguration; failed export
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Preserve immutable inputs and regenerate verified evidence.
- **Verification:** Recheck policy exception approval not recorded against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F14 — Compliance audit log tampering undetected

**Class:** Model / rules drift · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: compliance audit log tampering undetected.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck compliance audit log tampering undetected against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F15 — Fraud case escalation queue starved

**Class:** Abuse / security detection · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Fraud, abuse or intrusion anomalies spike; scenario-specific sentinel: fraud case escalation queue starved.
- **Evidence / instrumentation:** Anomaly alerts; rate limits; detection coverage; compare affected entity IDs and last-known-good state.
- **Likely causes:** Rule gaps; adversarial behavior; weak rate limits
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck fraud case escalation queue starved against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F16 — Beneficial ownership graph incomplete

**Class:** Resource exhaustion · **Default severity:** Medium · **Automation:** Guarded automatic action

- **Detection:** Memory, disk or connection pressure persists; scenario-specific sentinel: beneficial ownership graph incomplete.
- **Evidence / instrumentation:** OOM; GC; FD count; DB pool; disk capacity; compare affected entity IDs and last-known-good state.
- **Likely causes:** Leak, unbounded queue, missing capacity limits
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Scale or recycle stateless worker under safeguards.
- **Verification:** Recheck beneficial ownership graph incomplete against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F17 — Customer screening wrongly blocked due to homonym

**Class:** Data integrity / mapping · **Default severity:** High · **Automation:** Investigate / propose fix

- **Detection:** Invalid or missing domain data rises; scenario-specific sentinel: customer screening wrongly blocked due to homonym.
- **Evidence / instrumentation:** Contract test; reconciliation diff; field-level validation; compare affected entity IDs and last-known-good state.
- **Likely causes:** Schema mismatch; incorrect mapping; silent data loss
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Quarantine affected records; validate mapping; replay verified input.
- **Verification:** Recheck customer screening wrongly blocked due to homonym against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F18 — Case management export leaks confidential data

**Class:** Privacy / authorization · **Default severity:** Critical · **Automation:** Human approval required

- **Detection:** Unauthorized access pattern or data exposure; scenario-specific sentinel: case management export leaks confidential data.
- **Evidence / instrumentation:** Authorization deny/allow anomalies; DLP scan; audit; compare affected entity IDs and last-known-good state.
- **Likely causes:** Broken object-level authorization; masking regression
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Contain affected access through preapproved controls; preserve forensic evidence and escalate to security/privacy incident response.
- **Verification:** Recheck case management export leaks confidential data against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F19 — Regulatory deadline reminder not triggered

**Class:** Scheduling / batch windows · **Default severity:** High · **Automation:** Guarded automatic action

- **Detection:** Job misses contractual or processing deadline; scenario-specific sentinel: regulatory deadline reminder not triggered.
- **Evidence / instrumentation:** Last-success age; DAG SLA; run completeness; compare affected entity IDs and last-known-good state.
- **Likely causes:** Job orchestration failure; missed schedule; resource contention
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Retry idempotent batch if window and dependencies safe.
- **Verification:** Recheck regulatory deadline reminder not triggered against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

### D40-F20 — Compliance model rule change not versioned

**Class:** Model / rules drift · **Default severity:** Medium · **Automation:** Human approval required

- **Detection:** Quality metrics shift from approved baseline; scenario-specific sentinel: compliance model rule change not versioned.
- **Evidence / instrumentation:** Drift scores; shadow test; false-positive/negative trend; compare affected entity IDs and last-known-good state.
- **Likely causes:** Training data shift; changed business rules; untested rollout
- **Triage:** Identify affected regtech entities; correlate deployment/change history; determine blast radius; verify system-of-record invariants.
- **Potential remediation:** Rollback model/rules behind gated evaluation.
- **Verification:** Recheck compliance model rule change not versioned against independent source of truth; confirm error/SLO and integrity signals recover; monitor for recurrence.

## Implementation guidance

1. Model incidents as observations, hypotheses, experiments, actions, verification and audit artifacts.
2. Bind every candidate detector to real event schemas, business invariants, sample payloads, service owners and severity thresholds.
3. Correlate error spikes with releases and dependency incidents; avoid assuming the first matching detector gives the root cause.
4. Keep AI diagnostic reasoning separate from deterministic policy enforcement, approvals and remediation execution.
5. Use sandbox replay, canary and fault-injection validation; never use live data or financial/physical actions as exploratory tests.
6. Measure precision, recall, MTTD, MTTR, false positive rate and bad-remediation rate per domain.
