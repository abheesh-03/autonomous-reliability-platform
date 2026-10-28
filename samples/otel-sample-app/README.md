# otel-sample-app (Phase 16 Gate 9)

A disposable, standalone sample external application used only to prove
the real Phase 16 OpenTelemetry onboarding path end to end. It is
**deliberately separate** from this repository's own
checkout/payment/inventory/notification demonstration services, runs
**outside** the Docker Compose stack, and is **not** part of the
platform's own architecture — it stands in for a real customer's own
external application.

Pure Python standard library — no dependencies to install.

## What it does

- Serves `GET /work` on `:9100` — a small, real, variable-duration
  request that returns 200 normally, or 500 when fail mode is enabled.
- Serves `POST /fail-mode` (`{"enabled": true|false}`) to toggle a
  controlled test failure on/off.
- Every few seconds, exports a real, authenticated OTLP/HTTP JSON
  metrics batch (the `http.server.request.duration` histogram) to a
  running control-plane's telemetry ingestion endpoint.

It is a **minimal, hand-built OTLP/HTTP JSON client**, not the official
OpenTelemetry Python SDK — see
`docs/architecture/phase-16-secure-telemetry-onboarding.md` for why,
and for which SDK-based language paths were (and were not)
independently validated this round.

## Usage

1. Register a service and generate an OpenTelemetry integration
   credential for it in the real web console (`/services/<id>`) —
   copy the real `cred_xxx.yyy` bearer token shown once.

2. Run the sample app:

   ```bash
   OTEL_INGEST_ENDPOINT=http://127.0.0.1:8000/api/v1/telemetry/otlp/v1/metrics \
   OTEL_BEARER_TOKEN=cred_xxx.yyy \
   python3 samples/otel-sample-app/app.py
   ```

3. Generate real traffic:

   ```bash
   for i in $(seq 1 20); do curl -s http://127.0.0.1:9100/work > /dev/null; done
   ```

4. Within a few seconds, the service's real telemetry summary
   (`/services/<id>` in the web console) shows "Receiving telemetry"
   with real request rate / p50 / p95 latency.

5. Trigger a controlled test failure:

   ```bash
   curl -s -X POST http://127.0.0.1:9100/fail-mode -d '{"enabled": true}'
   for i in $(seq 1 10); do curl -s http://127.0.0.1:9100/work > /dev/null; done
   ```

   Once the elevated error rate is reported, a real, tenant-scoped
   incident appears for this service within one export interval.

6. Turn fail mode back off to watch the incident auto-resolve on the
   next healthy export:

   ```bash
   curl -s -X POST http://127.0.0.1:9100/fail-mode -d '{"enabled": false}'
   ```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `OTEL_INGEST_ENDPOINT` | `http://127.0.0.1:8000/api/v1/telemetry/otlp/v1/metrics` | Where to export |
| `OTEL_BEARER_TOKEN` | *(none — exports will 401)* | The real credential from the web console |
| `OTEL_SAMPLE_APP_PORT` | `9100` | This app's own listen port |
| `OTEL_EXPORT_INTERVAL_SECONDS` | `2` | How often to flush aggregated metrics |
