# Phase 16 — Secure Application Onboarding and Tenant-Safe OpenTelemetry Integration

## 1. Mission and scope

Phase 16 implements the platform's **first real, secure onboarding pathway**
for connecting an external application to an organization: a developer
registers a service, generates a real credential, configures their
application to emit OpenTelemetry metrics, and sees real operational
measurements — and, when that service genuinely fails, a real,
tenant-scoped incident — inside their own organization's dashboard.

Deliberately **one** ingestion path, **one** signal (HTTP server request
metrics), done honestly and verifiably, rather than several incomplete
integrations. Traces and logs are explicitly **not** implemented this
round — see §6.

## 2. Gate 1 audit — what already existed, and why it isn't safe to reuse as-is

Before writing any code, the existing telemetry architecture was
mapped end to end:

- **OTel Collector** (`observability/otel-collector/config.yaml`): a
  single shared instance, OTLP receivers on `:4317`/`:4318` with **no
  authentication of any kind** — any process that can reach those
  ports can submit arbitrary telemetry under any `service.name`.
- **Prometheus** (`observability/prometheus/prometheus.yml`): a single
  shared TSDB. A `service_name` label is just a label — Prometheus has
  no concept of a tenant, no per-label query ACL, and no
  `--web.enable-remote-write-receiver` authentication story either.
  **Anyone who can query Prometheus can read any label value.**
- **Tempo** (`observability/tempo/tempo.yaml`): comment in the file
  itself confirms "no multitenancy/auth is enabled (the default)" —
  `X-Scope-OrgID` is not configured.
- **Loki** (`observability/loki/loki.yaml`): `auth_enabled: false` —
  the same single-tenant default.
- **Control-plane** (`reliability.incidents`): the one place in this
  platform where tenant isolation is REAL — `organization_id` is a
  column, every query is `WHERE organization_id = :actor_org`, and
  this has been proven by two real, repeatedly-passing acceptance
  suites (`verify-phase14-multitenant-security.sh`,
  `verify-retrieval-tenant-isolation.sh`).

**Conclusion (the core architectural decision):** adding an
`organization_id` label to Prometheus/Tempo/Loki data would be real in
the sense that the label exists, but would provide **no actual
isolation**, because nothing in those systems enforces it at query
time. Retrofitting real multi-tenancy onto all three (enabling Loki/
Tempo's own tenant modes, building a label-enforcing proxy in front of
Prometheus, authenticating the Collector's receivers) is real
infrastructure work, out of scope for "the smallest coherent secure
integration" this round, and was **not attempted**.

### Chosen architecture

Externally-submitted tenant telemetry is **never written to Prometheus/
Tempo/Loki**. It is stored as validated, bounded rows in a **new
PostgreSQL table** (`reliability.telemetry_samples`), using the exact
same `organization_id`-scoped-query pattern already proven secure for
`reliability.incidents`. A new, purpose-built, authenticated ingestion
endpoint inside control-plane (the platform's one existing trust
boundary) is the only write path into it.

| Option considered | Why rejected |
|---|---|
| Authenticate the OTel Collector (custom auth extension) + keep using Prometheus/Tempo | Requires a new Go build/toolchain for a custom extension, AND still leaves Prometheus/Tempo's own query layer unauthenticated — ingestion-side auth alone does not solve storage/query-side isolation. |
| Prometheus `remote_write` with a trusted label | Same fundamental problem: once data is in the shared TSDB, nothing stops a future raw-query feature (or a Grafana misconfiguration) from reading another tenant's label value. |
| **Chosen: a new control-plane-owned ingestion endpoint + a new Postgres table** | Reuses this platform's own, already-proven tenant-isolation mechanism exactly. No new infrastructure. Isolation is enforced by the same code path already covered by 34+17 real, passing security checks. |

The existing OTel Collector/Prometheus/Tempo/Loki stack is **completely
unchanged** by this phase and continues to serve only the platform's
own internal demo services.

## 3. Database (additive only — V1–V12 untouched)

- **`V13__create_integration_credentials.sql`** — `reliability.integration_credentials`:
  `id`, `organization_id`, `service_id` (FK to `reliability.services`),
  `connection_type` (CHECK, currently only `'opentelemetry'`),
  `credential_id` (public lookup key), `credential_secret_hash` (SHA-256
  digest — **no plaintext secret column exists**), `status`
  (`active`/`revoked`), `created_by_user_id`, `created_at`/`updated_at`,
  `revoked_at`, `last_verified_telemetry_at`.
- **`V14__create_telemetry_samples.sql`** — `reliability.telemetry_samples`:
  `organization_id`/`service_id`/`integration_credential_id` (all
  server-derived, never client-supplied), `observed_at`, `http_method`/
  `http_route`/`http_status_code`, `request_count`,
  `duration_sum_seconds`, `is_error`. See that migration's own
  docstring for the honest modeling note on why `request_count`/
  `duration_sum_seconds` (not one row per individual request) is the
  correct, non-fabricated representation of a real OTLP histogram data
  point.
- **`V15__add_otel_telemetry_incident_actor.sql`** — widens
  `reliability.incident_events.actor_type`'s CHECK constraints to
  accept `'otel-telemetry'`, mirroring V8/V9's own Kubernetes/AWS
  precedent, with one real difference: `otel-telemetry` is also
  permitted on `status_transition` events, since a telemetry-derived
  incident is safely, genuinely auto-resolvable (§6).
- **`V16__add_telemetry_sample_dedup_key.sql`** (independent review
  correction round, §6b item 5) — a unique index on
  `telemetry_samples (service_id, observed_at, COALESCE(http_method,
  ''), COALESCE(http_route, ''), COALESCE(http_status_code, -1))`,
  enforcing durable deduplication of a retried DELTA export at the
  database layer. Additive only — V1–V15 were never edited; V13–V15
  had already been applied to a real developer database before this
  round, so this correction is a new migration rather than a rewrite
  of any of them.

## 4. Credential lifecycle and RBAC (Gate 2/3)

- **Enrollment roles**: `OWNER`/`ADMIN`/`ENGINEER` only — reuses
  `core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES` directly (the same
  constant Phase 15's service-registration role gate already
  established), rather than a new, parallel constant.
  `POST`/`.../revoke` both enforce it; `VIEWER`/`INCIDENT_APPROVER` get
  a real 403.
- **Generation** (`core/credentials.py`): `credential_id` is a public,
  non-secret `cred_<22 random base64 chars>` lookup key (~132 bits);
  `secret` is a separate 256-bit `secrets.token_urlsafe` value. The
  bearer token a client actually uses is `<credential_id>.<secret>`.
- **Storage**: only `SHA-256(secret)` is ever persisted — chosen over
  bcrypt/argon2 deliberately: the secret is already CSPRNG-generated
  with far more entropy than any realistic offline attack could search,
  so slow key-stretching (which defends a *low-entropy human password*)
  buys nothing and only adds ingestion latency.
- **Shown once**: the real secret is present in exactly one API
  response (`POST .../integrations`) and one browser dialog; it is
  never logged, never re-fetchable, and the public list view never
  includes the hash.
- **Revocation**: `POST .../integrations/{id}/revoke` sets
  `status='revoked'` + `revoked_at`; the ingestion auth path checks
  `status == 'active'` on every request, so a revoked credential is
  denied immediately, not eventually.
- **Rotation**: generate a new credential, revoke the old one — no
  separate "rotate" endpoint exists; two independent, auditable
  mutations is simpler and no less safe.
- **No cross-organization reuse**: a credential's `organization_id`/
  `service_id` are fixed at creation and never re-derived from
  anything the client sends afterward.

## 5. Threat model (Gate 3)

| Threat | Mitigation |
|---|---|
| Credential guessing | 256-bit CSPRNG secret; constant-time (`hmac.compare_digest`) verification. |
| Credential leaked in logs/URLs | Never logged; accepted only via the `Authorization` header, never a query string; this repo's own `.gitignore`/secret-scanning discipline applies as it does everywhere else. |
| Stolen/revoked credential reuse | `status` checked on every request; revocation is immediate. |
| Brute-force / credential-stuffing against the ingestion endpoint | `AUTH_FAILURE_RATE_LIMITER` (10 failures / 5 min per credential-id-or-IP) — see `core/rate_limit.py`. |
| Ingestion-volume abuse by a valid credential | `INGESTION_RATE_LIMITER` (60 accepted requests / min per credential). |
| Tenant-identity spoofing via resource attributes / `service.name` / client-claimed org id | **Structurally impossible**, not merely checked: `ingestion/telemetry_service.py`'s parser has no field, and `api/telemetry_ingest.py` has no code path, that reads an organization or service identity from the request body at all. Identity comes exclusively from the authenticated credential (`api/telemetry_auth.py`). |
| Oversized payload (resource exhaustion) | ASGI-level `TelemetryBodySizeLimitMiddleware` (512 KiB), enforced on real received bytes before any buffering/parsing — mirrors the existing webhook guard exactly. |
| Malformed/adversarial OTLP payload | A bounded, strict Pydantic model (`domain/telemetry.py`) — unsupported shapes are rejected (422/400), never guessed at. |
| Browser-side credential persistence | None — the credential is generated server-side, shown once in a React dialog state, and never written to `localStorage`/cookies/any browser storage. |

**Known limitation**: the two rate limiters are in-process (a Python
dict on the running control-plane instance), not a shared store. Real
and effective for this single-instance deployment; would need a shared
backing store (Redis, etc.) to remain effective across multiple
horizontally-scaled replicas. Documented, not silently assumed away.

## 6. Ingestion flow (Gate 4, corrected)

`POST /api/v1/telemetry/otlp/v1/metrics`, OTLP/HTTP, now accepting
**both JSON and protobuf** bodies (dispatched on `Content-Type`; see
§6b item 3 below for why protobuf was added this round). Exactly
**one** supported metric: `http.server.request.duration` (a
Histogram) — the same real OTel semantic convention this platform's
own checkout/payment/inventory/notification services already emit,
which real HTTP-server instrumentation libraries (Spring/Micrometer,
`opentelemetry-instrumentation-fastapi`/`flask`, Go's `otelhttp`,
Node's `@opentelemetry/instrumentation-http`) emit automatically once
configured with an OTLP HTTP exporter.

Request flow: ASGI body-size guard → credential authentication (hash
verify, revocation check, both rate limiters) → Content-Type dispatch
(JSON validated directly against the Pydantic model; protobuf decoded
via `ingestion/otlp_protobuf.py` into the identical shape) → semantic
extraction (temporality/unit validation, bounded time window,
inconsistent-interval points dropped) → one bounded, durably-
deduplicated batch INSERT with **server-derived**
`organization_id`/`service_id` → the credential's
`last_verified_telemetry_at` is touched → an inline, synchronous
threshold check (§7) → an OTLP-compatible `ExportMetricsServiceResponse`
JSON body, HTTP 200.

**Signal scope decision (explicit, per Gate 4's own instruction to
narrow rather than half-build three)**: only metrics are implemented.
Traces/logs via Tempo/Loki would require enabling and verifying real
multi-tenancy in two additional systems that don't have it today — a
substantially larger, separately-reviewable piece of work. **This
capability is deliberately not implemented and remains disabled**
rather than half-built.

## 6b. Independent security/protocol correction round

An independent review of the Phase 16 implementation above found nine
confirmed issues before it was eligible to commit. The architecture in
§1–§9 was **accepted as-is**; every item below is a correction to
implementation details, not a redesign. All nine were fixed, verified
against real PostgreSQL and (for item 3) a real official OpenTelemetry
SDK, and are summarized here; full technical detail lives in the
corresponding module docstrings.

1. **OTLP histogram temporality.** The previous round's parser ignored
   `aggregationTemporality` entirely and treated every export as a
   fresh delta — summing a client's repeated CUMULATIVE exports would
   have silently inflated every count forever. The endpoint now
   **requires DELTA (1) and rejects CUMULATIVE/UNSPECIFIED outright**
   with a clear 400 (`ingestion/telemetry_service.py::
   _require_delta_temporality`) — no durable cumulative-to-delta
   conversion was attempted; that is real, state-carrying work out of
   scope for this narrow MVP. `samples/otel-sample-app/app.py` was
   itself mislabeled (`aggregationTemporality: 2` on data that was
   always real delta behavior — it clears its own pending buckets on
   every export) and now correctly declares `1`, with a real,
   correctly-advancing `startTimeUnixNano` per interval instead of a
   value that never changed.

2. **OTLP/HTTP response contract.** The endpoint returned a custom
   `202 {"accepted_data_points": N}` body. It now returns the real
   OTLP `ExportMetricsServiceResponse` shape at HTTP 200 — `{}` on full
   acceptance, or `{"partialSuccess": {"rejectedDataPoints": "<n>",
   "errorMessage": "..."}}` when some (not all) data points in an
   otherwise-accepted batch were dropped (a stale timestamp, an
   inconsistent interval) — verified against a genuine compatible
   exporter (item 3's own official-SDK proof).

3. **Official SDK integration.** Independent verification of the real
   `opentelemetry-exporter-otlp-proto-http==1.45.1` package (installed
   from PyPI, source read directly) found it hardcodes
   `Content-Type: application/x-protobuf` and calls
   `ExportMetricsServiceRequest.SerializeToString()` — it has **no
   JSON code path at all**, regardless of
   `OTEL_EXPORTER_OTLP_PROTOCOL`. The previous round's onboarding
   snippets set `http/json` (never real for this exporter) and pointed
   a generic `OTEL_EXPORTER_OTLP_ENDPOINT` at this platform's base URL
   (which gets the spec's own `/v1/metrics` suffix auto-appended —
   never this platform's real `/api/v1/telemetry/otlp/v1/metrics`
   route). Both are now fixed: the backend gained a real protobuf
   decode path (`ingestion/otlp_protobuf.py`, using the OpenTelemetry
   project's own `opentelemetry-proto` generated message classes,
   converted via `google.protobuf.json_format.MessageToDict` into the
   exact same validated shape the JSON path already used — no parallel
   validation logic), and the Python onboarding snippet now sets
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` and the signal-specific
   `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` to the exact, full ingestion
   URL. **A third real finding from the same verification**: the
   official SDK's metrics exporter defaults to CUMULATIVE temporality
   for histograms, not DELTA — incompatible with item 1's own fix
   unless `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta` (a
   real, spec-defined env var the SDK already reads) is also set;
   every onboarding snippet now sets it.

   **Real proof, this round**: using this exact installed SDK/exporter
   (not a hand-rolled client), a real `MeterProvider` +
   `PeriodicExportingMetricReader` + `OTLPMetricExporter` recorded 5
   histogram observations and `force_flush()`'d them over real HTTP to
   the live control-plane container; the resulting row in
   `reliability.telemetry_samples` showed `request_count=5,
   duration_sum_seconds=0.35` — the real, correct sum of
   `0.05+0.06+0.07+0.08+0.09`. `samples/otel-sample-app/`'s own
   hand-built JSON client remains a separate, legitimate, simpler
   walkthrough — it is no longer the only path exercised, and the
   onboarding UI's "validated" badge now says so explicitly. Node/
   Java/Go snippets were corrected to the same protocol/endpoint/
   temporality pattern (every official SDK's HTTP metrics exporter
   defaults to protobuf, per the OTLP spec's own default) but remain
   explicitly marked **unverified** — only Python was actually run
   this round.

4. **Request latency correctness.** The previous round's p50/p95 were
   `percentile_cont` over each stored row's own per-export-interval
   MEAN duration (`duration_sum_seconds / request_count`) — a
   percentile of batch averages, not a request-level percentile, and
   one that weights a batch of 1 request the same as a batch of 1,000.
   Per the review's own preference for "the smallest correct
   solution" over bucket-level histogram storage (option A), this is
   now a single, honestly-labeled `mean_latency_seconds =
   SUM(duration_sum_seconds) / SUM(request_count)` across the window —
   a real, correctly-weighted mean of every observed request, computed
   server-side, never called a percentile.

5. **Duplicate export handling.** An identical retried export was
   previously stored twice — a real OTel SDK's at-least-once delivery
   contract means this is not a hypothetical. `database/migrations/
   V16__add_telemetry_sample_dedup_key.sql` adds a unique index on a
   data point's stable timeseries identity (service, its own
   `observed_at` end timestamp, and its attribute set, with `COALESCE`
   normalizing NULL attributes); `insert_batch` now uses a real
   `INSERT ... ON CONFLICT ... DO NOTHING ... RETURNING id`, counting
   only genuinely new rows. **A second real bug was found verifying
   this against real PostgreSQL** (not caught by the 463 unit tests,
   which use an in-memory fake with no real SQL compilation): every
   ingestion request failed with "there is no unique or exclusion
   constraint matching the ON CONFLICT specification" because
   SQLAlchemy compiled the `COALESCE(..., "")` fallback as a bound
   parameter, which Postgres's `ON CONFLICT` inference does not
   recognize as matching V16's own literal `COALESCE(http_method, '')`
   expression. Fixed by forcing the fallback to compile as literal SQL
   text (`sa.text("''")`/`sa.text("-1")`). **Real proof**: 10
   concurrent, byte-identical duplicate submissions against the real
   running stack produced exactly **one** stored row with the correct
   `request_count`, both before measuring this fix (confirming the bug)
   and after (confirming the fix). The previously-misnamed test
   (`..._is_accepted_idempotently_without_error`, which asserted TWO
   stored rows) is renamed to `test_duplicate_retried_submission_is_
   deduplicated_and_stored_once` and now asserts one.

6. **Authentication rate-limit bypass.** The auth-failure limiter keyed
   its budget by the credential id the *caller claimed* — entirely
   attacker-controlled, so an attacker could reset their own budget
   forever by fabricating a new id each request. It is now keyed
   **exclusively by the real connecting peer address**
   (`request.client.host`, as ASGI/Starlette itself observed it,
   including for a missing/malformed `Authorization` header, which is
   now also rate-limited); `X-Forwarded-For` or any other
   caller-suppliable "I am really at this IP" header is never read —
   this service sits behind no trusted reverse proxy that would make
   trusting one safe. `SlidingWindowRateLimiter` also gained a real,
   enforced memory bound (`max_tracked_keys`, with idle-key pruning and
   least-recently-used eviction as a last resort) rather than relying
   on a caller to periodically invoke `prune_idle_keys()`. **Real
   proof**: 15 requests from one real source, each with a completely
   different fabricated credential id, correctly tripped the limiter
   on the live stack (10 failures allowed, then 429) — the exact
   bypass the previous round's keying allowed.

7. **Unit/count/sum validation.** A metric's `unit` is now validated
   against an explicit supported set (`s`, `ms`, `us`, `ns`) with a
   real conversion to seconds — a missing or unrecognized unit is
   rejected outright, never assumed to already be seconds. `count` is
   bounded (`<= 1,000,000`) and `sum` is bounded
   (`<= 1,000,000.0 seconds`) and `allow_inf_nan=False` — a literal
   `NaN`/`Infinity`/`-Infinity` JSON token (invalid per RFC 8259, but
   tolerated by Python's own lenient `json.loads`, which this
   endpoint's JSON path uses) is rejected with a clean 422, not a 500
   from a downstream float-handling crash. A data point whose
   `startTimeUnixNano` is present but after its own `timeUnixNano` is
   dropped as an inconsistent interval.

8. **Benchmark reconciliation.** The previous round's architecture doc
   and review-archive benchmark summary reported two different sets of
   ingestion-latency and rate-limit-burst numbers for the same
   measurements, with no record of why they differed. Root cause: the
   figures came from separate, uncontrolled runs — different pre-
   existing states of the in-process rate limiter at measurement time
   (itself a real, in-process, stateful component) produced different
   burst-acceptance counts, and neither run's own conditions were
   recorded alongside its numbers. §13 below is a full, single,
   reproducible rebenchmark against this round's corrected code, with
   its exact method and starting conditions stated inline — not a
   silent pick of whichever number looked better.

9. **Full regression.** See §12 (updated) for the complete real-stack
   regression this round, including the new dedup/temporality/
   validation/rate-limit-bypass tests and a second real, official-SDK-
   driven run of the Gate 9 end-to-end proof.

## 7. Tenant-scoped incident detection (Gate 6)

A small, inline, synchronous detector
(`ingestion/telemetry_threshold_detector.py`) — not a new polling
service — runs after every accepted ingestion batch: it re-queries a
bounded 5-minute window for the submitting service and, when
`request_count >= 3` and `error_rate >= 50%`, calls the **existing**
`IncidentRepository.upsert_firing_incident` (now accepting an optional
`organization_id`, defaulting to the legacy constant for every
pre-existing caller — zero behavior change for Alertmanager/
Kubernetes/AWS ingestion). The fingerprint is
`source="otel-telemetry"`, `source_fingerprint="service:<service_id>"`
— `service_id` is a real, globally-unique UUID, so this can never
collide across two different organizations' services, and the
existing `(organization_id, source, source_fingerprint)` partial
unique index (added back in V10, originally for exactly this future
use) does the rest. When the window later reports a healthy error
rate again, the same code path **actively resolves** the still-open
incident via the existing `resolve_active_incident_for_fingerprint` —
safe specifically because a telemetry-derived incident's own
triggering condition is independently re-observed on every subsequent
batch, unlike a one-shot Kubernetes/AWS finding (which never
auto-resolves).

No parallel incident system was created. The legacy Alertmanager/
Kubernetes/AWS ingestion paths are completely untouched. No autonomous
remediation exists for telemetry-derived incidents — investigation is
read-only exactly like every other incident; approving/executing a
remediation still requires the existing, unchanged human-approval
path.

## 8. Frontend (Gate 5 / Gate 7)

- **`/services/[serviceId]`** (new) — the real service detail/
  onboarding page: service header, `TelemetryPanel` (Gate 5's six
  required states: NOT_CONFIGURED / CONFIGURED_AWAITING_DATA /
  RECEIVING_TELEMETRY / STALE_DATA / CONNECTION_ERROR / REVOKED — the
  first five derived server-side in `api/service_telemetry.py`;
  CONNECTION_ERROR is the frontend's own existing `BackendFailure`
  state when the API call itself fails), `IntegrationSetupFlow`
  (generate/revoke credentials, real copyable per-language setup
  snippets), and a real "Recent incidents" list (filtered to this
  service's own real fingerprint from the existing, already org-scoped
  `listIncidents` call).
- Request rate / error rate / p50 / p95 latency / last-observed-
  telemetry are rendered **only** when `request_count > 0` for the
  selected window — an empty window shows "No measurements," never a
  zero that could be misread as "healthy."
- **Gate 7 honesty note**: setup instructions are shown for Python,
  Node.js, Java, and Go. **Only the Python path was independently
  validated end-to-end this round** (`samples/otel-sample-app/`,
  itself a hand-built minimal client, not the official SDK). The
  other three tabs are marked with an explicit, visible warning that
  they follow the official SDK's own documented configuration but were
  not independently exercised this round — never silently presented as
  equally verified.

## 9. New backend endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/services/{id}` | `require_actor_context` | Single-service lookup (new; the detail page's own data source). |
| `POST` | `/api/v1/services/{id}/integrations` | `require_actor_context` + role | Create a credential; returns the secret once. |
| `GET` | `/api/v1/services/{id}/integrations` | `require_actor_context` | List credentials (secret-free). |
| `POST` | `/api/v1/services/{id}/integrations/{iid}/revoke` | `require_actor_context` + role | Revoke. |
| `POST` | `/api/v1/telemetry/otlp/v1/metrics` | integration credential | The one real ingestion path. |
| `GET` | `/api/v1/services/{id}/telemetry-summary` | `require_actor_context` | Bounded, windowed aggregate for the dashboard. |

## 10. A real bug found and fixed this round

**`upsert_firing_incident` never commits its own transaction** (by
design — every pre-existing caller, e.g. the Alertmanager webhook
path, is responsible for calling `repo.commit()` itself). The new
telemetry threshold detector called it but never called `commit()` —
every unit test (using the in-memory fake repository, which has no
real transaction to roll back) passed, but the very first real,
PostgreSQL-backed end-to-end run silently discarded the incident. Found
by directly inspecting `reliability.incidents` after a real ingestion
run showed no incident despite a clearly elevated error rate, fixed by
adding the missing `await repo.commit()`, and covered by a new
regression assertion (`test_telemetry_ingest.py::
test_elevated_error_rate_produces_a_real_tenant_scoped_incident`
asserts `incidents.commit_count >= 1`).

**A second real bug**: V15's migration correctly widened the real
database CHECK constraint on `incident_events.actor_type` to accept
`'otel-telemetry'`, but `domain/incident_event.py`'s Pydantic
`ActorType` Literal was never widened to match — `GET
/api/v1/incidents/{id}/events` crashed with a real HTTP 500
(`pydantic_core.ValidationError`) the first time a genuinely
`otel-telemetry`-attributed event was read back through the real API.
Found during the Gate 9 end-to-end Playwright run (a blank "Received an
unexpected response from the backend" audit timeline on a real,
freshly created incident), fixed by widening the Literal, and covered
by a new regression test
(`test_incident_audit.py::test_otel_telemetry_actor_type_events_serialize_without_error`)
that exercises the real route's own Pydantic response validation —
**both bugs were only found via real end-to-end testing against real
PostgreSQL and a real browser; neither was caught by the (still
valuable, still passing) unit test suite alone.** This is the exact
lesson Gate 8 states explicitly ("Do not rely exclusively on mocks").

## 11. Gate 9 — end-to-end acceptance (real stack, real sample app)

`services/web-console/e2e/phase16-e2e-proof.ts`, run against the live
Compose stack with investigator-service forced into its existing
deterministic stub LLM provider (same mechanism `phase9-workflow.spec.ts`
already uses — **no real paid LLM call**), proved the complete real
path:

1. Two real, disposable organizations created via real registration +
   real email verification (the documented local-development
   mechanism — the real link from web-console's own server logs).
2. A real service registered in Org A.
3. A real integration credential generated (secret shown once).
4. `samples/otel-sample-app/app.py` (a standalone sample app, separate
   from checkout/payment/inventory/notification — see its own README)
   configured with the real credential and run as a real, independent
   process.
5. Real HTTP traffic sent to the sample app.
6. Real OTLP export accepted; the service's real telemetry summary
   showed `receiving_telemetry` with real measurements.
7. A controlled test failure triggered (`/fail-mode`).
8. A real, tenant-scoped incident appeared — the error-rate/request-
   count numbers in its description are the real, computed values, not
   placeholders.
9. The incident was viewed in Org A's own dashboard, with a real,
   complete audit timeline.
10. A real AI investigation was started against it (read-only —
    **no autonomous remediation was enabled or attempted**).
11. **Org B** (the second disposable organization) was proven unable
    to read Org A's service page (404), Org A's incident (404), while
    Org B's **own** dashboard remained reachable (proving a real,
    scoped denial, not a general outage).

All 9 checks passed. Two real screenshots were captured
(`e2e/screenshots-output/phase16-incident-detail.png`,
`phase16-investigation.png`). Every disposable user/organization/
service/credential/telemetry row this proof created was deleted
afterward (the incident and its append-only audit events are left in
place — `reliability.incident_events` is immutable by design, the same
accepted pattern every other real security-acceptance run in this
project's history already leaves behind).

**Re-run after the correction round** (§6b), against the rebuilt
control-plane AND web-console images (the frontend's own
`p50_latency_seconds`/`p95_latency_seconds` → `mean_latency_seconds`
rename required a rebuild too — the first correction-round re-run was
done against a stale web-console image and surfaced exactly this gap,
caught before being reported as a false pass): **all 9 checks passed
again**, proving the temporality/response-contract/dedup/validation
corrections did not regress the real, authenticated, tenant-scoped
user journey.

## 12. Regression (Gate 10, updated for the correction round)

- Control-plane: **463 passed, 23 skipped, 0 failed** (pytest) —
  grew from 434 with this round's new temporality, response-contract,
  dedup, unit/count/sum validation, protobuf-decode, and rate-limit-
  bypass tests (`test_rate_limit.py`, `test_telemetry_protobuf.py`,
  plus new cases in `test_telemetry_ingest.py`).
- Web-console: **237 passed** (Vitest), `tsc --noEmit` clean, `eslint .`
  clean, against the `mean_latency_seconds` rename.
- A real, uncached production Docker build of both
  `services/control-plane/Dockerfile` (now installing
  `opentelemetry-proto`) and `services/web-console/Dockerfile`
  succeeded.
- `scripts/verify-phase14-multitenant-security.sh`: **34/34**.
- `scripts/verify-retrieval-tenant-isolation.sh`: **17/17**.
- The full real Playwright `phase9-workflow.spec.ts` browser workflow:
  passed against the corrected, rebuilt stack.
- The Gate 9 Phase 16 end-to-end proof: re-run and passed 9/9 against
  the corrected, rebuilt stack (§11).
- **V16 migration applied to the existing, real developer database**
  (never reset) — `flyway migrate` validated all 16 migrations'
  checksums (confirming V1–V15 were never edited) before applying the
  one new, additive V16.
- **Real-PostgreSQL correction-round proofs** (beyond the unit suite,
  against the live Compose stack's real database):
  - DELTA-only enforcement: a CUMULATIVE export real-curled against the
    live endpoint returns 400 naming DELTA; a DELTA export is accepted.
  - Duplicate dedup under real concurrency: 10 simultaneous, byte-
    identical duplicate submissions produced exactly **one** stored
    row with the correct `request_count` — first run exposed the real
    `ON CONFLICT` compilation bug (§6b item 5), second run (after the
    fix, rebuilt image) confirmed it resolved.
  - Rate-limit bypass fix: 15 requests from one real source, each with
    a different fabricated credential id, correctly tripped the
    auth-failure limiter (10 allowed, then 429).
  - Official SDK protobuf acceptance: the real
    `opentelemetry-exporter-otlp-proto-http` SDK exporter, configured
    per the corrected onboarding snippet, successfully exported real
    histogram data end to end (§6b item 3).
  - Partial-success response contract: one valid + one stale data
    point in the same export → real 200 with
    `partialSuccess.rejectedDataPoints: "1"`, one row stored.
  - Unit/count validation: an unsupported unit (`"minutes"`) → real
    400 naming the supported set; a count of 99,999,999 → real 422.
- **Fresh-checkout validation** (from the previous round, re-confirmed
  unaffected by this round's changes): an isolated `rsync` copy, its
  own Compose project/ports, `make db-migrate` against a brand-new
  empty database applied all migrations cleanly, and a real
  service → credential → ingestion → telemetry-summary round trip
  succeeded. The developer's own long-running stack's data was
  independently confirmed unaffected throughout this round too (row
  counts, container health, `flyway migrate`'s own checksum
  validation of V1–V15).

## 13. Performance measurements (Gate 11, reconciled this round)

**Item 8 finding**: the previous round's architecture doc and its own
review-archive benchmark summary reported two different sets of
numbers for the same measurements (e.g. this doc's "186 req/s" vs. the
archive's own differently-worded figures) with no record of why. Root
cause, confirmed this round: the in-process `SlidingWindowRateLimiter`
is real, stateful, and shared across whatever happened to run against
that credential/process earlier — the two prior runs simply started
from different, undocumented rate-limiter states, so their numbers
(especially the burst-rejection count) genuinely differed and neither
was "wrong," just incompletely specified. This round's numbers are
from ONE run, with starting conditions stated explicitly, so the
figures below are reproducible by anyone repeating the same method.

**Environment**: this developer's own Mac (Apple Silicon, arm64),
Docker Desktop, the real live Compose stack, control-plane's real
PostgreSQL-backed process (rebuilt with every §6b correction) — no
synthetic/mocked backend. Client: Python's `urllib`, sequential single
connection, from the host (not inside the Docker network) against
`127.0.0.1:8000`.

| Measurement | Starting condition | Sample size | Result |
|---|---|---|---|
| Ingestion request latency (`POST .../telemetry/otlp/v1/metrics`) | A freshly-created credential, its own ingestion budget untouched; no reset during the run | 55 sequential, authenticated, accepted requests (kept under the real 60/60s budget on purpose — see below) | p50 **4.06 ms**, p95 **9.78 ms**, p99 **41.17 ms**, min/max 3.08 ms / 41.17 ms |
| Observed throughput (accepted, sequential, single connection) | Same run as above | 55 requests | **191 req/s** |
| Telemetry-summary aggregate query (server-side `EXPLAIN ANALYZE`, the corrected `mean_latency_seconds` SQL) | Real table, 188 matching rows in the query's own window | 1 query | **Execution Time 0.105 ms** (Postgres's own measurement; a full HTTP round trip adds FastAPI/network overhead on top, not measured separately this round) |
| Rejection behavior under a real burst | A SEPARATE, freshly-created credential (its budget untouched), 80 requests with no inter-request delay | 80 requests | **60 accepted, 20 rejected (429)** — the real `SlidingWindowRateLimiter` enforcing its documented, exact 60-requests/60-second budget |

Why the ingestion-latency run used only 55 (not 200) requests: the
real `INGESTION_RATE_LIMITER` would otherwise reject request 61
onward from the SAME credential — a prior round's "200 sequential
requests" figure either ran across more than 60 real seconds of wall
time (letting the sliding window advance) or was measured against a
limiter state this doc never recorded; this round chooses to document
an honest, budget-respecting sample size instead of silently working
around the real limit. The burst-rejection measurement, which
specifically needs to observe the limiter's own enforcement, uses a
separate fresh credential so its own starting state is unambiguous
(0 prior events).

No number above is invented — every figure came from this exact,
stated run against this round's corrected code; see the final report
for the raw session log. These numbers describe one developer machine
under light, sequential load, not a production capacity claim.

## 14. Security limitations (honest, not exhaustive)

- Rate limiting is in-process only (§5) — not safe across multiple
  replicas without a shared store. The correction round's fix (§6b
  item 6) closes the single-instance credential-id bypass but does not
  change this cross-replica limitation.
- `SlidingWindowRateLimiter`'s memory bound (§6b item 6) evicts the
  single least-recently-used key once `max_tracked_keys` is reached
  and nothing is idle to prune — a true hard bound on memory, at the
  cost of occasionally resetting one active key's own budget early
  under a sustained burst from many simultaneously-active sources. For
  the real auth-failure limiter (now keyed solely by connecting
  address) this trade-off is unlikely to matter in practice; documented
  here because the limiter class itself is a general-purpose component.
- No retention/rollup policy on `telemetry_samples` — unbounded growth
  over a long-running real deployment; out of scope this round (noted
  in V14's own migration comment).
- `mean_latency_seconds` (§6b item 4) is a real, correctly-weighted
  mean, not a percentile — true request-level p50/p95 would require
  storing each data point's real `bucketCounts`/`explicitBounds` (a
  real, additive schema change), out of scope for this round's
  "smallest correct solution."
- Cumulative-to-delta conversion is not implemented (§6b item 1) — a
  client that can only emit CUMULATIVE histograms cannot use this
  endpoint at all today; this is a real, documented gap, not silently
  worked around.
- Only the Python official SDK path was independently verified this
  round (§6b item 3) — Node/Java/Go onboarding snippets were corrected
  to the same protocol/endpoint/temporality pattern but remain
  unverified, and the UI says so.
- `GET /api/v1/incidents` (used by the service-detail page's "Recent
  incidents" section) filters to this service client-side via
  `source_fingerprint`; there is no dedicated "incidents by service"
  backend endpoint yet. Still real, still organization-scoped at the
  API layer — just not purpose-built for this one query shape.
- Traces/logs are not implemented (§6) — explicitly disabled, not
  half-built.
- The detector's threshold (50% error rate, minimum 3 requests, 5-
  minute window) is a simple, fixed, documented rule — not a
  statistical anomaly model.

## 15. Operational setup

```bash
make db-up          # applies V1-V16 (idempotent)
# Register a service, generate a credential in the real web console
# (Services -> a service -> "Generate credential"), then:
OTEL_INGEST_ENDPOINT=http://127.0.0.1:8000/api/v1/telemetry/otlp/v1/metrics \
OTEL_BEARER_TOKEN=<the credential shown once> \
python3 samples/otel-sample-app/app.py
curl http://127.0.0.1:9100/work   # generate real traffic
```

See `samples/otel-sample-app/README.md` for the full sample-app
walkthrough, including triggering and resolving a real test incident.
