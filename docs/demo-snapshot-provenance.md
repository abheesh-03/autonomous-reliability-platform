# Public recorded-demo snapshot: provenance

This records exactly how the data bundled into `services/web-console/lib/demo/snapshot.ts` (the public, read-only `/demo` experience's data source) was captured. Both scenarios below are real — produced by running this repository's own code against a real, disposable, isolated stack — never fabricated, mocked, or hand-written to "look right."

Captured: 2026-11-01.

## Isolated capture environment

A fresh `rsync` checkout of the repository, with every hardcoded host port in `docker-compose.yml` offset by +10000, `WEB_CONSOLE_TRUSTED_ORIGIN` updated to match, and a fresh `.env` (`cp .env.example .env`, with `POSTGRES_PORT=15432`, `INVESTIGATOR_LLM_PROVIDER=stub`, `PAYMENT_FAULT_INJECTION_ENABLED=true` added — all independently generated, never copied from the real repo's own `.env`). Brought up via `make check && make db-up && make db-migrate && make db-status` — all passed. Docker Compose project name: `phase18-demo-checkout` (derived from the isolated checkout's own directory name; every `docker compose`/`make` invocation ran from inside that directory, so Compose selected that isolated project implicitly from its directory (these were not explicit `--project-name` arguments)). Torn down completely afterward (`docker compose down -v --rmi local`, isolated checkout deleted) — see "Teardown and safety check" below.

**Capture-time build preparation:** the in-progress Phase 18 demo shell initially imported a nonexistent `Github` icon from `lucide-react`; the isolated capture copy used `ExternalLink`, and that correction is also present in the final source. While the real data was being captured, the isolated copy needed a temporary `snapshot.ts` placeholder to compile the new demo routes. That placeholder was discarded and replaced with the captured, sanitized snapshot. These were issues in the in-progress Phase 18 implementation, not pre-existing defects in the baseline project.

## Scenario 1: incident, investigation, approval, remediation, recovery

**Source**: this repository's own existing Playwright acceptance test, `services/web-console/e2e/phase9-workflow.spec.ts`, run for real against the isolated stack above. This test drives control-plane's documented **legacy local-development mode** (`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=false`, the fixed `00000000-0000-0000-0000-000000000001` legacy organization) — not a multi-tenant/secure-mode run, and this is disclosed here accurately rather than implied otherwise. `INVESTIGATOR_LLM_PROVIDER=stub` was set for the whole stack: the investigation was produced by investigator-service's own deterministic stub provider — confirmed in the captured `investigation_report.provider` field (`{"provider": "stub", "model": "stub-deterministic-v1"}`). **No live or paid LLM call was made.**

Real sequence exercised by the test, end to end, through the real browser UI and real backend HTTP APIs (never a mocked backend, never a direct database write of incident state): a real controlled payment-authorization fault was enabled → real sustained failing checkout traffic → a real Prometheus `CheckoutServerErrors` alert fired → a real Alertmanager webhook created the incident → a real signed-in browser session clicked "Start AI investigation" then "Run investigation" → the agent reached `await_human_approval` → a real human approval click → real `tool-gateway` execution → real automatic recovery verification → the alert naturally recovered → the incident resolved via Alertmanager's own webhook. Total real run time: 7.7 minutes, exit 0.

**Evidence bar required before using this run** (all independently confirmed against the real `GET /api/v1/agent-runs/{id}` response before it was written into the snapshot):
- `status`: `"completed"` ✓
- `remediation_status`: `"succeeded"` ✓
- `execution_result.status`: `"succeeded"` ✓
- `recovery_verification`: `{proposal_succeeded: true, fault_inactive: true, target_healthy: true}` ✓ (all three real, not assumed)
- `investigation_report`: present, non-trivial — 32 real evidence items were originally collected across control_plane/prometheus/loki/tempo, a real observation, and `source_outcomes` all `"ok"` ✓

**Real ids**: incident `e05f2bc4-f3e2-446c-a4e6-56bb0f0903f3`, agent run `f57c5d6e-4f96-4a7f-a730-b2016c3f42bd`, remediation proposal `b68abf69-1843-4a2d-b61f-be094ed59488`.

**One deliberate redaction beyond the snapshot type's own field allowlist**: the real `investigation_report.evidence` array included 20 raw Loki log-line entries (original ids E8–E27) — Java stack traces with internal file paths, a Docker container hostname (`5b26aabf5b00`), and local `IP:port` pairs from the demo commerce services' own application logs. These are exactly "raw private logs"/"internal addresses," so all 20 were omitted from the public snapshot. Nothing else in the evidence array was altered, and the remaining items keep their original `E`-numbers (so the sequence has real gaps — E1–E7 and E28–E32 — rather than being renumbered to look complete). The one observation in this report only cites `E1`, which is retained, so no reference is left dangling.

Excluded everywhere in this scenario, per the explicit allowlist in `lib/demo/types.ts`: `organization_id`, `decided_by_user_id`, `decided_by_organization_id`, any `metadata` field on incident/remediation events (both were inspected directly — contents were a fingerprint hash, timestamps, and a short human-readable execution detail string; none contained anything unsafe, but the type excludes the field regardless, by design).

## Scenario 2: external tenant OTLP telemetry (separate, unrelated org/service)

**This is a different path from Scenario 1** — a deliberately separate real capture, never merged with or presented as part of the incident/remediation story above. It exercises Phase 16's self-service tenant onboarding, not the alert/remediation pipeline, and never involved `tool-gateway` or human approval.

Real sequence, all through real HTTP calls against the same isolated stack: a real sign-up (`POST /api/auth/sign-up/email`) → the real verification link extracted from web-console's own container logs (local-development delivery, never emailed) → real email verification → real sign-in → a **freshly created, separate organization** (`POST /api/auth/organization/create` + `organization/set-active`, distinct from Scenario 1's legacy organization) → a real registered service (`POST /api/services`) → a real integration credential (`POST /api/services/{id}/integrations` — the response's `bearer_token` was used once, locally, to send the metric below, and was never written anywhere in the snapshot or this document) → one real metric exported with the **official OpenTelemetry Python SDK** (`opentelemetry-exporter-otlp-proto-http`) to control-plane's local-dev OTLP endpoint (`http://127.0.0.1:<offset-port>/api/v1/telemetry/otlp/v1/metrics`, delta temporality). Confirmed landed by direct query against `reliability.telemetry_samples` before being used.

**Real ids**: service `413c286a-32c7-41f1-9137-c9be85b92f5f`, credential `51bb8915-f10a-436d-95e5-7491b1964191` (public credential id `cred_02Wfpb8cw2dudRD0wxJALQ` — never the secret bearer token).

**Telemetry summary numbers** were read directly from the real, authenticated `/services/{id}` page's own rendered output (its `TelemetryPanel` component), not recomputed independently — `request_rate_per_minute: 0.1`, `error_rate: 0.0`, `mean_latency_seconds` displayed as "40 ms" (the snapshot stores the precise `0.0395` computed from the two real recorded samples' summed duration ÷ count, which rounds to the same displayed value). `request_count`/`error_count` (`2`/`0`) came from a direct, real query of `reliability.telemetry_samples` for this credential, since the backend doesn't render raw counts on that page. `last_observed_at`/credential `created_at`/`last_verified_telemetry_at` are the real timestamps from the credential's own API response and the samples table.

Excluded: `organization_id`, `created_by_user_id`, and — always — the secret `bearer_token`, which this UI never displays again after credential creation and which was used exactly once, locally, to make the real SDK call above.

## Teardown and safety check

The isolated stack was torn down completely (`docker compose down -v --rmi local` from inside the isolated checkout) and the checkout directory deleted. The real, long-running developer dev stack (`autonomous-reliability-platform-*` containers) was confirmed unaffected, before and after this capture, by comparing its real `reliability_platform_dev` database row counts directly:

| | before | after |
|---|---|---|
| `reliability.incidents` | 169 | 169 |
| `reliability.services` | 3 | 3 |
| `auth.user` | 33 | 33 |
| `reliability.telemetry_samples` | 12 | 12 |
| `auth.organization` | 19 | 19 |

Identical in both counts — the real dev stack was never touched.
