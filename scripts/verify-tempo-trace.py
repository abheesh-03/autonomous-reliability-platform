#!/usr/bin/env python3
"""Fetches one trace from Tempo's HTTP query API
(GET /api/v2/traces/{traceID}) and independently re-verifies it against
the seven-span checkout trace already established by
scripts/parse-checkout-trace.py — not just that the same IDs exist, but
that Tempo's own stored data has the correct Trace ID, span Kind,
resource service.name, and parent/child relationship on every branch.

Usage:
    python3 scripts/verify-tempo-trace.py [--tempo-url URL] "<match line>"

<match line> is exactly the success line scripts/parse-checkout-trace.py
prints on stdout, e.g.:
    trace_id=... checkout_server_span_id=... payment_client_span_id=...
    payment_server_span_id=... inventory_client_span_id=...
    inventory_server_span_id=... notification_client_span_id=...
    notification_server_span_id=...

Extra spans in the Tempo trace (e.g. internal Fastify/ASGI child spans)
are ignored. Exits 0 and prints a concise success line only if all
seven spans and all six parent/child relationships are confirmed;
fails closed (exits 1) on any missing or malformed data.
"""

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request

EXPECTED_KEYS = [
    "trace_id",
    "checkout_server_span_id",
    "payment_client_span_id",
    "payment_server_span_id",
    "inventory_client_span_id",
    "inventory_server_span_id",
    "notification_client_span_id",
    "notification_server_span_id",
]

TRACE_ID_RE = re.compile(r'^[0-9a-f]{32}$')
SPAN_ID_RE = re.compile(r'^[0-9a-f]{16}$')

# (client key, server key, expected CLIENT service.name, expected SERVER service.name)
BRANCHES = [
    ("payment_client_span_id", "payment_server_span_id", "checkout-service", "payment-service"),
    ("inventory_client_span_id", "inventory_server_span_id", "checkout-service", "inventory-service"),
    ("notification_client_span_id", "notification_server_span_id", "checkout-service", "notification-service"),
]


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def parse_match_line(line):
    found = dict(re.findall(r'(\w+)=([0-9a-f]+)', line))
    result = {}
    for key in EXPECTED_KEYS:
        value = found.get(key)
        pattern = TRACE_ID_RE if key == "trace_id" else SPAN_ID_RE
        if not value or not pattern.match(value):
            fail(f"missing or invalid '{key}' in input line")
        result[key] = value
    return result


def b64_to_hex(value, expected_length):
    """Strictly decodes a base64-encoded OTLP-JSON ID field to hex.
    Requires `value` to be a string, decodes with validate=True (rejects
    non-alphabet characters and malformed padding rather than silently
    ignoring them), and requires the decoded byte length to match
    `expected_length` exactly (16 for a Trace ID, 8 for a Span ID).
    Returns None on any failure, so malformed input can never satisfy a
    required span match."""
    if not isinstance(value, str):
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    if len(decoded) != expected_length:
        return None
    return decoded.hex()


def fetch_trace(tempo_url, trace_id):
    url = f"{tempo_url.rstrip('/')}/api/v2/traces/{trace_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                fail(f"Tempo returned HTTP {resp.status} for {url}")
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        fail(f"Tempo returned HTTP {e.code} for {url}")
    except urllib.error.URLError as e:
        fail(f"could not reach Tempo at {url}: {e}")
    except json.JSONDecodeError as e:
        fail(f"Tempo response for {url} was not valid JSON: {e}")


def extract_spans(trace_doc):
    """Flattens Tempo's nested resourceSpans/scopeSpans/spans structure
    (protobuf-JSON: trace/span IDs are base64, decoded here to hex) into
    a flat list, tagging each span with its resource's service.name.
    Spans with undecodable IDs are silently skipped (fail-closed: they
    simply won't match anything expected)."""
    spans = []
    trace = trace_doc.get('trace', {})
    for rs in trace.get('resourceSpans', []):
        service_name = None
        for attr in rs.get('resource', {}).get('attributes', []):
            if attr.get('key') == 'service.name':
                service_name = attr.get('value', {}).get('stringValue')
        for ss in rs.get('scopeSpans', []):
            for s in ss.get('spans', []):
                trace_id_hex = b64_to_hex(s.get('traceId', ''), 16)
                span_id_hex = b64_to_hex(s.get('spanId', ''), 8)
                parent_id_hex = b64_to_hex(s['parentSpanId'], 8) if s.get('parentSpanId') else None
                if not trace_id_hex or not span_id_hex:
                    continue
                spans.append({
                    'service_name': service_name,
                    'kind': s.get('kind'),
                    'trace_id': trace_id_hex,
                    'span_id': span_id_hex,
                    'parent_id': parent_id_hex,
                })
    return spans


def find_span(spans, span_id):
    for s in spans:
        if s['span_id'] == span_id:
            return s
    return None


def require_span(spans, span_id, trace_id, expected_kind, expected_service, label):
    span = find_span(spans, span_id)
    if span is None:
        fail(f"{label} span {span_id} not found in the Tempo trace")
    if span['trace_id'] != trace_id:
        fail(f"{label} span {span_id} has Trace ID {span['trace_id']}, expected {trace_id}")
    if span['kind'] != expected_kind:
        fail(f"{label} span {span_id} has Kind {span['kind']}, expected {expected_kind}")
    if span['service_name'] != expected_service:
        fail(f"{label} span {span_id} has service.name {span['service_name']!r}, expected {expected_service!r}")
    return span


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('match_line', help="parse-checkout-trace.py's success output line")
    parser.add_argument('--tempo-url', default='http://127.0.0.1:3200')
    args = parser.parse_args()

    expected = parse_match_line(args.match_line)
    trace_id = expected['trace_id']

    trace_doc = fetch_trace(args.tempo_url, trace_id)
    spans = extract_spans(trace_doc)
    if not spans:
        fail(f"Tempo trace {trace_id} contained no parseable spans")

    checkout_server = require_span(
        spans, expected['checkout_server_span_id'], trace_id,
        'SPAN_KIND_SERVER', 'checkout-service', 'checkout SERVER',
    )

    for client_key, server_key, client_service, server_service in BRANCHES:
        client = require_span(
            spans, expected[client_key], trace_id,
            'SPAN_KIND_CLIENT', client_service, client_key,
        )
        server = require_span(
            spans, expected[server_key], trace_id,
            'SPAN_KIND_SERVER', server_service, server_key,
        )
        if client['parent_id'] != checkout_server['span_id']:
            fail(
                f"{client_key}'s Parent ID ({client['parent_id']}) does not equal "
                f"checkout SERVER's Span ID ({checkout_server['span_id']})"
            )
        if server['parent_id'] != client['span_id']:
            fail(
                f"{server_key}'s Parent ID ({server['parent_id']}) does not equal "
                f"{client_key}'s Span ID ({client['span_id']})"
            )

    print(
        f"Tempo trace verified: trace_id={trace_id} "
        f"checkout_server_span_id={checkout_server['span_id']} "
        f"payment_client_span_id={expected['payment_client_span_id']} "
        f"payment_server_span_id={expected['payment_server_span_id']} "
        f"inventory_client_span_id={expected['inventory_client_span_id']} "
        f"inventory_server_span_id={expected['inventory_server_span_id']} "
        f"notification_client_span_id={expected['notification_client_span_id']} "
        f"notification_server_span_id={expected['notification_server_span_id']} "
        f"(total spans in Tempo trace: {len(spans)}, extra/internal spans ignored)"
    )
    sys.exit(0)


if __name__ == '__main__':
    main()
