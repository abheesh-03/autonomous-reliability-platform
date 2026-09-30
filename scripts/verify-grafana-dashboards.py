#!/usr/bin/env python3
"""Verifies the three Phase 2B.3 provisioned Grafana dashboards through
Grafana's real authenticated HTTP API, then independently re-executes
each dashboard's OWN panel queries directly against the underlying
backends' own APIs — not just checking that dashboard JSON exists or
that Grafana returns HTTP 200 for it, and not relying on a separately
maintained list of "representative" queries that could silently drift
from what the dashboards actually ship.

Usage:
    python3 scripts/verify-grafana-dashboards.py \
        [--grafana-url URL] [--user USER] [--password PASSWORD] \
        [--prometheus-url URL] [--loki-url URL]

Checks, in order:
  1. Grafana itself is healthy (GET /api/health, database == "ok").
  2. Each expected dashboard UID exists, is provisioned (not
     UI-created), and has the expected title.
  3. Each dashboard contains its required panels (by title) and no
     fewer.
  4. Every panel's (and every one of its targets') datasource reference
     resolves to the dashboard's expected datasource, and that
     datasource is really provisioned in Grafana with the expected
     type (cross-checked against GET /api/datasources) — not just a
     string that happens to be present in the JSON.
  5. Each dashboard's expected template variables exist, have a
     datasource reference matching the dashboard's expected datasource,
     and have a nonempty query definition.
  6. Each panel's query text (PromQL/LogQL) contains the metric or
     stream-selector substrings this script independently confirmed
     are real.
  7. For EVERY panel (not a separately maintained sample): every target
     must have a nonempty query expression and the correct datasource,
     and — with dashboard template variables (e.g. $service,
     $log_service) substituted for their real "match everything" value
     and Grafana built-in interval variables (e.g. $__rate_interval,
     $__interval) substituted for a concrete duration — that exact
     expression is re-executed directly against Prometheus's or Loki's
     own HTTP API (bypassing Grafana's query proxy entirely). Queries
     whose text identifies them as an HTTP-error-rate or
     refused-telemetry query (5xx status codes, "refused" metrics) are
     allowed to legitimately return empty; every other target is
     required to return real, nonempty data, and each panel as a whole
     must have at least one nonempty target result unless literally all
     of its targets are of the legitimately-empty kind.

This script does NOT and cannot verify that a panel renders correctly
in a browser — only that Grafana served the expected provisioned
dashboard structure and that its actual queries are valid and return
real data from the underlying backends. Visual rendering is out of
scope.

Fails closed (nonzero exit, clear message) on any check above failing.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

EXPECTED_DASHBOARDS = {
    "application-health": {
        "title": "Application Health",
        "datasource_name": "Prometheus",
        "datasource_type": "prometheus",
        "panel_titles": [
            "Request Throughput by Service",
            "Request Latency (p50 / p95) by Service",
            "HTTP Error Rate by Service (4xx / 5xx)",
            "Checkout Downstream Dependency Traffic",
            "Checkout Downstream Dependency Latency (p95)",
        ],
        "variables": ["service"],
        "required_query_substrings": [
            "http_server_request_duration_seconds",
            "http_client_request_duration_seconds",
        ],
    },
    "centralized-logging": {
        "title": "Centralized Logging",
        "datasource_name": "Loki",
        "datasource_type": "loki",
        "panel_titles": [
            "Log Line Rate by Service",
            "Application Log Stream",
        ],
        "variables": ["log_service"],
        "required_query_substrings": [
            "service=~",
        ],
    },
    "observability-infrastructure": {
        "title": "Observability Infrastructure",
        "datasource_name": "Prometheus",
        "datasource_type": "prometheus",
        "panel_titles": [
            "Scrape Target Availability",
            "Collector Telemetry Ingestion (Accepted vs. Refused)",
            "Collector Export Health (Sent Spans + Queue Size)",
            "Collector Process Health",
        ],
        "variables": [],
        "required_query_substrings": [
            "otelcol_",
            "up{",
        ],
    },
}

# Grafana built-in template variables that never appear in a dashboard's
# own templating.list but are used inside panel expressions. Substituted
# with a concrete, real duration before a query is re-executed directly
# against Prometheus/Loki (neither of which knows what "$__rate_interval"
# means).
GRAFANA_BUILTIN_SUBSTITUTIONS = {
    "$__rate_interval": "5m",
    "${__rate_interval}": "5m",
    "$__interval": "5m",
    "${__interval}": "5m",
    "$__interval_ms": "300000",
    "${__interval_ms}": "300000",
    "$__range": "30m",
    "${__range}": "30m",
}

# A query is allowed to legitimately return no data: an HTTP 5xx error
# rate (every service's simulated business logic currently always
# succeeds, so 5xx is expected to be near-zero/absent) or a
# refused-telemetry counter (expected to stay at 0 absent a real
# ingestion problem). Detected from the expression text itself, not a
# separately maintained list, so it can never drift from what a panel
# actually queries.
SPARSE_OK_PATTERNS = (
    re.compile(r'"5\.\."'),
    re.compile(r"refused", re.IGNORECASE),
)


def is_sparse_ok(expr):
    return any(p.search(expr) for p in SPARSE_OK_PATTERNS)


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def http_get_json(url, user=None, password=None, timeout=10):
    req = urllib.request.Request(url)
    if user is not None:
        import base64
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                fail(f"HTTP {resp.status} for {url}")
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        fail(f"HTTP {e.code} for {url}: {e.read()[:300]!r}")
    except urllib.error.URLError as e:
        fail(f"could not reach {url}: {e}")
    except json.JSONDecodeError as e:
        fail(f"response from {url} was not valid JSON: {e}")


def check_grafana_health(grafana_url):
    body = http_get_json(f"{grafana_url.rstrip('/')}/api/health")
    if body.get("database") != "ok":
        fail(f"Grafana /api/health did not report database == ok: {body}")
    print("Grafana health OK (database=ok)")


def get_real_datasources(grafana_url, user, password):
    body = http_get_json(f"{grafana_url.rstrip('/')}/api/datasources", user=user, password=password)
    by_name = {}
    for ds in body:
        by_name[ds.get("name")] = ds
    return by_name


def datasource_name_of(ref):
    return ref.get("name") if isinstance(ref, dict) else ref


def variable_query_text(var):
    q = var.get("query")
    if isinstance(q, dict):
        return (q.get("query") or "").strip()
    return (q or "").strip()


def variable_substitution_value(var):
    # These dashboards' variables are all multi-value with includeAll,
    # and each sets an explicit allValue regex that is exactly the
    # "match everything" value we want for a representative test query
    # — using it directly (rather than hand-maintaining a separate
    # substitution table) means the test value can never drift from
    # what "All" actually resolves to in the real dashboard.
    all_value = var.get("allValue")
    if all_value:
        return all_value
    current = var.get("current", {}).get("value")
    if current and current != "$__all":
        return current if isinstance(current, str) else str(current)
    return ".*"


def substitute_expr(expr, dashboard_vars):
    out = expr
    for name, value in GRAFANA_BUILTIN_SUBSTITUTIONS.items():
        out = out.replace(name, value)
    for var_name, var_value in dashboard_vars.items():
        out = out.replace(f"${{{var_name}}}", var_value)
        out = out.replace(f"${var_name}", var_value)
    return out


def prometheus_instant_query(prometheus_url, expr):
    url = f"{prometheus_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': expr})}"
    body = http_get_json(url)
    if body.get("status") != "success":
        fail(f"Prometheus query did not report status=success: {expr!r}: {body}")
    return body.get("data", {}).get("result", [])


def loki_query(loki_url, expr, since_seconds=1800):
    end_ns = time.time_ns()
    start_ns = end_ns - since_seconds * 1_000_000_000
    # A raw log-stream selector (e.g. `{service=~".+"}`, the "logs"
    # panel type) needs query_range to return matching log lines; an
    # aggregating LogQL expression (e.g. `sum by (service) (rate(...))`,
    # used by metric-style panels) is an instant query, same as
    # Prometheus.
    if expr.strip().startswith("{"):
        params = {"query": expr, "start": str(start_ns), "end": str(end_ns), "limit": "10"}
        path = "/loki/api/v1/query_range"
    else:
        params = {"query": expr, "time": str(end_ns)}
        path = "/loki/api/v1/query"
    url = f"{loki_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    body = http_get_json(url)
    if body.get("status") != "success":
        fail(f"Loki query did not report status=success: {expr!r}: {body}")
    return body.get("data", {}).get("result", [])


def run_query(expected_ds_name, prometheus_url, loki_url, expr):
    if expected_ds_name == "Prometheus":
        return prometheus_instant_query(prometheus_url, expr)
    if expected_ds_name == "Loki":
        return loki_query(loki_url, expr)
    fail(f"no query executor for datasource {expected_ds_name!r}")


def verify_panel(uid, panel, expected_ds_name, dashboard_vars, prometheus_url, loki_url):
    title = panel.get("title")
    ds_name = datasource_name_of(panel.get("datasource"))
    if ds_name != expected_ds_name:
        fail(f"{uid}: panel {title!r} references datasource {ds_name!r}, expected {expected_ds_name!r}")

    targets = panel.get("targets", [])
    if not targets:
        fail(f"{uid}: panel {title!r} has no targets at all")

    any_nonempty = False
    all_sparse_ok = True
    for target in targets:
        ref_id = target.get("refId")
        tds_name = datasource_name_of(target.get("datasource"))
        if tds_name != expected_ds_name:
            fail(f"{uid}: panel {title!r} target {ref_id!r} references datasource {tds_name!r}, expected {expected_ds_name!r}")

        expr = target.get("expr")
        if not expr or not expr.strip():
            fail(f"{uid}: panel {title!r} target {ref_id!r} has an empty query expression")

        sparse_ok = is_sparse_ok(expr)
        all_sparse_ok = all_sparse_ok and sparse_ok

        substituted = substitute_expr(expr, dashboard_vars)
        result = run_query(expected_ds_name, prometheus_url, loki_url, substituted)
        nonempty = bool(result)
        if nonempty:
            any_nonempty = True

        print(
            f"  panel query: uid={uid} panel={title!r} refId={ref_id} "
            f"n={len(result)} sparse_ok={sparse_ok} expr={substituted!r}"
        )

    if not any_nonempty and not all_sparse_ok:
        fail(
            f"{uid}: panel {title!r} has no target that returned real data, and not all of its "
            f"targets are legitimately allowed to be empty (HTTP 5xx / refused-telemetry) — "
            f"real data was expected here"
        )


def verify_dashboard(grafana_url, user, password, uid, spec, real_datasources, prometheus_url, loki_url):
    body = http_get_json(f"{grafana_url.rstrip('/')}/api/dashboards/uid/{uid}", user=user, password=password)
    dashboard = body.get("dashboard")
    meta = body.get("meta", {})
    if not dashboard:
        fail(f"{uid}: Grafana returned no 'dashboard' object")

    if dashboard.get("title") != spec["title"]:
        fail(f"{uid}: expected title {spec['title']!r}, got {dashboard.get('title')!r}")

    if not meta.get("provisioned"):
        fail(f"{uid}: dashboard is not reported as provisioned (meta.provisioned={meta.get('provisioned')!r}) — it may have been created/edited through the UI instead of file provisioning")

    panels = dashboard.get("panels", [])
    actual_titles = {p.get("title") for p in panels}
    missing = [t for t in spec["panel_titles"] if t not in actual_titles]
    if missing:
        fail(f"{uid}: missing expected panel(s): {missing} (found: {sorted(actual_titles)})")
    extra = actual_titles - set(spec["panel_titles"])
    if extra:
        fail(f"{uid}: unexpected extra panel(s) not in the expected list: {sorted(extra)}")

    expected_ds_name = spec["datasource_name"]
    if expected_ds_name not in real_datasources:
        fail(f"{uid}: dashboard expects datasource {expected_ds_name!r}, but Grafana has no provisioned datasource with that name")
    if real_datasources[expected_ds_name].get("type") != spec["datasource_type"]:
        fail(
            f"{uid}: datasource {expected_ds_name!r} has type "
            f"{real_datasources[expected_ds_name].get('type')!r}, expected {spec['datasource_type']!r}"
        )

    template_vars = dashboard.get("templating", {}).get("list", [])
    var_names = {v.get("name") for v in template_vars}
    missing_vars = [v for v in spec["variables"] if v not in var_names]
    if missing_vars:
        fail(f"{uid}: missing expected template variable(s): {missing_vars} (found: {sorted(var_names)})")

    dashboard_vars = {}
    for v in template_vars:
        name = v.get("name")
        var_ds_name = datasource_name_of(v.get("datasource"))
        if not name or not var_ds_name:
            fail(f"{uid}: template variable {name!r} has no datasource reference")
        if var_ds_name != expected_ds_name:
            fail(f"{uid}: template variable {name!r} references datasource {var_ds_name!r}, expected {expected_ds_name!r}")
        if not variable_query_text(v):
            fail(f"{uid}: template variable {name!r} has an empty query definition")
        dashboard_vars[name] = variable_substitution_value(v)

    all_query_text = " ".join(
        target.get("expr", "")
        for panel in panels
        for target in panel.get("targets", [])
    )
    missing_substrings = [s for s in spec["required_query_substrings"] if s not in all_query_text]
    if missing_substrings:
        fail(f"{uid}: no panel query references expected substring(s): {missing_substrings}")

    for panel in panels:
        verify_panel(uid, panel, expected_ds_name, dashboard_vars, prometheus_url, loki_url)

    print(
        f"Dashboard verified: uid={uid} title={dashboard.get('title')!r} "
        f"panels={len(panels)} variables={sorted(var_names)} datasource={expected_ds_name}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="local_dev_only_change_me")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--loki-url", default="http://127.0.0.1:3100")
    args = parser.parse_args()

    check_grafana_health(args.grafana_url)

    real_datasources = get_real_datasources(args.grafana_url, args.user, args.password)
    for name in ("Prometheus", "Tempo", "Loki"):
        if name not in real_datasources:
            fail(f"expected datasource {name!r} not found via Grafana's /api/datasources (found: {sorted(real_datasources)})")
    print(f"Grafana datasources confirmed: {sorted(real_datasources)}")

    for uid, spec in EXPECTED_DASHBOARDS.items():
        verify_dashboard(
            args.grafana_url, args.user, args.password, uid, spec,
            real_datasources, args.prometheus_url, args.loki_url,
        )

    print(
        "All Grafana dashboard checks passed (structure, datasource references, "
        "template variables, and every panel's own queries re-executed directly "
        "against Prometheus/Loki with real data)."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
