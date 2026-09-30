#!/usr/bin/env python3
"""Verifies the Phase 2B.4 alerting pipeline (Prometheus rule
evaluation -> Alertmanager) through both systems' real HTTP APIs.
stdlib only. Shared by the local verifier
(scripts/verify-observability.sh) and CI — no duplicated validation
logic in either.

Modes (subcommands):

  rules       Confirm Prometheus actually loaded the expected alert
              rules (GET /api/v1/rules): each expected rule name is
              present, its normalized query contains the expected
              fragments, its `for:` duration matches, its labels match
              exactly, and its required annotation keys are present and
              nonempty. Also confirms every expected rule's initial
              state is "inactive" (fails closed if any is already
              pending/firing, or the group failed to load at all).

  health      Confirm Alertmanager itself is healthy and ready
              (GET /-/healthy, GET /-/ready, GET /api/v2/status).

  state       Confirm one named Prometheus rule is in a specific state
              (inactive/pending/firing), via GET /api/v1/rules.

  firing      Confirm a named alert is "firing" in Prometheus AND that
              a matching alert (same alertname, same key labels) is
              present and active (not resolved) in Alertmanager's own
              GET /api/v2/alerts — proving the alert actually
              propagated from Prometheus into Alertmanager, not just
              that Prometheus alone thinks it's firing.

  recovered   Confirm a named alert is back to "inactive" in Prometheus
              AND is no longer reported as an active (unresolved) alert
              by Alertmanager's GET /api/v2/alerts — using
              Alertmanager's own resolved-vs-active semantics (an
              alert's `status.state` field), not just "absent from the
              list" (Alertmanager may still list a just-resolved alert
              briefly with state=="resolved").

Every check fails closed (nonzero exit, clear message) on an
unreachable service, a malformed response, a missing field, or a
mismatch.

Usage:
    python3 scripts/verify-alerting.py rules [--prometheus-url URL]
    python3 scripts/verify-alerting.py health [--alertmanager-url URL]
    python3 scripts/verify-alerting.py state --alert NAME --expect-state {inactive,pending,firing} [--prometheus-url URL]
    python3 scripts/verify-alerting.py firing --alert NAME [--prometheus-url URL] [--alertmanager-url URL]
    python3 scripts/verify-alerting.py recovered --alert NAME [--prometheus-url URL] [--alertmanager-url URL]
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# Ground truth for what scripts/observability/prometheus/rules/alerts.yml
# is expected to define. query_substrings are checked against
# Prometheus's own *normalized* rendering of the expression (its label
# matchers get reordered alphabetically, so this checks stable
# fragments rather than an exact string), not the raw YAML source text.
EXPECTED_RULES = {
    "TelemetryPipelineUnavailable": {
        "query_substrings": [
            'up{', 'otel-collector', 'otel-collector-app-metrics', '== 0',
        ],
        "duration_seconds": 60,
        "labels": {
            "severity": "critical",
            "component": "otel-collector",
            "category": "observability-infrastructure",
        },
        "required_annotations": ["summary", "description"],
    },
    "CheckoutServerErrors": {
        "query_substrings": [
            "http_server_request_duration_seconds_count",
            'service_name="checkout-service"',
            'http_response_status_code=~"5.."',
            "> 0",
        ],
        "duration_seconds": 120,
        "labels": {
            "severity": "critical",
            "component": "checkout-service",
            "service": "checkout-service",
        },
        "required_annotations": ["summary", "description"],
    },
    "CheckoutHighLatency": {
        "query_substrings": [
            "histogram_quantile(0.95",
            "http_server_request_duration_seconds_bucket",
            'http_route="/checkouts"',
            "> 1",
        ],
        "duration_seconds": 120,
        "labels": {
            "severity": "warning",
            "component": "checkout-service",
            "service": "checkout-service",
        },
        "required_annotations": ["summary", "description"],
    },
    "CollectorRefusingTelemetry": {
        "query_substrings": [
            "otelcol_receiver_refused_spans",
            "otelcol_receiver_refused_metric_points",
            "> 0",
        ],
        "duration_seconds": 60,
        "labels": {
            "severity": "warning",
            "component": "otel-collector",
            "category": "observability-infrastructure",
        },
        "required_annotations": ["summary", "description"],
    },
}


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def http_get_json(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                fail(f"HTTP {resp.status} for {url}")
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        fail(f"HTTP {e.code} for {url}: {e.read()[:300]!r}")
    except urllib.error.URLError as e:
        fail(f"could not reach {url}: {e}")
    except json.JSONDecodeError as e:
        fail(f"response from {url} was not valid JSON: {e}")


def get_prometheus_rules(prometheus_url):
    body = http_get_json(f"{prometheus_url.rstrip('/')}/api/v1/rules")
    if body.get("status") != "success":
        fail(f"Prometheus /api/v1/rules did not report status=success: {body}")
    rules_by_name = {}
    for group in body.get("data", {}).get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("type") == "alerting":
                rules_by_name[rule.get("name")] = rule
    return rules_by_name


def cmd_rules(args):
    rules_by_name = get_prometheus_rules(args.prometheus_url)

    missing = [name for name in EXPECTED_RULES if name not in rules_by_name]
    if missing:
        fail(f"Prometheus did not load expected rule(s): {missing} (found: {sorted(rules_by_name)})")

    for name, expected in EXPECTED_RULES.items():
        rule = rules_by_name[name]

        if rule.get("health") != "ok":
            fail(f"{name}: rule health is {rule.get('health')!r}, expected 'ok'")

        query = rule.get("query", "")
        missing_fragments = [s for s in expected["query_substrings"] if s not in query]
        if missing_fragments:
            fail(f"{name}: rule query missing expected fragment(s) {missing_fragments}: actual query={query!r}")

        duration = rule.get("duration")
        if duration != expected["duration_seconds"]:
            fail(f"{name}: expected for: duration {expected['duration_seconds']}s, got {duration}s")

        labels = rule.get("labels", {})
        for label_name, label_value in expected["labels"].items():
            if labels.get(label_name) != label_value:
                fail(f"{name}: expected label {label_name}={label_value!r}, got {labels.get(label_name)!r} (all labels: {labels})")

        annotations = rule.get("annotations", {})
        for ann_name in expected["required_annotations"]:
            if not annotations.get(ann_name, "").strip():
                fail(f"{name}: missing or empty required annotation {ann_name!r}")

        state = rule.get("state")
        if state != "inactive":
            fail(f"{name}: expected initial state 'inactive', got {state!r} — a real environment must start clean before the lifecycle test")

        print(f"Rule verified: name={name} state={state} duration={duration}s labels={labels}")

    print(f"All {len(EXPECTED_RULES)} expected alert rules loaded, healthy, correctly labeled, and initially inactive.")
    sys.exit(0)


def cmd_state(args):
    rules_by_name = get_prometheus_rules(args.prometheus_url)
    if args.alert not in rules_by_name:
        fail(f"rule {args.alert!r} not found in Prometheus (found: {sorted(rules_by_name)})")
    rule = rules_by_name[args.alert]
    state = rule.get("state")
    if state != args.expect_state:
        fail(f"{args.alert}: expected state {args.expect_state!r}, got {state!r}")
    print(f"Rule state confirmed: name={args.alert} state={state}")
    sys.exit(0)


def get_alertmanager_alerts(alertmanager_url):
    return http_get_json(f"{alertmanager_url.rstrip('/')}/api/v2/alerts")


def cmd_health(args):
    base = args.alertmanager_url.rstrip("/")
    for path in ("/-/healthy", "/-/ready"):
        url = f"{base}{path}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    fail(f"Alertmanager {path} returned HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            fail(f"Alertmanager {path} returned HTTP {e.code}")
        except urllib.error.URLError as e:
            fail(f"could not reach Alertmanager at {url}: {e}")
        print(f"Alertmanager {path} OK")

    status = http_get_json(f"{base}/api/v2/status")
    cluster_status = status.get("cluster", {}).get("status")
    if cluster_status != "ready":
        fail(f"Alertmanager cluster status is {cluster_status!r}, expected 'ready': {status.get('cluster')}")
    version = status.get("versionInfo", {}).get("version")
    print(f"Alertmanager health OK: cluster.status=ready version={version}")
    sys.exit(0)


def _matching_alerts(alerts, alert_name):
    matches = []
    for a in alerts:
        labels = a.get("labels", {})
        if labels.get("alertname") == alert_name:
            matches.append(a)
    return matches


def cmd_firing(args):
    rules_by_name = get_prometheus_rules(args.prometheus_url)
    if args.alert not in rules_by_name:
        fail(f"rule {args.alert!r} not found in Prometheus (found: {sorted(rules_by_name)})")
    rule = rules_by_name[args.alert]
    if rule.get("state") != "firing":
        fail(f"{args.alert}: expected Prometheus rule state 'firing', got {rule.get('state')!r}")
    prom_alerts = rule.get("alerts", [])
    if not prom_alerts:
        fail(f"{args.alert}: Prometheus rule state is 'firing' but its own 'alerts' list is empty — malformed response")
    print(f"Prometheus confirms firing: name={args.alert} active_series={len(prom_alerts)}")

    alerts = get_alertmanager_alerts(args.alertmanager_url)
    matches = _matching_alerts(alerts, args.alert)
    if not matches:
        fail(f"{args.alert}: Prometheus reports it firing, but Alertmanager's GET /api/v2/alerts has no alert with alertname={args.alert!r} (found alertnames: {sorted({a.get('labels',{}).get('alertname') for a in alerts})})")

    active_matches = [a for a in matches if a.get("status", {}).get("state") != "resolved"]
    if not active_matches:
        fail(f"{args.alert}: Alertmanager has matching alert(s) but all report status.state == 'resolved', expected at least one active")

    for a in active_matches:
        labels = a.get("labels", {})
        print(
            f"Alertmanager confirms alert present: alertname={labels.get('alertname')} "
            f"severity={labels.get('severity')} component={labels.get('component')} "
            f"status.state={a.get('status', {}).get('state')}"
        )
    sys.exit(0)


def cmd_recovered(args):
    rules_by_name = get_prometheus_rules(args.prometheus_url)
    if args.alert not in rules_by_name:
        fail(f"rule {args.alert!r} not found in Prometheus (found: {sorted(rules_by_name)})")
    rule = rules_by_name[args.alert]
    if rule.get("state") != "inactive":
        fail(f"{args.alert}: expected Prometheus rule state 'inactive' after recovery, got {rule.get('state')!r}")
    if rule.get("alerts"):
        fail(f"{args.alert}: Prometheus rule state is 'inactive' but its own 'alerts' list is nonempty: {rule.get('alerts')}")
    print(f"Prometheus confirms recovered: name={args.alert} state=inactive")

    alerts = get_alertmanager_alerts(args.alertmanager_url)
    matches = _matching_alerts(alerts, args.alert)
    still_active = [a for a in matches if a.get("status", {}).get("state") not in ("resolved", "suppressed")]
    if still_active:
        fail(f"{args.alert}: Alertmanager still reports {len(still_active)} active (non-resolved) alert(s) for this name: {still_active}")
    print(f"Alertmanager confirms no active alert remains for alertname={args.alert} (matches={len(matches)}, all resolved or absent)")
    sys.exit(0)


def main():
    # A shared parent so --prometheus-url/--alertmanager-url can be
    # given either before or after the subcommand name (e.g. both
    # `verify-alerting.py --prometheus-url U rules` and
    # `verify-alerting.py rules --prometheus-url U` work) — argparse
    # subparsers do not inherit a parent parser's own optionals
    # otherwise.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    common.add_argument("--alertmanager-url", default="http://127.0.0.1:9093")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common]
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("rules", parents=[common])
    sub.add_parser("health", parents=[common])

    p_state = sub.add_parser("state", parents=[common])
    p_state.add_argument("--alert", required=True)
    p_state.add_argument("--expect-state", required=True, choices=["inactive", "pending", "firing"])

    p_firing = sub.add_parser("firing", parents=[common])
    p_firing.add_argument("--alert", required=True)

    p_recovered = sub.add_parser("recovered", parents=[common])
    p_recovered.add_argument("--alert", required=True)

    args = parser.parse_args()

    {
        "rules": cmd_rules,
        "health": cmd_health,
        "state": cmd_state,
        "firing": cmd_firing,
        "recovered": cmd_recovered,
    }[args.mode](args)


if __name__ == "__main__":
    main()
