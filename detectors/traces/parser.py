"""Gate C: parses Tempo's real `GET /api/v2/traces/{traceID}` response
body into flat `SpanRecord`s.

The base64-decode-to-hex / resourceSpans-scopeSpans-spans flattening
logic here is adapted directly from `scripts/verify-tempo-trace.py`'s
own `extract_spans`/`b64_to_hex` -- the exact parsing already
independently proven against this repository's real Tempo instance
(see that script's own docstring) -- extended, additively, to also
read `startTimeUnixNano`/`endTimeUnixNano` (OTLP-required fields,
always present per the OTLP spec) and an optional `status.code` (OTLP-
optional; genuinely absent is reported as `error=None`, never coerced
to `False`). This extension was NOT independently re-verified against
a live Tempo in this round -- see
`docs/architecture/phase-11b-autonomous-failure-discovery.md` section
7 for the honest limitation.

Correction-round Issue 4: every nested field read from the response
body is now explicitly type-checked before use (a non-dict `resource`,
`value`, or any other nested object is treated as malformed and
skipped, never dereferenced blindly), and the per-span construction is
wrapped in a final defensive `try/except` so no conceivable malformed
shape can propagate an exception out of this module -- a crash here
must never be allowed to crash the whole unified pipeline. Every span
is also validated against the REQUESTED trace id: a span whose own
`traceId` decodes to something other than the trace id this module was
actually asked for is rejected as a cross-trace identity mismatch,
never trusted as evidence for the requested trace (and never used to
build a dependency edge).

This module never touches `services/investigator-service` -- it is a
bounded, detector-specific adapter, per Phase 11B's own explicit
"create a bounded detector-specific adapter" option.
"""

import base64

from detectors.schemas.dependency import SpanRecord, TraceParseResult

_STATUS_CODE_ERROR = "STATUS_CODE_ERROR"


def _b64_to_hex(value: object, expected_length: int) -> str | None:
    """Strictly decodes a base64-encoded OTLP-JSON id field to hex.
    Returns None on ANY failure (wrong type, invalid base64, wrong
    decoded length) -- malformed input can never produce a span this
    module treats as real."""
    if not isinstance(value, str):
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    if len(decoded) != expected_length:
        return None
    return decoded.hex()


def _extract_service_name(resource: object) -> str | None:
    """Defensive: a malformed `resource` (not an object), a malformed
    `attributes` list, a malformed individual attribute, or a
    malformed `value` object are all treated as "no service name
    found here", never dereferenced blindly (the exact Issue 4A
    reproduction: a bare string `resource` must never raise
    AttributeError)."""
    if not isinstance(resource, dict):
        return None
    attributes = resource.get("attributes")
    if not isinstance(attributes, list):
        return None
    for attr in attributes:
        if not isinstance(attr, dict) or attr.get("key") != "service.name":
            continue
        value = attr.get("value")
        if isinstance(value, dict):
            string_value = value.get("stringValue")
            if isinstance(string_value, str):
                return string_value
    return None


def _parse_timing(raw_start: object, raw_end: object) -> tuple[int | None, int | None]:
    try:
        start_ns = int(raw_start) if raw_start is not None else None
        end_ns = int(raw_end) if raw_end is not None else None
    except (TypeError, ValueError):
        return None, None
    return start_ns, end_ns


def _parse_error_status(status: object) -> bool | None:
    if isinstance(status, dict) and "code" in status:
        return status.get("code") == _STATUS_CODE_ERROR
    return None  # genuinely absent/malformed status is unknown, never coerced to False


def _extract_raw_spans(trace_doc: dict, requested_trace_id: str) -> tuple[list[SpanRecord], int, int]:
    """Returns (spans, malformed_count, trace_id_mismatch_count).
    Every span is validated against `requested_trace_id` -- a span
    whose own decoded traceId differs is REJECTED (counted separately,
    never silently included as if it belonged to the requested trace)."""
    spans: list[SpanRecord] = []
    malformed = 0
    mismatched = 0
    trace = trace_doc.get("trace", {})
    if not isinstance(trace, dict):
        return spans, malformed, mismatched

    resource_spans = trace.get("resourceSpans")
    if not isinstance(resource_spans, list):
        return spans, malformed, mismatched

    for rs in resource_spans:
        if not isinstance(rs, dict):
            malformed += 1
            continue
        service_name = _extract_service_name(rs.get("resource"))

        scope_spans = rs.get("scopeSpans")
        if not isinstance(scope_spans, list):
            malformed += 1
            continue

        for ss in scope_spans:
            if not isinstance(ss, dict):
                malformed += 1
                continue
            raw_spans = ss.get("spans")
            if not isinstance(raw_spans, list):
                malformed += 1
                continue

            for s in raw_spans:
                if not isinstance(s, dict):
                    malformed += 1
                    continue
                try:
                    trace_id_hex = _b64_to_hex(s.get("traceId", ""), 16)
                    span_id_hex = _b64_to_hex(s.get("spanId", ""), 8)
                    if not trace_id_hex or not span_id_hex:
                        malformed += 1
                        continue
                    if trace_id_hex != requested_trace_id:
                        mismatched += 1
                        continue

                    parent_id_hex = _b64_to_hex(s["parentSpanId"], 8) if s.get("parentSpanId") else None
                    start_ns, end_ns = _parse_timing(s.get("startTimeUnixNano"), s.get("endTimeUnixNano"))
                    error = _parse_error_status(s.get("status"))
                    raw_kind = s.get("kind")
                    kind = raw_kind if isinstance(raw_kind, str) else None

                    spans.append(
                        SpanRecord(
                            trace_id=trace_id_hex,
                            span_id=span_id_hex,
                            parent_span_id=parent_id_hex,
                            service_name=service_name,
                            kind=kind,
                            start_time_unix_nano=start_ns,
                            end_time_unix_nano=end_ns,
                            error=error,
                        )
                    )
                except Exception:
                    # Final defensive net: no conceivable malformed
                    # shape inside one span's fields may ever raise out
                    # of this function -- count it and move on.
                    malformed += 1
                    continue
    return spans, malformed, mismatched


def _detect_cycle(spans: list[SpanRecord]) -> bool:
    """Walks every span's ancestor chain; a cycle exists if that walk
    ever revisits a span already in the current chain. Bounded by
    `len(spans)` steps per span, so a corrupted/cyclic structure can
    never cause an infinite loop."""
    by_id = {s.span_id: s for s in spans}
    for start in spans:
        seen: set[str] = set()
        current: SpanRecord | None = start
        steps = 0
        while current is not None and current.parent_span_id is not None:
            if current.span_id in seen:
                return True
            seen.add(current.span_id)
            steps += 1
            if steps > len(spans) + 1:
                return True  # defensive: should be unreachable given the `seen` check above
            current = by_id.get(current.parent_span_id)
    return False


def parse_trace_detail(trace_id: str, body: dict) -> TraceParseResult:
    """Never raises on malformed input -- an unexpected shape anywhere
    inside `body` is counted in `malformed_span_count`, never a crash
    and never a silently-fabricated span. Every span is also validated
    against `trace_id` -- any span belonging to a DIFFERENT trace
    (cross-trace identity mismatch) is rejected, counted in
    `trace_id_mismatch_count`, and never used as evidence for this
    trace."""
    if not isinstance(body, dict):
        return TraceParseResult(
            trace_id=trace_id, spans=[], malformed_span_count=1, trace_id_mismatch_count=0, has_cycle=False,
            root_span_ids=[], spans_with_missing_parent=[],
        )

    try:
        spans, malformed, mismatched = _extract_raw_spans(body, trace_id)
    except Exception:
        # Unreachable in practice (the inner loop already has its own
        # defensive try/except), but kept as an absolute final
        # guarantee that this function itself never raises.
        return TraceParseResult(
            trace_id=trace_id, spans=[], malformed_span_count=1, trace_id_mismatch_count=0, has_cycle=False,
            root_span_ids=[], spans_with_missing_parent=[],
        )

    has_cycle = _detect_cycle(spans)

    by_id = {s.span_id: s for s in spans}
    root_span_ids = [s.span_id for s in spans if s.parent_span_id is None]
    missing_parent = [s.span_id for s in spans if s.parent_span_id is not None and s.parent_span_id not in by_id]

    return TraceParseResult(
        trace_id=trace_id,
        spans=spans,
        malformed_span_count=malformed,
        trace_id_mismatch_count=mismatched,
        has_cycle=has_cycle,
        root_span_ids=root_span_ids,
        spans_with_missing_parent=missing_parent,
    )
