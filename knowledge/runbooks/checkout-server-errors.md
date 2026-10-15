# CheckoutServerErrors

## What this alert means

Prometheus fires `CheckoutServerErrors` (severity: `critical`,
component/service: `checkout-service`) when checkout-service's own
`http_server_request_duration_seconds_count` series shows a nonzero
average rate of `http_response_status_code=~"5.."` responses over a
5-minute window, sustained for at least 2 minutes
(`observability/prometheus/rules/alerts.yml`). A genuine client-side
`4xx` (e.g. a failed `POST /checkouts` request-body validation) never
contributes to this expression — only a real `5xx` does.

This is investigated after the fact through
`services/investigator-service`, which reads this exact incident's
real evidence from control-plane, Prometheus, Loki, and Tempo. This
runbook is contextual background knowledge for that investigation —
it is never itself evidence about the current incident, and it is
never proof that any specific past cause is the current one.

## Known dependency order

`checkout-service`'s `POST /checkouts` calls exactly three downstream
services, synchronously, in this fixed order, stopping immediately on
the first failure:

1. `payment-service` — `POST /payments/authorize`
2. `inventory-service` — `POST /inventory/reservations`
3. `notification-service` — `POST /notifications`

Payment, inventory, and notification never call each other or call
back into checkout-service. A `5xx` from checkout-service is a
downstream failure normalized by checkout-service's own
`@RestControllerAdvice` (non-2xx, a connection failure, an empty
response, an unexpected business status, or a malformed/inconsistent
`200` body) into a fixed `{"error": "downstream_failure", "service":
"...", "message": "Downstream service request failed"}` body — never
a stack trace or the raw downstream response. Because the call order
is fixed and stops on first failure, a failure at payment-service
means inventory-service and notification-service were never called at
all for that request.

## Evidence that distinguishes which downstream dependency failed

- **Prometheus**: `http_client_request_duration_seconds_count` /
  `_bucket{service_name="checkout-service"}`, grouped by
  `server_address`. The three possible values are
  `payment-service`, `inventory-service`, and `notification-service`
  — whichever one shows elevated error/latency activity (or an outright
  absence of samples for the services AFTER it in the call order, since
  they were never called) is the one that failed first.
- **Tempo**: candidate traces rooted at `checkout-service` in the
  incident window (see the investigator's own Tempo evidence item —
  this is a time+service correlation only, explicitly NOT a confirmed
  causal link, since none of the four application services currently
  emit a trace or span ID into their own logs). A trace whose span set
  stops after the payment CLIENT span (no inventory/notification
  spans) is consistent with payment-service being the first failure;
  a trace with payment+inventory CLIENT spans but no notification span
  is consistent with inventory-service failing.
- **Loki**: `checkout-service` and `inventory-service` currently only
  log at container startup — there is no per-request access logging
  for either (a known, real observability limitation, not specific to
  this incident). `payment-service` and `notification-service` do log
  per request, so a log line from one of those two services in the
  incident window is more likely to carry direct information than the
  absence of one from checkout-service/inventory-service.

## Known observability limitations

- No log/trace correlation: none of the four application services'
  current log output contains a trace or span ID.
- `checkout-service` and `inventory-service` have no per-request
  access logging.
- Tempo evidence is always a *candidate* trace (time + root-service
  match only), never a confirmed causal link to a specific incident.

## Useful read-only checks

- Compare `http_client_request_duration_seconds_count` across the
  three `server_address` values for the incident window.
- Look for the last downstream service with a CLIENT span in a
  candidate Tempo trace rooted at checkout-service.
- Check whether payment-service / notification-service logged
  anything at all in the incident window (inventory-service and
  checkout-service won't have per-request entries regardless).
- Confirm via `GET /api/v1/incidents/{id}/events` whether this exact
  incident has previously recurred (a resolved incident with the same
  `source_fingerprint` recurring is visible as a new row, since
  resolved/closed history is preserved, never overwritten).

This runbook never recommends restarting, scaling, or otherwise
modifying any service — only read-only inspection.
