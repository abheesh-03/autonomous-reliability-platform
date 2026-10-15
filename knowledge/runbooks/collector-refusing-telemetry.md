# CollectorRefusingTelemetry

## What this alert means

Prometheus fires `CollectorRefusingTelemetry` (severity: `warning`,
component: `otel-collector`, category: `observability-infrastructure`)
when `otel-collector`'s own self-telemetry shows a nonzero average
rate of refused spans or refused metric points over a 5-minute window
(`sum(rate(otelcol_receiver_refused_spans{job="otel-collector"}[5m]))
+ sum(rate(otelcol_receiver_refused_metric_points{job="otel-collector"}[5m])) > 0`),
sustained for at least 1 minute
(`observability/prometheus/rules/alerts.yml`). Both counters are
always present as real series (value `0` at rest, never absent), so
this only fires on genuine nonzero refusal activity — e.g. a malformed
OTLP payload from one of the four application services — never merely
because telemetry volume is low.

This runbook is contextual background knowledge for an investigation
performed by `services/investigator-service`. It is never itself
evidence about the current incident.

## What this alert does NOT mean

This is distinct from `TelemetryPipelineUnavailable`: the Collector is
UP and reachable (otherwise its own self-telemetry, including these
exact counters, would not be scrapeable at all) — it is actively
receiving data and REJECTING some of it, not failing to receive
anything. A service whose own telemetry is being refused may appear
perfectly healthy on its own `/health` endpoint while quietly losing
observability coverage.

## Known dependency order / architecture

All four application services (`checkout-service`, `payment-service`,
`inventory-service`, `notification-service`) export OTLP metrics and
traces to `otel-collector`. A malformed/incompatible payload from any
one of them could drive this alert; the aggregate expression above
does not by itself identify WHICH service's export was refused.

## Evidence that distinguishes which service's telemetry is being refused

- **Prometheus**: `otelcol_receiver_refused_spans` and
  `otelcol_receiver_refused_metric_points` are both labeled by
  receiver/transport in the Collector's own self-telemetry; comparing
  their values against each of the four services' own export activity
  in the same window (e.g. whether one service's
  `http_client_request_duration_seconds_count`/
  `http_server_request_duration_seconds_count` growth suddenly stalls)
  can help narrow which service's export attempts coincide with the
  refusal spike.
- **otel-collector container logs**: the Collector's own `debug`
  exporter output (visible via its container logs, the same mechanism
  `scripts/parse-checkout-trace.py` already reads for trace
  verification) may show the specific rejected payload's shape,
  depending on log verbosity at the time.
- **Loki**: as with the other alerts, `checkout-service` and
  `inventory-service` have no per-request access logging;
  `payment-service` and `notification-service` do.

## Known observability limitations

- No log/trace correlation.
- No dedicated Tempo/traces dashboard panel.
- This repository's four application services are not independently
  instrumented with their OWN "export failed" metric — only the
  Collector's receiver-side refusal counters exist.

## Useful read-only checks

- Compare `otelcol_receiver_refused_spans` /
  `otelcol_receiver_refused_metric_points` against each service's own
  export activity for the incident window.
- Review the Collector's own container logs for the incident window.
- Confirm via Prometheus whether `TelemetryPipelineUnavailable` is ALSO
  firing — a Collector that is both refusing some telemetry AND
  periodically failing its own scrape is a different situation than
  one that is merely rejecting a subset of payloads while remaining
  fully scrapeable.

This runbook never recommends restarting, scaling, or otherwise
modifying any service — only read-only inspection.
