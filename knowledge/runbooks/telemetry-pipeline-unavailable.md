# TelemetryPipelineUnavailable

## What this alert means

Prometheus fires `TelemetryPipelineUnavailable` (severity: `critical`,
component: `otel-collector`, category: `observability-infrastructure`)
when `up{job=~"otel-collector|otel-collector-app-metrics"} == 0` for at
least 1 minute (`observability/prometheus/rules/alerts.yml`) — i.e.
Prometheus has failed to scrape either the Collector's own
self-telemetry job (`:8888`) or the application-telemetry relay job
(`:8889`) for four consecutive 15-second scrapes. Either job being
down means some or all of this platform's metrics pipeline is not
reaching Prometheus. This is the exact rule this repository's own
Phase 2B.4 lifecycle acceptance test and Phase 3C alert-ingestion
acceptance test both use, by deliberately stopping the real
`otel-collector` container.

This runbook is contextual background knowledge for an investigation
performed by `services/investigator-service`. It is never itself
evidence about the current incident.

## What this alert does NOT mean

This alert is about the **telemetry pipeline itself**
(`otel-collector`'s scrape targets), not about the four application
services' own health. `checkout-service`, `payment-service`,
`inventory-service`, and `notification-service` can all still be
fully healthy and successfully serving real traffic while this alert
is firing — they would just be failing to export their OTLP telemetry
(or exporting it into a Collector that isn't up to receive it) during
that window. Conflating this with an application outage is a common
investigation mistake.

## Known dependency order / architecture

`otel-collector` receives OTLP (gRPC `:4317`, HTTP `:4318`) from all
four application services, then fans out: metrics to its own
Prometheus exporter (`:8889`), traces to both its `debug` exporter
(container logs) and Tempo's OTLP receiver. `otel-collector` itself
has no shell/wget/curl in its official image, so there is no
Docker-level healthcheck for it — its liveness is proven only by
Prometheus successfully scraping it, which is exactly this alert's own
signal, inverted.

## Evidence that is actually available for this alert

- **Prometheus**: `up{job="otel-collector"}` and
  `up{job="otel-collector-app-metrics"}` directly — if the alert
  fired, at least one of these should show a real `0` value in the
  incident window.
- **Loki**: `otel-collector` does not emit application-level log
  lines of its own in the same way the four application services do;
  there is nothing meaningful to search for in its own log stream for
  this specific alert, beyond confirming the container's own
  start/stop container lifecycle lines (via Alloy's Docker-log
  collection, which still runs independent of whether otel-collector
  itself is up).
- **Tempo**: if the Collector's traces pipeline was down for the
  window, no NEW traces would have been exported to Tempo during that
  window — an absence of recent traces is consistent with, but not
  sole proof of, this specific alert (checkout traffic itself could
  simply have been low).
- **control-plane audit trail**: Phase 3C's real Collector-outage
  acceptance test proves this exact alert, delivered through
  Alertmanager's real webhook, is what originally creates/resolves the
  corresponding `reliability.incidents` row for this alert name — the
  incident's own audit timeline (`GET /api/v1/incidents/{id}/events`)
  is real evidence of when it fired/resolved from control-plane's own
  perspective.

## Known observability limitations

- No outbound alert notification to an external system — Alertmanager's
  one receiver is control-plane's own internal webhook, not
  email/Slack/PagerDuty.
- `otel-collector` has no Docker-level healthcheck of its own.

## Useful read-only checks

- Check `up{job=~"otel-collector|otel-collector-app-metrics"}` directly
  for the incident window.
- Check whether application services' own HTTP server metrics
  (`http_server_request_duration_seconds_count`) show a gap during the
  same window — a gap there (not just on the Collector's own `up`
  metric) indicates telemetry was genuinely not reaching Prometheus,
  not merely that the Collector's own scrape briefly hiccuped.
- Review `GET /api/v1/incidents/{id}/events` for this incident's full
  audit timeline (creation, any repeat observations, resolution).

This runbook never recommends restarting, scaling, or otherwise
modifying any service — only read-only inspection.
