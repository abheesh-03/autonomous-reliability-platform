#!/usr/bin/env python3
# Parses `docker compose logs --no-log-prefix otel-collector` from
# stdin into individual spans (grouping each Span block with the
# service.name of its enclosing ResourceSpans block), then proves real
# distributed trace continuation for one checkout trace:
#
#                     +-> checkout payment CLIENT -> payment SERVER
#   checkout SERVER --|
#                     +-> checkout inventory CLIENT -> inventory SERVER
#                     +-> checkout notification CLIENT  (no SERVER yet —
#                                                          notification-
#                                                          service is not
#                                                          instrumented)
#
# All spans above must share one Trace ID; each downstream SERVER
# span's Parent ID must equal its own checkout CLIENT span's Span ID
# (payment and inventory are sibling branches, not parent/child of each
# other). Exits 0 and prints the matched IDs if a complete, valid match
# is found, else exits 1.

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

def spans_matching(service_name, kind, attr_key, attr_value):
    return [
        s for s in spans
        if s['service_name'] == service_name
        and s['kind'] == kind
        and s['attrs'].get(attr_key) == attr_value
    ]


checkout_server = spans_matching('checkout-service', 'Server', 'http.route', '/checkouts')
checkout_payment_client = spans_matching('checkout-service', 'Client', 'url.full', 'http://payment-service:8081/payments/authorize')
payment_server = spans_matching('payment-service', 'Server', 'http.route', '/payments/authorize')
checkout_inventory_client = spans_matching('checkout-service', 'Client', 'url.full', 'http://inventory-service:8082/inventory/reservations')
# The Go otelhttp SERVER span (unlike the Java/Python ones) does not
# carry a separate http.route attribute — only url.path — observed
# empirically, not assumed.
inventory_server = spans_matching('inventory-service', 'Server', 'url.path', '/inventory/reservations')
checkout_notification_client = spans_matching('checkout-service', 'Client', 'url.full', 'http://notification-service:8083/notifications')

trace_id_re = re.compile(r'^[0-9a-f]{32}$')
span_id_re = re.compile(r'^[0-9a-f]{16}$')


def is_valid_hex_id(value, pattern):
    return isinstance(value, str) and pattern.match(value) is not None


def valid_span(s):
    return (is_valid_hex_id(s['trace_id'], trace_id_re)
            and is_valid_hex_id(s['parent_id'], span_id_re)
            and is_valid_hex_id(s['span_id'], span_id_re))


def find_client_then_server(clients, servers, trace_id, parent_span_id):
    """Find a (CLIENT, SERVER) pair where the CLIENT is a child of
    parent_span_id in trace_id, and the SERVER is a child of that
    CLIENT span — fails closed (returns None) unless every ID involved
    is present and syntactically valid."""
    for c in clients:
        if not valid_span(c):
            continue
        if c['trace_id'] != trace_id or c['parent_id'] != parent_span_id:
            continue
        for s in servers:
            if not valid_span(s):
                continue
            if s['trace_id'] == trace_id and s['parent_id'] == c['span_id']:
                return c, s
    return None


def find_client(clients, trace_id, parent_span_id):
    for c in clients:
        if (is_valid_hex_id(c['trace_id'], trace_id_re)
                and is_valid_hex_id(c['span_id'], span_id_re)
                and c['trace_id'] == trace_id
                and c['parent_id'] == parent_span_id):
            return c
    return None


for cs in checkout_server:
    if not (is_valid_hex_id(cs['trace_id'], trace_id_re) and is_valid_hex_id(cs['span_id'], span_id_re)):
        continue
    trace_id, checkout_span_id = cs['trace_id'], cs['span_id']

    payment_match = find_client_then_server(checkout_payment_client, payment_server, trace_id, checkout_span_id)
    if not payment_match:
        continue

    inventory_match = find_client_then_server(checkout_inventory_client, inventory_server, trace_id, checkout_span_id)
    if not inventory_match:
        continue

    notification_client = find_client(checkout_notification_client, trace_id, checkout_span_id)
    if not notification_client:
        continue

    payment_client, payment_srv = payment_match
    inventory_client, inventory_srv = inventory_match

    print(
        f"trace_id={trace_id} "
        f"checkout_server_span_id={checkout_span_id} "
        f"payment_client_span_id={payment_client['span_id']} "
        f"payment_server_span_id={payment_srv['span_id']} "
        f"inventory_client_span_id={inventory_client['span_id']} "
        f"inventory_server_span_id={inventory_srv['span_id']} "
        f"notification_client_span_id={notification_client['span_id']}"
    )
    sys.exit(0)

sys.exit(1)
