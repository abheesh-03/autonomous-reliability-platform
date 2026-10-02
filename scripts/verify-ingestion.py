#!/usr/bin/env python3
"""Phase 3C: confirms that a REAL firing alert, delivered by
Alertmanager's own webhook (never a synthetic POST from this script),
was persisted as a genuine reliability.incidents row and is visible
through the existing read-only GET /api/v1/incidents API.

Used only by scripts/verify-alert-lifecycle.sh when
VERIFY_INGESTION=true. This script is READ-ONLY: it never POSTs
anything to Alertmanager or control-plane itself — it only reads
Prometheus's, Alertmanager's, and control-plane's real HTTP APIs and
cross-checks them. stdlib only, matching scripts/verify-alerting.py's
convention (this script does not import from it; each is a
self-contained CLI, by the same convention verify-alerting.py already
follows).

The expected set of active alert instances is derived from TWO
independent sources, not just one:

  1. Prometheus's own GET /api/v1/rules — the real, currently-firing
     label sets for the named rule (its `alerts` list), which is the
     ultimate source of truth for "what is actually firing right now".
  2. Alertmanager's own GET /api/v2/alerts — matched back to (1) by
     exact label-set equality (both sides receive/report the identical
     label set for a given alert instance; Alertmanager was not
     configured with any `global.external_labels` that would add
     extra labels and break this match).

Every Prometheus-reported firing instance MUST have a matching, active
Alertmanager alert — if Prometheus reports two firing instances and
Alertmanager has only delivered/activated one of them, this fails
closed rather than passing on the lesser evidence. This also means the
expected instance count is never hard-coded (works correctly whether a
given alert rule produces one label set or several), and confirms a
single notification group never collapses multiple alert instances
into one incident.

GET /api/v1/incidents is paginated fully (not just its first page) via
the API's own limit/offset contract, so this remains correct
regardless of how many other incidents already exist. Per fingerprint,
only the currently ACTIVE row (status not in resolved/closed) is
considered — a resolved historical row for the same fingerprint (an
expected, legitimate artifact of the dedup design) is never mistaken
for current state.

Usage:
    python3 scripts/verify-ingestion.py incident-from-alert \\
        --alert NAME --since ISO8601 \\
        [--prometheus-url URL] [--alertmanager-url URL] [--control-plane-url URL]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime


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


def get_prometheus_firing_instances(prometheus_url, alert_name):
    """Returns the list of real, currently-firing label-set dicts for
    the named rule, straight from Prometheus's own rule evaluation
    state — not Alertmanager's view of them."""
    body = http_get_json(f"{prometheus_url.rstrip('/')}/api/v1/rules")
    if body.get("status") != "success":
        fail(f"Prometheus /api/v1/rules did not report status=success: {body}")
    for group in body.get("data", {}).get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("type") == "alerting" and rule.get("name") == alert_name:
                if rule.get("state") != "firing":
                    fail(f"{alert_name}: expected Prometheus rule state 'firing', got {rule.get('state')!r}")
                prom_alerts = rule.get("alerts", [])
                if not prom_alerts:
                    fail(f"{alert_name}: Prometheus rule state is 'firing' but its own 'alerts' list is empty")
                return prom_alerts
    fail(f"rule {alert_name!r} not found in Prometheus /api/v1/rules")


def get_alertmanager_active_alerts(alertmanager_url, alert_name):
    alerts = http_get_json(f"{alertmanager_url.rstrip('/')}/api/v2/alerts")
    return [
        a
        for a in alerts
        if a.get("labels", {}).get("alertname") == alert_name and a.get("status", {}).get("state") != "resolved"
    ]


def match_prometheus_instances_to_alertmanager(prom_alerts, am_alerts, alert_name):
    """For every Prometheus-reported firing label set, requires an
    exact-label-set match among Alertmanager's own active alerts for
    this alertname. Fails closed if any Prometheus instance has no
    corresponding active Alertmanager alert — this is what prevents
    the test from passing on partial delivery (e.g. Prometheus firing
    two instances but Alertmanager having only activated one so far).
    Returns the matched Alertmanager alert objects (one per Prometheus
    instance, by construction)."""
    matched = []
    unmatched_prom = []
    for prom_alert in prom_alerts:
        prom_labels = prom_alert.get("labels", {})
        found = next((a for a in am_alerts if a.get("labels", {}) == prom_labels), None)
        if found is None:
            unmatched_prom.append(prom_labels)
        else:
            matched.append(found)
    if unmatched_prom:
        fail(
            f"{alert_name}: Prometheus reports {len(prom_alerts)} firing instance(s), but "
            f"{len(unmatched_prom)} of them have no matching ACTIVE alert in Alertmanager yet "
            f"(unmatched label set(s): {unmatched_prom}) — the real webhook delivery has not "
            "(yet, or ever) covered every firing instance"
        )
    return matched


def fetch_all_incidents(control_plane_url, source, page_size=100):
    """Fully paginates GET /api/v1/incidents?source=<source> via the
    API's own limit/offset contract — correct regardless of how many
    incidents already exist, not just the first page."""
    base = control_plane_url.rstrip("/")
    items = []
    offset = 0
    while True:
        body = http_get_json(f"{base}/api/v1/incidents?source={source}&limit={page_size}&offset={offset}")
        page_items = body.get("items", [])
        items.extend(page_items)
        total = body.get("total", len(items))
        offset += page_size
        if not page_items or offset >= total:
            break
    return items


def active_incidents_by_fingerprint(items):
    """Maps source_fingerprint -> the single ACTIVE (status not in
    resolved/closed) incident for it. A resolved/closed historical row
    for the same fingerprint is deliberately excluded here, never
    allowed to overwrite or be mistaken for the active one — multiple
    historical rows sharing a fingerprint are an expected, legitimate
    artifact of the dedup design (see
    docs/architecture/phase-3c-alert-ingestion.md), not a bug. More
    than one ACTIVE row for the same fingerprint, on the other hand,
    would be a real bug (the partial unique index should make it
    impossible) and fails closed here rather than silently picking
    one."""
    active = {}
    for item in items:
        if item["status"] in ("resolved", "closed"):
            continue
        fp = item["source_fingerprint"]
        if fp in active:
            fail(
                f"multiple ACTIVE incidents found for fingerprint {fp!r}: "
                f"{active[fp]['id']} and {item['id']} — the partial unique index "
                "(incidents_active_fingerprint_uniq) should make this impossible"
            )
        active[fp] = item
    return active


def cmd_incident_from_alert(args):
    prom_alerts = get_prometheus_firing_instances(args.prometheus_url, args.alert)
    print(f"Prometheus reports {len(prom_alerts)} real firing instance(s) for {args.alert}")

    am_active = get_alertmanager_active_alerts(args.alertmanager_url, args.alert)
    matches = match_prometheus_instances_to_alertmanager(prom_alerts, am_active, args.alert)
    print(
        f"Alertmanager has an ACTIVE alert matching every one of those {len(prom_alerts)} "
        f"Prometheus-reported instance(s) (not just some of them)"
    )

    expected_fingerprints = {a["fingerprint"] for a in matches}
    if len(expected_fingerprints) != len(prom_alerts):
        fail(
            f"{args.alert}: {len(prom_alerts)} real firing instances in Prometheus matched to only "
            f"{len(expected_fingerprints)} distinct Alertmanager fingerprint(s) — expected a 1:1 mapping"
        )
    print(f"expected fingerprint(s): {sorted(expected_fingerprints)}")

    all_items = fetch_all_incidents(args.control_plane_url, "alertmanager")
    incidents_by_fp = active_incidents_by_fingerprint(all_items)

    missing = expected_fingerprints - set(incidents_by_fp)
    if missing:
        fail(f"no ACTIVE reliability.incidents row (via GET /api/v1/incidents) yet for fingerprint(s): {sorted(missing)}")

    since = datetime.fromisoformat(args.since)
    for alert in matches:
        fp = alert["fingerprint"]
        incident = incidents_by_fp[fp]
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        expected_severity = labels.get("severity")
        if incident["severity"] != expected_severity:
            fail(
                f"incident for fingerprint {fp}: severity={incident['severity']!r}, "
                f"expected {expected_severity!r} (from Alertmanager's own labels)"
            )

        expected_title = (annotations.get("summary") or "").strip() or labels.get("alertname", "")
        if incident["title"] != expected_title:
            fail(f"incident for fingerprint {fp}: title={incident['title']!r}, expected {expected_title!r}")

        if incident["source"] != "alertmanager":
            fail(f"incident for fingerprint {fp}: source={incident['source']!r}, expected 'alertmanager'")

        if incident["status"] in ("resolved", "closed"):
            fail(
                f"incident for fingerprint {fp}: status={incident['status']!r}, but Alertmanager still "
                "reports this alert active — Phase 3C must never auto-resolve an incident"
            )

        last_seen_at = datetime.fromisoformat(incident["last_seen_at"])
        if last_seen_at < since:
            fail(
                f"incident for fingerprint {fp}: last_seen_at={last_seen_at.isoformat()} predates this "
                f"test run's own outage (since={since.isoformat()}) — not genuinely (re)ingested just now "
                "(this is the one check that would catch a stale pre-existing incident masquerading as proof)"
            )

        print(
            f"  incident OK: fingerprint={fp} id={incident['id']} status={incident['status']} "
            f"severity={incident['severity']} title={incident['title']!r} last_seen_at={incident['last_seen_at']}"
        )

    found_for_alert = {fp for fp in expected_fingerprints if fp in incidents_by_fp}
    if len(found_for_alert) != len(expected_fingerprints):
        fail(
            f"expected {len(expected_fingerprints)} distinct ACTIVE incident(s) (one per firing instance "
            f"confirmed in both Prometheus and Alertmanager), found {len(found_for_alert)} — a single group "
            "must never collapse multiple alert instances into one incident"
        )

    print(
        f"Ingestion verified: {len(expected_fingerprints)} real firing {args.alert} instance(s), confirmed in "
        "BOTH Prometheus and Alertmanager, each have a correctly-mapped, currently-active reliability.incidents "
        "row, visible via GET /api/v1/incidents."
    )
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("incident-from-alert")
    p.add_argument("--alert", required=True)
    p.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    p.add_argument("--alertmanager-url", default="http://127.0.0.1:9093")
    p.add_argument("--control-plane-url", default="http://127.0.0.1:8000")
    p.add_argument(
        "--since",
        required=True,
        help="ISO 8601 timestamp; an incident's last_seen_at must be >= this to count as genuinely "
        "(re)ingested by this run, tolerating a pre-existing incident from an earlier genuine outage",
    )

    args = parser.parse_args()
    {"incident-from-alert": cmd_incident_from_alert}[args.mode](args)


if __name__ == "__main__":
    main()
