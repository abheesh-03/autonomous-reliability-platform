# Phase 3F — End-to-End Acceptance and Handoff

Phase 3F is the **closure milestone** for the Phase 3 incident-management
foundation (3A–3E). It does not add new product capability. It audits
the existing real verification coverage, closes one genuinely missing
cross-system assertion in the existing acceptance test, and gives
another engineer a single document to pick up the system from.

If you are looking for *how a capability was built*, see the
phase-specific docs linked from the matrix below. This document is
about *how to run and trust what already exists*.

## 1. Phase 3 acceptance matrix

Every row below is a REAL check against a REAL PostgreSQL database and
(where noted) a REAL running Alertmanager/Prometheus/otel-collector —
never a mock, never an in-memory substitute. All of these run in CI
(`.github/workflows/ci.yml`) on every push, in the order listed.

| Capability | Implemented in | Real verification gate | What it actually proves |
|---|---|---|---|
| Incident schema + persistence (3A) | `database/migrations/V1__create_incident_schema.sql` | `make verify-persistence` (`scripts/verify-persistence.sh`) | Schema/constraints/indexes exist; invalid severity/status/blank fields rejected with the exact `SQLSTATE`; duplicate-active-incident uniqueness enforced; a resolved incident's fingerprint can recur; migrations are safe to rerun; data survives a real PostgreSQL restart |
| Occurrence watermark (3A post-review) | `database/migrations/V2__add_occurrence_watermark.sql` | `make verify-incident-lifecycle` (`scripts/verify-incident-lifecycle.sh`, sections 8–11) | `occurrence_starts_at` correctly distinguishes a newer firing, a stale/delayed replay, and a genuine recurrence |
| Read-only control-plane API (3B) | `services/control-plane` (`GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`, `/health/live`, `/health/ready`) | `make verify-control-plane` (`scripts/verify-control-plane.sh`) | Real HTTP responses match the real database row-for-row; filtering, pagination, and deterministic ordering are correct; 404/422 on bad input; read endpoints never mutate; service recovers readiness after a real PostgreSQL restart without a manual restart |
| Authenticated Alertmanager webhook ingestion (3C) | `POST /internal/v1/alertmanager/webhook` | `make verify-webhook-ingestion` (`scripts/verify-webhook-ingestion.sh`) | Auth required (401 without/with a wrong token); payload validation (422); firing alert atomically upserted and deduplicated per-fingerprint; a repeated firing updates in place; a resolved notification with no matching active incident is a no-op; a PostgreSQL outage during delivery returns 503 and writes nothing, then resumes on its own |
| Incident lifecycle / state machine + source-driven resolution (3D) | `PATCH /api/v1/incidents/{id}/status`, `domain/lifecycle.py`, webhook resolution path | `make verify-incident-lifecycle` (`scripts/verify-incident-lifecycle.sh`) | Every permitted transition works via the real HTTP endpoint and matches the database; illegal transitions and a stale `expected_status` are rejected (409) with the row unchanged; access control enforced; optimistic concurrency is race-free under 10 genuinely concurrent real requests; state survives a real PostgreSQL restart |
| Append-only incident audit trail (3E) | `database/migrations/V3__create_incident_audit.sql`, `V4__harden_incident_audit.sql`, `GET /api/v1/incidents/{id}/events` | `make verify-incident-audit` (`scripts/verify-incident-audit.sh`) | Direct `UPDATE`/`DELETE`/`TRUNCATE` against `reliability.incident_events` are all rejected at the database level; an audit-insert failure rolls back its incident mutation in the same real transaction; every accepted mutation produces exactly the right event with the right attribution; rejected/ignored/no-op operations add nothing; a concurrent-PATCH race produces exactly one event; pagination is correct beyond the first page; history survives a real PostgreSQL restart |
| **Full cross-system chain**: Collector outage → real Prometheus alert → real Alertmanager webhook → persisted incident → Collector recovery → automatic resolution → correctly-attributed audit history (3C/3D/3E integration, closed by 3F) | `scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`, `scripts/verify-ingestion.py` | `make verify-alert-ingestion` | The ONE end-to-end gate: a real, controlled `otel-collector` outage drives a real Prometheus rule to `firing`, Alertmanager delivers its own real webhook (not a synthetic POST), the resulting incident is correctly mapped and identity-matched to the real alert fingerprint; after recovery, Alertmanager's own real resolved webhook transitions that *exact* incident to `resolved`; the incident's real, persisted audit trail is read back and confirmed correctly attributed to `alertmanager` throughout, with its `created` event's own metadata traced back to the real Alertmanager fingerprint (the 3F addition — see §3) |
| Observability foundation (Phase 2, prerequisite for all of the above) | OTel Collector, Prometheus, Grafana, Tempo, Loki, Alloy, Alertmanager | `make verify-observability` plus the individual CI steps (metrics, traces, logs, dashboards, alert rules) | Unchanged by Phase 3; listed for completeness since every Phase 3 gate above runs on top of it |

No new verifier scripts were created for Phase 3F. The matrix above
maps existing gates — creating a new one just to grow the test count
would violate this phase's own scope.

## 2. The one coverage gap found, and what was done about it

Auditing `scripts/verify-ingestion.py` against the acceptance matrix
above surfaced one real, narrow gap in the final cross-system row.

**What was already proven**: the incident *row* was matched to the
real Alertmanager fingerprint (`active_incidents_by_fingerprint` keys
incidents by their own `source_fingerprint` column), and the exact
same incident id was carried through to the post-recovery resolution
check.

**What was never checked**: `confirm-resolved` reads the incident's
*audit trail* (`GET /api/v1/incidents/{id}/events`) and asserts a
`created` event exists with `actor_type='alertmanager'` — but nothing
ever read that event's own `metadata.source_fingerprint` field back
and compared it to the real alert's fingerprint. The audit *event*
(the thing this check actually reads) was never itself tied back to
the real alert's identity — only the incident row, a different table,
had been.

This matters because `metadata.source_fingerprint` exists in the
schema *specifically* for this purpose (see
`services/control-plane/src/control_plane/repositories/incident_repository.py`'s
"Allowlisted, structured metadata only" comment) — it was written by
the application and never read back by any real integration test.

**Fix** (`scripts/verify-ingestion.py`, narrow extension of the
existing acceptance path, no new test added):

- `incident-from-alert`'s `--ids-out` file now writes
  `incident_id<TAB>fingerprint` pairs instead of bare incident ids.
- `confirm-resolved` parses that pair and passes the expected
  fingerprint into `verify_audit_trail`, which now asserts the
  `created` event's `metadata.source_fingerprint` equals the real
  fingerprint Alertmanager reported for that exact alert — failing
  loudly if the persisted audit record cannot be traced back to the
  real alert that is supposed to have produced it.

No second Collector outage, no new subcommand, no new Make target —
this extends the one existing acceptance path exactly as instructed.
Re-run end to end against a real stack (`make verify-alert-ingestion`,
2026-10-03): passed, including the new check (see validation evidence
in the Phase 3F implementation report).

Everything else in the matrix was already correct and is intentionally
left untouched — in particular, this document does not re-litigate or
duplicate anything `scripts/verify-persistence.sh`,
`scripts/verify-control-plane.sh`, `scripts/verify-webhook-ingestion.sh`,
or `scripts/verify-incident-audit.sh` already prove on their own.

## 3. Operations runbook

Everything below uses only placeholders. **Never commit or print a
real token value** — the two Bearer tokens this stack uses
(`CONTROL_PLANE_WEBHOOK_TOKEN`, `CONTROL_PLANE_LIFECYCLE_TOKEN`) are
generated locally into your own `.env` (gitignored) by
`scripts/init-webhook-secret.sh`, which `make db-up` already calls for
you. Nowhere in this repository is a real secret value checked in.

### 3.1 Start the stack safely

```bash
make db-up
```

This generates (or reuses, idempotently) the local webhook + lifecycle
secrets, then runs `docker compose up -d`. It does **not** drop or
reset any existing named volume (`postgres_data`,
`prometheus_data`, `tempo_data`, `loki_data`, `grafana_data`,
`alertmanager_data`) — a prior run's data is preserved.

```bash
make db-status   # docker compose ps — confirm postgres is "healthy"
```

### 3.2 Apply Flyway migrations (V1–V4)

```bash
make db-migrate
```

Safe to rerun at any time — Flyway tracks which of `V1`–`V4` have
already been applied and is a no-op if the schema is current. This
repository's Flyway migrations are **never** edited after being
applied (that would invalidate their checksum); every fix so far has
been a new, additive migration file. Do not hand-edit anything under
`database/migrations/`.

### 3.3 Confirm service readiness

```bash
curl -s http://127.0.0.1:8000/health/live    # {"status":"ok"} once the process is up
curl -s http://127.0.0.1:8000/health/ready   # 200 once PostgreSQL + the schema are reachable
```

`/health/ready` correctly reports `503` (not a crash) if PostgreSQL or
the migration isn't ready yet, and recovers on its own — no manual
restart needed.

### 3.4 Inspect existing incidents through HTTP (read-only, unauthenticated)

```bash
curl -s "http://127.0.0.1:8000/api/v1/incidents?limit=20&offset=0" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/v1/incidents?status=open&severity=critical" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/v1/incidents/<incident-id>" | python3 -m json.tool
```

Supports `status`, `severity`, and `source` filters, plus `limit`/
`offset` pagination, deterministically ordered
(`last_seen_at DESC, id DESC`). These endpoints are read-only by
design — no request against them ever mutates a row.

### 3.5 Inspect an incident's paginated audit timeline

```bash
curl -s "http://127.0.0.1:8000/api/v1/incidents/<incident-id>/events?limit=20&offset=0" | python3 -m json.tool
```

Also read-only and unauthenticated. `total` tells you how many events
exist in total; page with `limit`/`offset` (`limit` is capped at 100
server-side) if an incident has accumulated more events than fit on
one page. An incident that predates the audit trail (Phase 3E)
legitimately returns an empty `items` array with `200`, not a `404` —
that is expected, not a bug: history is never invented retroactively.

### 3.6 Exercise the authenticated operator lifecycle API

The lifecycle Bearer token lives in your own local `.env` — read it
yourself, don't paste it into a shared terminal/log:

```bash
LIFECYCLE_TOKEN="$(grep '^CONTROL_PLANE_LIFECYCLE_TOKEN=' .env | cut -d= -f2-)"

curl -s -X PATCH "http://127.0.0.1:8000/api/v1/incidents/<incident-id>/status" \
  -H "Authorization: Bearer $LIFECYCLE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expected_status": "open", "target_status": "investigating"}' \
  | python3 -m json.tool
```

`expected_status` is mandatory optimistic-concurrency protection, not
decoration — the transition is only applied if the incident's actual
current status still matches it at the instant of the real atomic
`UPDATE`. A stale `expected_status` or an illegal transition (per
`domain/lifecycle.py`'s state machine:
`open → {acknowledged, investigating, resolved}`,
`acknowledged → {investigating, resolved}`,
`investigating → {remediating, resolved}`,
`remediating → {investigating, resolved}`, `resolved → {closed}`,
`closed → {}`) returns `409` with the row left completely unchanged.
This is a **distinct** Bearer token from the webhook's
(`CONTROL_PLANE_WEBHOOK_TOKEN`) — they are not interchangeable, and
each call writes a matching audit event in the same transaction as
the transition.

### 3.7 Understand the existing real Alertmanager acceptance test

```bash
make verify-alert-ingestion
```

This is the **one** Collector-outage gate (do not add a second one —
see §2). `make verify-alert-ingestion` runs
`scripts/verify-alert-lifecycle.sh` with `VERIFY_INGESTION=true`. That
shell script is the actual orchestrator of the real failure: it stops
and restarts the `otel-collector` container directly, waits for
Prometheus/Alertmanager to observe and recover from it, and, at the
end, triggers a fresh real `POST /checkouts` to confirm telemetry has
genuinely resumed afterward (section 13 of the script) — none of that
is part of `scripts/verify-ingestion.py`.

`scripts/verify-ingestion.py` (invoked twice by that shell script, as
`incident-from-alert` and `confirm-resolved`) is the read-only
cross-checking half: it **only reads** Prometheus's, Alertmanager's,
and control-plane's own HTTP APIs — it never POSTs anything to any of
them. Every actual mutation to a `reliability.incidents` row or its
audit trail in this test is performed by Alertmanager's own real
webhook deliveries (firing, then resolved) to control-plane, which
`scripts/verify-ingestion.py` observes after the fact; it never
simulates or injects that delivery itself.

Together, the chain this gate proves is: real outage (shell script) →
real Prometheus firing alert → real Alertmanager webhook delivery
(the actual mutation) → persisted, identity-matched incident (read
back and confirmed by `verify-ingestion.py`) → Collector recovery
(shell script) → real Alertmanager resolved webhook delivery (the
actual resolution mutation) → genuine automatic resolution →
correctly-attributed, fingerprint-traceable audit history (read back
and confirmed by `verify-ingestion.py`) → fresh checkout confirms
telemetry resumed (shell script, final step).

This is the **expensive** gate — it drives a real multi-minute outage
and recovery. Prefer the focused gates (`make verify-persistence`,
`make verify-control-plane`, `make verify-webhook-ingestion`,
`make verify-incident-lifecycle`, `make verify-incident-audit`) for
day-to-day iteration; run this one when you need end-to-end
confidence, or let CI run it.

### 3.8 Shut down without deleting volumes

```bash
make db-down
```

This runs `docker compose down`, which stops and removes containers
and the Compose network but — critically — **preserves every named
volume** (no `-v` flag): `postgres_data` and every observability
volume (`prometheus_data`, `tempo_data`, `loki_data`, `grafana_data`,
`alertmanager_data`) all survive. `make db-up` later resumes from
exactly where you left off. Never run `docker compose down -v` or
`docker volume rm` against this project unless you specifically intend
to destroy historical incidents and audit history.

That said, "no verifier deletes anything" is **not** accurate, and is
worth being precise about:

- `scripts/verify-persistence.sh` and `scripts/verify-control-plane.sh`
  insert their test incidents **directly via SQL**, bypassing the
  application entirely — these rows are never audited (no
  `reliability.incident_events` row is ever created for them, since
  only the application's own write paths record one), and both
  scripts' final section genuinely `DELETE`s exactly their own
  run-scoped rows at the end, confirmed back down to the count before
  the run.
- `scripts/verify-webhook-ingestion.sh`, `scripts/verify-incident-lifecycle.sh`,
  and `scripts/verify-incident-audit.sh` drive their incidents through
  the **real application write paths** (the webhook and the lifecycle
  API), which do record audit events — and `ON DELETE RESTRICT` makes
  an audited incident undeletable in any case. These three scripts'
  final sections only **confirm** their run's rows and event counts
  are present; they never attempt a delete.
- **No verifier, anywhere, ever deletes a row from
  `reliability.incident_events`** — the append-only triggers
  (`V3`/`V4`) would reject it at the database level even if one tried.

So: `reliability.incident_events` history is permanent by design and
by construction, full stop. `reliability.incidents` rows created
*directly via SQL by the two Phase 3A/3B verifiers* are intentionally
cleaned up as disposable test fixtures; every other incident row this
system has ever audited is retained permanently. Either way, none of
this touches Docker volumes — that cleanup happens inside an already-
running, already-migrated database, not by resetting storage.

### 3.9 Recognize expected failures, and how to investigate a real one

A few things that look like failures are actually correct, documented
behavior:

- `GET /health/ready` returning `503` while PostgreSQL is mid-restart
  or mid-migration — expected; it recovers on its own.
- `GET /api/v1/incidents/{id}/events` returning `200` with an empty
  `items` array for an incident that predates Phase 3E — expected, not
  a bug (see §3.5).
- A `PATCH .../status` call returning `409` — expected whenever
  `expected_status` is stale or the requested transition is illegal;
  the response body names which.
- A webhook delivery during a PostgreSQL outage returning `503` and
  writing nothing — expected; `make verify-webhook-ingestion` proves
  this directly.

If a verification script genuinely fails (exits non-zero with a `FAIL:`
line), it is designed to fail loudly rather than silently pass on
partial evidence — read that `FAIL:` message first; it names exactly
what was expected versus what was found. For a CI-only failure that
does not reproduce locally:

1. Open the failing job in GitHub Actions and read the exact step name
   and its full log output, not just the red X.
2. Check whether the failure is in a focused gate (3A–3E, isolated) or
   the full `verify-alert-ingestion` chain (cross-system) — that tells
   you which script and which real system (PostgreSQL vs.
   Prometheus/Alertmanager/otel-collector) to look at first.
3. Reproduce the same `make <target>` locally against a freshly
   started stack (`make db-up` on a clean checkout) before assuming
   it's environment-specific. A prior CI incident in this repository
   (see the fix for broken-pipe failures in the focused verifier
   scripts) turned out to be a shell/timing bug in the verifier
   itself, not the application — don't assume a CI-only failure means
   the runner is broken.
4. Never silence a failing assertion with `|| true` or by deleting the
   check — fix the real cause, or escalate with the exact `FAIL:` text.

## 4. Implemented vs. planned

**Implemented and verified (Phase 3A–3F):**

- Durable `reliability.incidents` schema + migrations (`V1`, `V2`)
- Read-only control-plane HTTP API (list/filter/paginate, get-by-id,
  liveness/readiness)
- Authenticated Alertmanager webhook ingestion (create/update/resolve,
  deduplicated per-fingerprint, occurrence-identity/stale-replay safe)
- Authenticated operator incident lifecycle API with a centralized
  state machine and real optimistic concurrency
- Durable, append-only incident audit trail (`V3`, `V4`), including
  TRUNCATE-hardening, genuine insertion-time timestamps, and a
  read-only paginated timeline API
- One real, end-to-end Collector-outage acceptance test tying all of
  the above together, including fingerprint-level traceability of the
  persisted audit record back to the real alert that produced it
- This runbook and the acceptance matrix above

**Explicitly planned / future work (not implemented, not started this
phase, and out of scope for Phase 3F):**

- Failure injection or chaos engineering beyond the existing, narrow
  Collector-outage test
- AI/LLM-based investigation of incidents
- LangGraph-based agent runtime, or any RAG component
- Automated remediation of any kind
- Human approval workflows for remediation actions
- A frontend / operations console
- Kubernetes, Terraform, or AWS deployment
- Authentication on the read-only `GET` endpoints
- Redis, Kafka/Redpanda, or any other new infrastructure dependency
- Additional database tables for investigation history, decisions, or
  approvals

See [docs/architecture/system-overview.md](system-overview.md)'s
"Planned Architecture" section for the full long-term shape — Phase 3F
closes the incident-management foundation those future phases will be
built on top of; it does not begin building them.

## 5. Related documents

- [docs/architecture/incident-domain-model.md](incident-domain-model.md) — Phase 3A
- [docs/api/control-plane.md](../api/control-plane.md) — Phase 3B API reference
- [docs/architecture/phase-3c-alert-ingestion.md](phase-3c-alert-ingestion.md) — Phase 3C
- [docs/architecture/phase-3d-incident-lifecycle.md](phase-3d-incident-lifecycle.md) — Phase 3D
- [docs/architecture/phase-3e-incident-audit.md](phase-3e-incident-audit.md) — Phase 3E
- [docs/architecture/system-overview.md](system-overview.md) — full system architecture, current + planned
