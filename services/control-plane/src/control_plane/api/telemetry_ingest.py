"""Phase 16 Gate 4: the one real, authenticated OTLP metrics ingestion
endpoint -- accepts both OTLP/HTTP JSON and OTLP/HTTP protobuf bodies
(correction round item 3; see ingestion/otlp_protobuf.py for why
protobuf support was added).

Request flow, in order:
  1. api/telemetry_limits.py's ASGI middleware -- raw byte-size cap,
     before anything is buffered.
  2. api/telemetry_auth.py::require_telemetry_credential -- real
     credential lookup, constant-time secret verification, revocation
     check, auth-failure AND ingestion rate limits. Derives the
     TRUSTED organization_id/service_id used for everything below.
  3. Content-Type dispatch (`_parse_request_body`, this module):
     `application/x-protobuf` is decoded via
     ingestion/otlp_protobuf.py; `application/json` (or no/empty
     Content-Type, for backward compatibility with existing JSON
     clients) is validated directly against OtlpExportMetricsRequest
     (domain/telemetry.py). Either path produces the SAME validated
     shape -- a structurally invalid JSON body is rejected with 422; a
     malformed/invalid protobuf body or an unrecognized Content-Type
     is rejected with 400/415.
  4. ingestion/telemetry_service.py::extract_points -- semantic
     validation/extraction (temporality, unit, time window); a
     structurally valid but unusable payload raises
     TelemetryIngestionRejected -> 400.
  5. One bounded, durably-deduplicated batch INSERT
     (repositories/telemetry_repository.py), with organization_id/
     service_id taken EXCLUSIVELY from step 2's verified credential --
     never from the parsed OTLP body at any point in this file.
  6. The credential's own `last_verified_telemetry_at` is touched.
  7. ingestion/telemetry_threshold_detector.py evaluates a short,
     bounded recent window and upserts/resolves a real, tenant-scoped
     incident via the EXISTING incident repository.
  8. An OTLP-compatible `ExportMetricsServiceResponse`-shaped JSON body
     is returned with HTTP 200 (item 2) -- `{}` on full success, or
     `{"partialSuccess": {...}}` if some (not all) data points in an
     otherwise-accepted batch were dropped.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from control_plane.api.dependencies import (
    get_incident_repository,
    get_integration_credential_repository,
    get_service_repository,
    get_telemetry_repository,
)
from control_plane.api.telemetry_auth import TelemetryCredentialContext, require_telemetry_credential
from control_plane.domain.telemetry import OtlpExportMetricsRequest, SUPPORTED_METRIC_NAME
from control_plane.ingestion.otlp_protobuf import OtlpProtobufDecodeError, parse_protobuf_export_request
from control_plane.ingestion.telemetry_service import TelemetryIngestionRejected, extract_points
from control_plane.ingestion.telemetry_threshold_detector import evaluate_and_upsert
from control_plane.repositories.incident_repository import IncidentRepository
from control_plane.repositories.integration_credential_repository import IntegrationCredentialRepository
from control_plane.repositories.service_repository import ServiceRepository
from control_plane.repositories.telemetry_repository import TelemetryRepository

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger("control_plane.telemetry_ingest")


async def _parse_request_body(request: Request) -> OtlpExportMetricsRequest:
    """Item 3: dispatches on Content-Type -- the ASGI body-size guard
    (api/telemetry_limits.py) has already bounded `raw_body` before
    this ever runs, regardless of which branch is taken."""
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    raw_body = await request.body()

    if content_type == "application/x-protobuf":
        try:
            return parse_protobuf_export_request(raw_body)
        except OtlpProtobufDecodeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if content_type in ("", "application/json"):
        try:
            parsed_json = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid JSON body: {exc}") from exc
        try:
            return OtlpExportMetricsRequest.model_validate(parsed_json)
        except ValidationError as exc:
            # `include_context=False` -- a custom field_validator's
            # raised ValueError would otherwise end up inside
            # `ctx: {"error": ValueError(...)}`, not JSON serializable.
            # `include_input=False` -- a rejected NaN/Infinity value
            # would otherwise appear verbatim as `"input": inf`, which
            # Starlette's own strict JSONResponse (`allow_nan=False`)
            # also refuses to serialize. Either one left in would turn
            # this clean 422 into an unrelated 500.
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_context=False, include_url=False, include_input=False),
            ) from exc

    raise HTTPException(
        status_code=415,
        detail=f"unsupported content-type {content_type!r}; expected application/json or application/x-protobuf",
    )


# Gate 6: the detector's own short, reactive evaluation window -- NOT
# the same as the dashboard's own longer display window
# (api/service_telemetry.py). Short and recent on purpose: a real
# instrumented client exporting every few seconds will have several
# accepted batches within this window shortly after a real failure
# begins, so the detector reacts promptly without needing a separate
# polling loop.
DETECTOR_WINDOW = timedelta(minutes=5)


@router.post("/telemetry/otlp/v1/metrics", status_code=200)
async def ingest_otlp_metrics(
    request: Request,
    credential_ctx: Annotated[TelemetryCredentialContext, Depends(require_telemetry_credential)],
    telemetry_repo: Annotated[TelemetryRepository, Depends(get_telemetry_repository)],
    credential_repo: Annotated[IntegrationCredentialRepository, Depends(get_integration_credential_repository)],
    service_repo: Annotated[ServiceRepository, Depends(get_service_repository)],
    incident_repo: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> dict:
    body = await _parse_request_body(request)
    try:
        points, rejected_count = extract_points(body)
    except TelemetryIngestionRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    accepted = await telemetry_repo.insert_batch(
        organization_id=credential_ctx.organization_id,
        service_id=credential_ctx.service_id,
        integration_credential_id=credential_ctx.integration_id,
        points=[point.model_dump(exclude={}) for point in points],
    )

    await credential_repo.touch_last_verified_telemetry(credential_ctx.integration_id)

    # Gate 6: inline, synchronous threshold evaluation -- see
    # ingestion/telemetry_threshold_detector.py's own module docstring
    # for why this is deliberately not a separate polling service this
    # round. A failure here must never fail the ingestion response
    # itself (the telemetry was already durably written above) -- this
    # is detection, not the ingestion contract.
    try:
        service = await service_repo.get_by_id_for_organization(
            credential_ctx.organization_id, credential_ctx.service_id
        )
        if service is not None:
            now = datetime.now(UTC)
            window = await telemetry_repo.get_window_aggregate(
                organization_id=credential_ctx.organization_id,
                service_id=credential_ctx.service_id,
                since=now - DETECTOR_WINDOW,
                until=now,
            )
            await evaluate_and_upsert(
                incident_repo,
                organization_id=credential_ctx.organization_id,
                service_id=credential_ctx.service_id,
                service_name=service["name"],
                window_request_count=int(window["request_count"] or 0),
                window_error_count=int(window["error_count"] or 0),
                window_minutes=int(DETECTOR_WINDOW.total_seconds() // 60),
                now=now,
            )
    except Exception:
        logger.exception("telemetry threshold detector failed for service_id=%s", credential_ctx.service_id)

    # Item 2: an OTLP-compatible `ExportMetricsServiceResponse` JSON
    # body -- `{}` for full success (the real collector's own shape for
    # "nothing to report"), or `partialSuccess` describing how many
    # data points were dropped (bad timestamp/inconsistent interval)
    # even though the export as a whole was still accepted. A
    # conformant OTLP exporter already tolerates/ignores an empty `{}`
    # body on 200; this is never a custom shape a real exporter would
    # choke on.
    if rejected_count:
        return {
            "partialSuccess": {
                "rejectedDataPoints": str(rejected_count),
                "errorMessage": (
                    f"{rejected_count} data point(s) for {SUPPORTED_METRIC_NAME!r} were outside the accepted "
                    f"observation window or had an inconsistent interval and were dropped; {accepted} data "
                    "point(s) were accepted."
                ),
            }
        }
    return {}
