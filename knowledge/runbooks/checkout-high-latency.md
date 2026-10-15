# CheckoutHighLatency

## What this alert means

Prometheus fires `CheckoutHighLatency` (severity: `warning`,
component/service: `checkout-service`) when the p95 latency for
`POST /checkouts` — computed via `histogram_quantile(0.95, ...)` over
`http_server_request_duration_seconds_bucket{service_name="checkout-service",
http_route="/checkouts"}` — exceeds 1 second, sustained for at least 2
minutes (`observability/prometheus/rules/alerts.yml`). The 1s
threshold was deliberately set far above this stack's own observed
local baseline (roughly 10-25ms end to end, confirmed by firing 20 real
requests against a running stack), so this is a large, deliberate
margin, not a tight bound tuned to incidental noise. This is a
`warning`, not `critical` — unlike `CheckoutServerErrors`, elevated
latency alone does not mean requests are failing.

This runbook is contextual background knowledge for an investigation
performed by `services/investigator-service`. It is never itself
evidence about the current incident, and historical similarity to a
past latency incident is never proof the same cause applies now.

## Known dependency order

Same fixed, sequential call order as every `POST /checkouts` request:
`payment-service` → `inventory-service` → `notification-service`,
stopping on first failure. Latency (unlike an outright failure) can
accumulate across ALL THREE downstream calls, since a slow-but-
eventually-successful call still lets checkout-service proceed to the
next step — so high checkout-service latency does not by itself
identify which single downstream dependency is slow; it could be one
dependency, or a smaller slowdown compounding across all three.

## Evidence that distinguishes which downstream dependency is slow

- **Prometheus**: compare p95 (via the same
  `histogram_quantile(0.95, ...)` pattern) for
  `http_client_request_duration_seconds_bucket{service_name="checkout-service"}`
  grouped by `server_address`, against each downstream service's OWN
  server-side latency
  (`http_server_request_duration_seconds_bucket{service_name="payment-service"|"inventory-service"|"notification-service"}`).
  A downstream service whose own server-side p95 is low while
  checkout-service's CLIENT-side latency to that same
  `server_address` is high points at network/transport overhead
  between the two containers rather than the downstream service's own
  processing; the reverse points at the downstream service itself.
- **Tempo**: a candidate trace's CLIENT span durations for each
  downstream branch (payment/inventory/notification are sibling
  branches, not sequential in trace structure, but checkout-service's
  own orchestration logic still calls them sequentially) — again, a
  time+service correlation only, not a confirmed causal link.
- **Loki**: as with `CheckoutServerErrors`, only `payment-service` and
  `notification-service` currently log per request;
  `checkout-service` and `inventory-service` only log at startup.

## Known observability limitations

- No log/trace correlation (no service emits a trace/span ID into its
  logs).
- No dedicated Tempo/traces dashboard panel exists; trace inspection
  is via Tempo's own query API or the investigator's candidate-trace
  evidence.
- The 1s threshold is a large margin above observed local baseline,
  not a production SLA — there is no formally defined latency SLA
  anywhere in this repository.

## Useful read-only checks

- Compare checkout-service's CLIENT-side p95 per `server_address`
  against each downstream service's own SERVER-side p95 for the same
  window.
- Check whether `CheckoutServerErrors` is ALSO firing in the same
  window — sustained high latency immediately before a burst of 5xx
  responses can be a different signal than latency alone with no
  accompanying error-rate increase.
- Review candidate Tempo traces rooted at checkout-service for
  per-branch span duration, time+service correlation only.

This runbook never recommends restarting, scaling, or otherwise
modifying any service — only read-only inspection.
