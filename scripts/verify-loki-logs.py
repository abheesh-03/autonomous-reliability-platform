#!/usr/bin/env python3
"""Queries Loki's real HTTP API (GET /loki/api/v1/query_range) to prove
each application service has genuine, nonempty log output actually
ingested through the Alloy -> Loki pipeline — not a synthetic line
injected directly into Loki to satisfy this check.

Default mode verifies all four application services:
    python3 scripts/verify-loki-logs.py [--loki-url URL] [--since-seconds N] [--after-ns NS]

For each service, requires: a successful Loki query response, at least
one returned stream whose "service" label matches the queried service,
at least one nonempty log entry in that stream, and a timestamp inside
the given lookback window. If --after-ns is given, additionally
requires at least one entry strictly newer than that nanosecond
timestamp (used to prove genuinely fresh ingestion during this run,
rather than being satisfied by stale entries already sitting in a
persistent loki_data volume from an earlier run). Fails closed
(nonzero exit, clear message) on an unreachable Loki, a malformed
response, an empty result, a wrong service label, an out-of-window
timestamp, or (with --after-ns) no entry newer than that timestamp.

Substring persistence-check mode (legacy; prefer --capture-exact /
--verify-exact below for a real restart-persistence test, since a log
message can recur) looks for one specific substring for one service:
    python3 scripts/verify-loki-logs.py --service SVC --expect-line TEXT [--since-seconds N]

Exact-entry capture/verify mode: captures one single, unambiguous log
entry (service + the FULL message + its original nanosecond timestamp)
as a JSON blob on stdout, then later verifies that exact triple is
still present — not just that a matching substring appears somewhere,
which could be satisfied by a different occurrence of a recurring
message:
    python3 scripts/verify-loki-logs.py --capture-exact --service SVC [--line-contains TEXT] [--since-seconds N]
    python3 scripts/verify-loki-logs.py --verify-exact 'CAPTURED_JSON' [--since-seconds N]
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVICES = [
    "checkout-service",
    "payment-service",
    "inventory-service",
    "notification-service",
]


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def query_range(loki_url, query, start_ns, end_ns, limit=200):
    params = {
        "query": query,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(limit),
        "direction": "backward",
    }
    url = f"{loki_url.rstrip('/')}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                fail(f"Loki returned HTTP {resp.status} for {url}")
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        fail(f"Loki returned HTTP {e.code} for {url}")
    except urllib.error.URLError as e:
        fail(f"could not reach Loki at {url}: {e}")
    except json.JSONDecodeError as e:
        fail(f"Loki response for {url} was not valid JSON: {e}")

    if body.get("status") != "success":
        fail(f"Loki query did not report status=success: {body}")
    data = body.get("data", {})
    if data.get("resultType") != "streams":
        fail(f"unexpected Loki resultType {data.get('resultType')!r} for query {query!r}")
    return data.get("result", [])


def verify_service_has_logs(loki_url, service, start_ns, end_ns, after_ns=None):
    streams = query_range(loki_url, f'{{service="{service}"}}', start_ns, end_ns)
    if not streams:
        fail(f"{service}: no log streams returned by Loki")

    total_entries = 0
    fresh_entries = 0
    newest = None  # (ts_ns, line) among all in-window entries
    newest_fresh = None  # (ts_ns, line) among entries newer than after_ns
    for stream in streams:
        labels = stream.get("stream", {})
        if labels.get("service") != service:
            fail(f"{service}: a returned stream had service label {labels.get('service')!r}, expected {service!r}")
        for ts_str, line in stream.get("values", []):
            if not line or not line.strip():
                continue
            try:
                ts_ns = int(ts_str)
            except (TypeError, ValueError):
                fail(f"{service}: malformed timestamp {ts_str!r} in Loki response")
            if not (start_ns <= ts_ns <= end_ns):
                fail(
                    f"{service}: log entry timestamp {ts_ns} is outside the "
                    f"expected verification window [{start_ns}, {end_ns}]"
                )
            total_entries += 1
            if newest is None:
                newest = (ts_ns, line)
            if after_ns is not None and ts_ns > after_ns:
                fresh_entries += 1
                if newest_fresh is None:
                    newest_fresh = (ts_ns, line)

    if total_entries == 0:
        fail(f"{service}: Loki returned stream(s) but no nonempty log entries")

    if after_ns is not None:
        if fresh_entries == 0:
            fail(
                f"{service}: found {total_entries} log entr{'y' if total_entries == 1 else 'ies'} "
                f"in the window, but none newer than the required starting timestamp "
                f"{after_ns} (ns) — log collection may not have (re)started, or these are "
                f"stale entries from an earlier run"
            )
        return fresh_entries, newest_fresh

    return total_entries, newest


def run_all_services(loki_url, services, start_ns, end_ns, after_ns=None):
    results = {}
    for service in services:
        results[service] = verify_service_has_logs(loki_url, service, start_ns, end_ns, after_ns)

    for service in services:
        count, (ts_ns, line) = results[service]
        preview = line if len(line) <= 160 else line[:157] + "..."
        freshness = " (fresh, i.e. newer than --after-ns)" if after_ns is not None else ""
        print(f"Loki logs verified: service={service} entries={count}{freshness} latest_ts={ts_ns} sample={preview!r}")
    sys.exit(0)


def run_expect_line(loki_url, service, expect_line, start_ns, end_ns):
    streams = query_range(loki_url, f'{{service="{service}"}}', start_ns, end_ns, limit=1000)
    for stream in streams:
        labels = stream.get("stream", {})
        if labels.get("service") != service:
            continue
        for ts_str, line in stream.get("values", []):
            if expect_line in line:
                print(f"Loki log persistence confirmed: service={service} timestamp={ts_str} line={line!r}")
                sys.exit(0)
    fail(f"expected log line not found for service={service} within the lookback window: {expect_line!r}")


def run_capture_exact(loki_url, service, contains, start_ns, end_ns):
    streams = query_range(loki_url, f'{{service="{service}"}}', start_ns, end_ns, limit=1000)
    if not streams:
        fail(f"{service}: no log streams returned by Loki (nothing to capture)")

    newest = None  # (ts_ns, line) — the single most recent qualifying entry
    for stream in streams:
        labels = stream.get("stream", {})
        if labels.get("service") != service:
            fail(f"{service}: a returned stream had service label {labels.get('service')!r}, expected {service!r}")
        for ts_str, line in stream.get("values", []):
            if not line or not line.strip():
                continue
            if contains and contains not in line:
                continue
            try:
                ts_ns = int(ts_str)
            except (TypeError, ValueError):
                fail(f"{service}: malformed timestamp {ts_str!r} in Loki response")
            if newest is None or ts_ns > newest[0]:
                newest = (ts_ns, line)

    if newest is None:
        filt = f" containing {contains!r}" if contains else ""
        fail(f"{service}: no log entry{filt} found to capture within the lookback window")

    ts_ns, line = newest
    # A single-line JSON blob: unambiguous (service, exact full message,
    # exact nanosecond timestamp) evidence, safe to hand back on the
    # command line to a later --verify-exact call even if the log line
    # itself contains quotes, spaces, or escaped newlines.
    print(json.dumps({"service": service, "timestamp_ns": ts_ns, "line": line}))
    sys.exit(0)


def run_verify_exact(loki_url, captured_json, start_ns, end_ns):
    try:
        captured = json.loads(captured_json)
    except json.JSONDecodeError as e:
        fail(f"--verify-exact value is not valid JSON produced by --capture-exact: {e}")

    service = captured.get("service")
    expected_ts_ns = captured.get("timestamp_ns")
    expected_line = captured.get("line")
    if not service or not isinstance(expected_ts_ns, int) or expected_line is None:
        fail(f"--verify-exact value is missing required fields (service/timestamp_ns/line): {captured}")

    streams = query_range(loki_url, f'{{service="{service}"}}', start_ns, end_ns, limit=1000)
    for stream in streams:
        labels = stream.get("stream", {})
        if labels.get("service") != service:
            continue
        for ts_str, line in stream.get("values", []):
            try:
                ts_ns = int(ts_str)
            except (TypeError, ValueError):
                continue
            if ts_ns == expected_ts_ns and line == expected_line:
                print(
                    f"Loki log persistence confirmed (exact entry): service={service} "
                    f"timestamp_ns={ts_ns} line={line!r}"
                )
                sys.exit(0)

    fail(
        f"exact log entry not found for service={service} timestamp_ns={expected_ts_ns} "
        f"line={expected_line!r} within the lookback window — it did not survive, or the "
        f"window/--since-seconds is too narrow"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loki-url", default="http://127.0.0.1:3100")
    parser.add_argument("--services", default=",".join(DEFAULT_SERVICES),
                         help="Comma-separated service labels to verify (default mode only).")
    parser.add_argument("--since-seconds", type=int, default=600,
                         help="Lookback window in seconds from now (default: 600).")
    parser.add_argument("--after-ns", type=int, default=None,
                         help="Default mode only: additionally require at least one log entry "
                              "per service strictly newer than this nanosecond epoch timestamp "
                              "(e.g. from `python3 -c 'import time; print(time.time_ns())'`), to "
                              "prove fresh ingestion rather than being satisfied by stale entries "
                              "already present from an earlier run.")
    parser.add_argument("--service", default=None,
                         help="Single service to check; required with --expect-line or --capture-exact.")
    parser.add_argument("--expect-line", default=None,
                         help="Legacy substring persistence check: verify this substring still "
                              "appears somewhere in --service's logs. Prefer --capture-exact / "
                              "--verify-exact for restart-persistence tests, since a substring can "
                              "match more than one real occurrence of a recurring message.")
    parser.add_argument("--capture-exact", action="store_true",
                         help="Capture one exact, unambiguous log entry (service, full message, "
                              "original nanosecond timestamp) for --service as a JSON blob on "
                              "stdout, for a later --verify-exact call. Optionally narrow which "
                              "entry with --line-contains; without it, the single most recent "
                              "entry for --service is captured.")
    parser.add_argument("--line-contains", default=None,
                         help="With --capture-exact, only consider entries containing this "
                              "substring (e.g. to select a known startup line rather than "
                              "whatever happens to be newest).")
    parser.add_argument("--verify-exact", default=None, metavar="CAPTURED_JSON",
                         help="Verify the exact entry captured by a prior --capture-exact call "
                              "(same service, exact full message, exact original timestamp) is "
                              "still present.")
    args = parser.parse_args()

    end_ns = time.time_ns()
    start_ns = end_ns - args.since_seconds * 1_000_000_000

    if args.verify_exact is not None:
        run_verify_exact(args.loki_url, args.verify_exact, start_ns, end_ns)
        return

    if args.capture_exact:
        if not args.service:
            fail("--capture-exact requires --service")
        run_capture_exact(args.loki_url, args.service, args.line_contains, start_ns, end_ns)
        return

    if args.expect_line is not None:
        if not args.service:
            fail("--expect-line requires --service")
        run_expect_line(args.loki_url, args.service, args.expect_line, start_ns, end_ns)
        return

    if args.after_ns is not None and args.after_ns >= end_ns:
        fail(f"--after-ns ({args.after_ns}) is not before the current time ({end_ns}); nothing could ever be newer")

    services = [s.strip() for s in args.services.split(",") if s.strip()]
    if not services:
        fail("no services specified")
    run_all_services(args.loki_url, services, start_ns, end_ns, args.after_ns)


if __name__ == "__main__":
    main()
