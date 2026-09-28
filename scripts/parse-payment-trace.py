#!/usr/bin/env python3
# Phase 2A.3: parses `docker compose logs --no-log-prefix otel-collector`
# from stdin into individual spans (grouping each Span block with the
# service.name of its enclosing ResourceSpans block), then proves real
# distributed trace continuation from checkout-service to payment-service:
# a checkout-service CLIENT span to /payments/authorize and a
# payment-service SERVER span for /payments/authorize that share a Trace
# ID, where the payment span's Parent ID equals the checkout span's own
# Span ID. Exits 0 and prints the matched IDs if found, else exits 1.

import re
import sys

lines = sys.stdin.read().splitlines()

spans = []
resource_attrs = {}
span = None
in_resource_attrs = False
in_span_attrs = False

attr_re = re.compile(r'^\s{5}-> ([^:]+): \w+\((.*)\)$')
field_re = re.compile(r'^\s{4}(Trace ID|Parent ID|ID|Name|Kind)\s*:\s*(.*?)\s*$')
rspans_re = re.compile(r'ResourceSpans #\d+$')


def finalize():
    global span
    if span is not None:
        spans.append(span)
        span = None


for line in lines:
    # "ResourceSpans #N" lines carry a timestamp+level prefix from the
    # Collector's own logger; every other line below is a bare
    # continuation line of that same multi-line log entry.
    if rspans_re.search(line):
        finalize()
        resource_attrs = {}
        in_resource_attrs = False
        in_span_attrs = False
    elif line == 'Resource attributes:':
        in_resource_attrs = True
    elif line.startswith('ScopeSpans #'):
        in_resource_attrs = False
    elif re.match(r'^Span #\d+$', line):
        finalize()
        span = {'service_name': resource_attrs.get('service.name'),
                'trace_id': None, 'parent_id': None, 'span_id': None,
                'name': None, 'kind': None, 'attrs': {}}
        in_span_attrs = False
    elif line == 'Attributes:':
        in_span_attrs = True
    elif in_span_attrs:
        m = attr_re.match(line)
        if m and span is not None:
            span['attrs'][m.group(1)] = m.group(2)
    elif span is not None:
        m = field_re.match(line)
        if m:
            field, value = m.group(1), m.group(2)
            if field == 'Trace ID':
                span['trace_id'] = value
            elif field == 'Parent ID':
                span['parent_id'] = value
            elif field == 'ID':
                span['span_id'] = value
            elif field == 'Name':
                span['name'] = value
            elif field == 'Kind':
                span['kind'] = value
    elif in_resource_attrs:
        m = attr_re.match(line)
        if m:
            resource_attrs[m.group(1)] = m.group(2)

finalize()

checkout_client = [
    s for s in spans
    if s['service_name'] == 'checkout-service'
    and s['kind'] == 'Client'
    and s['attrs'].get('url.full') == 'http://payment-service:8081/payments/authorize'
]
payment_server = [
    s for s in spans
    if s['service_name'] == 'payment-service'
    and s['kind'] == 'Server'
    and s['attrs'].get('http.route') == '/payments/authorize'
]

trace_id_re = re.compile(r'^[0-9a-f]{32}$')
span_id_re = re.compile(r'^[0-9a-f]{16}$')


def is_valid_hex_id(value, pattern):
    return isinstance(value, str) and pattern.match(value) is not None


for c in checkout_client:
    for p in payment_server:
        # Require every correlation ID to be present and syntactically
        # valid before comparing them — otherwise e.g. two missing
        # fields (None == None) could falsely satisfy the relationship.
        if not (is_valid_hex_id(c['trace_id'], trace_id_re)
                and is_valid_hex_id(c['span_id'], span_id_re)
                and is_valid_hex_id(p['trace_id'], trace_id_re)
                and is_valid_hex_id(p['parent_id'], span_id_re)
                and is_valid_hex_id(p['span_id'], span_id_re)):
            continue
        if p['trace_id'] == c['trace_id'] and p['parent_id'] == c['span_id']:
            print(f"trace_id={c['trace_id']} checkout_client_span_id={c['span_id']} "
                  f"payment_server_parent_id={p['parent_id']} payment_server_span_id={p['span_id']}")
            sys.exit(0)

sys.exit(1)
