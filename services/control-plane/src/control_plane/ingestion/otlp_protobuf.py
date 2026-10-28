"""Phase 16 correction round (item 3): decodes a REAL OTLP/HTTP
protobuf body (`Content-Type: application/x-protobuf`) into the exact
same `OtlpExportMetricsRequest` shape `domain/telemetry.py` already
validates for the JSON path -- every downstream rule (temporality,
unit, bounds, time window, dedup) therefore applies identically to
both wire formats; there is no separate, parallel protobuf-specific
validation path to drift out of sync.

WHY THIS EXISTS: independent verification (see this module's own test
coverage and docs/architecture/phase-16-secure-telemetry-onboarding.md
Gate 3 section) found the official OpenTelemetry Python SDK's HTTP
metrics exporter (`opentelemetry-exporter-otlp-proto-http`) hardcodes
`Content-Type: application/x-protobuf` and calls
`ExportMetricsServiceRequest.SerializeToString()` -- it has NO JSON
code path at all. A JSON-only ingestion endpoint is therefore
incompatible with every official OTel SDK's default HTTP metrics
exporter, regardless of `OTEL_EXPORTER_OTLP_PROTOCOL`. This module is
the smallest fix: decode the real wire format real SDKs actually send,
reusing (not duplicating) every existing validation rule.

`opentelemetry-proto` is the OpenTelemetry project's own generated
protobuf message definitions -- not a new trust boundary; the messages
it decodes into are themselves re-validated by the strict Pydantic
model below before anything is trusted.
"""

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest as PBExportMetricsServiceRequest,
)
from pydantic import ValidationError

from control_plane.domain.telemetry import OtlpExportMetricsRequest


class OtlpProtobufDecodeError(Exception):
    """Raised for a body that is not valid OTLP protobuf, or that
    decodes but fails the same structural validation the JSON path
    enforces. Always a 400 at the route layer -- never a 500."""


def parse_protobuf_export_request(raw_body: bytes) -> OtlpExportMetricsRequest:
    message = PBExportMetricsServiceRequest()
    try:
        message.ParseFromString(raw_body)
    except DecodeError as exc:
        raise OtlpProtobufDecodeError(f"could not decode request body as OTLP protobuf: {exc}") from exc

    # `use_integers_for_enums=True` matches the JSON path's own
    # `aggregationTemporality: int` field exactly (proto3 JSON would
    # otherwise emit the enum's string name, e.g. "DELTA", not `1`).
    # Default camelCase field naming and the default int64-as-string
    # mapping already match domain/telemetry.py's field names/types
    # verbatim -- no separate field-mapping table to keep in sync.
    as_dict = MessageToDict(message, use_integers_for_enums=True)

    try:
        return OtlpExportMetricsRequest.model_validate(as_dict)
    except ValidationError as exc:
        raise OtlpProtobufDecodeError(f"decoded OTLP protobuf body failed structural validation: {exc}") from exc
