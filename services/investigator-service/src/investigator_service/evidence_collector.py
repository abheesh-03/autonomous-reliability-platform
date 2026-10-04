"""Assembles the normalized EvidencePackage (Phase 5 §5) from the four
read-only clients, BEFORE any LLM call. Incident retrieval is
mandatory — a failure there propagates (there is no evidence package
without a real incident). Every telemetry source is independently
best-effort: a failure there (including a malformed/unparseable
response — see clients/*.py's own hardening) is recorded as an
"unavailable" outcome and the investigation proceeds with a partial
package, never fabricated data standing in for it.
"""

import json
import logging
from datetime import datetime, timedelta

from investigator_service.clients.control_plane import ControlPlaneClient
from investigator_service.clients.loki import LokiClient, LokiUnavailableError
from investigator_service.clients.prometheus import PrometheusClient, PrometheusUnavailableError
from investigator_service.clients.tempo import TempoClient, TempoUnavailableError
from investigator_service.config import EvidenceBounds
from investigator_service.domain.evidence import EvidenceItem, EvidencePackage, SourceOutcome
from investigator_service.redaction import redact

logger = logging.getLogger("investigator_service.evidence")


class EvidenceCollector:
    def __init__(
        self,
        control_plane: ControlPlaneClient,
        prometheus: PrometheusClient,
        loki: LokiClient,
        tempo: TempoClient,
        bounds: EvidenceBounds,
    ) -> None:
        self._control_plane = control_plane
        self._prometheus = prometheus
        self._loki = loki
        self._tempo = tempo
        self._bounds = bounds

    async def collect(self, incident_id: str) -> EvidencePackage:
        # Mandatory: propagates IncidentNotFoundError / ControlPlaneUnavailableError
        # to the caller, which maps them to 404 / 503 respectively (see
        # api/investigations.py) — there is no such thing as a partial
        # investigation with no real incident behind it.
        incident = await self._control_plane.get_incident(incident_id)
        events, events_total = await self._control_plane.get_all_events(
            incident_id, max_events=self._bounds.max_audit_events
        )

        window_start = incident.first_seen_at - timedelta(seconds=self._bounds.evidence_window_before_seconds)
        window_end = (incident.resolved_at or incident.last_seen_at) + timedelta(
            seconds=self._bounds.evidence_window_after_seconds
        )

        next_id = _IdSequence()
        items: list[EvidenceItem] = []
        outcomes: list[SourceOutcome] = []

        items.append(self._incident_core_item(next_id, incident, self._bounds.max_incident_text_length))
        items.extend(self._event_items(next_id, events))
        outcomes.append(self._control_plane_outcome(events, events_total, self._bounds.max_audit_events))

        await self._collect_prometheus(next_id, window_start, window_end, items, outcomes)
        await self._collect_loki(next_id, window_start, window_end, items, outcomes)
        await self._collect_tempo(next_id, window_start, window_end, items, outcomes)

        return EvidencePackage(
            incident=incident,
            events=events,
            events_total=events_total,
            items=items,
            source_outcomes=outcomes,
            collected_at=datetime.now(incident.first_seen_at.tzinfo),
        )

    @staticmethod
    def _control_plane_outcome(events, events_total: int, max_events: int) -> SourceOutcome:
        if not events_total:
            return SourceOutcome(
                source="control_plane",
                status="ok",
                detail=(
                    "incident retrieved; no audit events exist for it (valid for a pre-audit-trail "
                    "incident or one never mutated by the application)"
                ),
                query_summary="GET /api/v1/incidents/{id}, GET /api/v1/incidents/{id}/events",
            )
        if len(events) < events_total:
            # Phase 5 correction round #2A: a truncated mandatory
            # retrieval must NEVER be described as complete. "partial"
            # is a distinct status from "ok" specifically for this —
            # the real total is always reported alongside what was
            # actually retrieved, and this limitation is also carried
            # into the prompt (llm/prompt.py renders every outcome,
            # including this one) and into missing_evidence (see
            # investigator.py).
            return SourceOutcome(
                source="control_plane",
                status="partial",
                detail=(
                    f"retrieved only {len(events)} of {events_total} real audit events — the "
                    f"remaining {events_total - len(events)} were not retrieved because the "
                    f"configured safety cap (INVESTIGATOR_MAX_AUDIT_EVENTS={max_events}) was reached; "
                    "this is a genuine gap in mandatory evidence, not invented data, and the audit "
                    "history shown is NOT the complete real history"
                ),
                query_summary="GET /api/v1/incidents/{id}, GET /api/v1/incidents/{id}/events",
            )
        return SourceOutcome(
            source="control_plane",
            status="ok",
            detail=f"incident retrieved; all {len(events)} of {events_total} real audit event(s) retrieved",
            query_summary="GET /api/v1/incidents/{id}, GET /api/v1/incidents/{id}/events",
        )

    @staticmethod
    def _incident_core_item(next_id: "_IdSequence", incident, max_text_length: int) -> EvidenceItem:
        # Phase 5 correction round #2C/#7: title/description are
        # free-text, operator/alert-annotation-controlled columns with
        # NO length limit at the database level
        # (database/migrations/V1__create_incident_schema.sql) and are
        # untrusted content — bounded and redacted here, the same as
        # every other piece of external text this service handles.
        title = redact(incident.title)[:max_text_length]
        description = redact(incident.description)[:max_text_length] if incident.description else None
        return EvidenceItem(
            id=next_id.next(),
            source="control_plane",
            observed_at=incident.first_seen_at,
            window_start=incident.first_seen_at,
            window_end=incident.resolved_at,
            summary=f"Incident {incident.id}: {title!r} (severity={incident.severity}, status={incident.status})",
            detail=(
                f"source={incident.source} source_fingerprint={incident.source_fingerprint} "
                f"description={description!r} first_seen_at={incident.first_seen_at.isoformat()} "
                f"last_seen_at={incident.last_seen_at.isoformat()} "
                f"resolved_at={incident.resolved_at.isoformat() if incident.resolved_at else 'null'}"
            ),
            reference={"endpoint": "GET /api/v1/incidents/{id}"},
        )

    @staticmethod
    def _event_items(next_id: "_IdSequence", events) -> list[EvidenceItem]:
        out = []
        for ev in events:
            metadata = json.dumps(ev.metadata, sort_keys=True)
            if len(metadata) > 300:
                metadata = metadata[:297] + "..."
            out.append(
                EvidenceItem(
                    id=next_id.next(),
                    source="control_plane",
                    observed_at=ev.occurred_at,
                    summary=(
                        f"Audit event: {ev.event_type} by {ev.actor_type} "
                        f"({ev.previous_status or 'null'} -> {ev.new_status})"
                    ),
                    detail=f"metadata={metadata}",
                    reference={"endpoint": "GET /api/v1/incidents/{id}/events", "event_id": str(ev.id)},
                )
            )
        return out

    async def _collect_prometheus(self, next_id, window_start, window_end, items, outcomes) -> None:
        try:
            summaries = await self._prometheus.query_window(
                window_start, window_end, max_points=self._bounds.max_prometheus_series
            )
        except PrometheusUnavailableError as exc:
            outcomes.append(SourceOutcome(source="prometheus", status="unavailable", detail=str(exc)))
            return

        any_signal = False
        for s in summaries:
            if s.sample_count == 0:
                detail = "no samples returned in this window (metric absent or Prometheus has no data this old)"
            else:
                last_value_str = f"{s.last_value:.4g}" if s.last_value is not None else "n/a"
                detail = (
                    f"{s.sample_count} sample(s); {s.nonzero_or_below_one_count} of interest "
                    f"(nonzero rate / below-1 availability); extreme value {s.max_value:.4g} at "
                    f"{s.max_value_at.isoformat() if s.max_value_at else 'n/a'}; last value {last_value_str}"
                )
                if s.nonzero_or_below_one_count:
                    any_signal = True
            items.append(
                EvidenceItem(
                    id=next_id.next(),
                    source="prometheus",
                    window_start=window_start,
                    window_end=window_end,
                    summary=f"Prometheus: {s.description}",
                    detail=detail,
                    reference={"promql": s.promql},
                )
            )
        outcomes.append(
            SourceOutcome(
                source="prometheus",
                status="ok" if any_signal else "no_data",
                detail=(
                    "at least one of the four monitored metrics showed activity in this window"
                    if any_signal
                    else "all four monitored metrics were flat/healthy (or absent) in this window"
                ),
                query_summary=f"{len(summaries)} allowlisted range queries",
            )
        )

    async def _collect_loki(self, next_id, window_start, window_end, items, outcomes) -> None:
        try:
            lines = await self._loki.query_window(
                window_start,
                window_end,
                max_lines=self._bounds.max_loki_lines,
                max_line_length=self._bounds.max_loki_line_length,
            )
        except LokiUnavailableError as exc:
            outcomes.append(SourceOutcome(source="loki", status="unavailable", detail=str(exc)))
            return

        for line in lines:
            items.append(
                EvidenceItem(
                    id=next_id.next(),
                    source="loki",
                    observed_at=line.timestamp,
                    summary=f"Log line from {line.service}",
                    # Real log lines are untrusted, operator/application
                    # -influenced free text -- bounded-redacted the same
                    # as the incident description above (Phase 5
                    # correction round #7). Best-effort, not a guarantee
                    # — see redaction.py's own docstring.
                    detail=redact(line.message),
                    reference={"service": line.service},
                )
            )
        outcomes.append(
            SourceOutcome(
                source="loki",
                status="ok" if lines else "no_data",
                detail=(
                    f"{len(lines)} log line(s) retrieved across the four application services"
                    if lines
                    else "no application log lines found in this window"
                ),
                query_summary="application service logs in the incident window",
            )
        )

    async def _collect_tempo(self, next_id, window_start, window_end, items, outcomes) -> None:
        try:
            traces = await self._tempo.search_window(
                window_start, window_end, max_traces=self._bounds.max_tempo_traces
            )
        except TempoUnavailableError as exc:
            outcomes.append(SourceOutcome(source="tempo", status="unavailable", detail=str(exc)))
            return

        for trace in traces:
            # Phase 5 correction round #4: enrich the bounded candidate
            # trace (already found via search) with its REAL span/
            # service relationships, reusing the exact
            # GET /api/v2/traces/{traceID} endpoint and response shape
            # scripts/verify-tempo-trace.py already proved against this
            # real Tempo. Best-effort, bounded to the candidates already
            # found (never a new, separate search) -- a failure here
            # only labels the limitation, it never fails the
            # investigation and never fabricates a span relationship.
            detail_summary = await self._tempo.get_trace_detail(trace.trace_id)
            if detail_summary is not None:
                relationship = (
                    f"{detail_summary.span_count} real span(s) across "
                    f"{len(detail_summary.service_names)} service(s) ({', '.join(detail_summary.service_names)}); "
                    f"root span service(s): {', '.join(detail_summary.root_span_services) or 'unknown'}"
                )
            else:
                relationship = "detailed span retrieval unavailable for this candidate trace"
            items.append(
                EvidenceItem(
                    id=next_id.next(),
                    source="tempo",
                    observed_at=trace.start_time,
                    summary=f"Candidate trace rooted at {trace.root_service_name} ({trace.duration_ms}ms)",
                    detail=(
                        f"trace_id={trace.trace_id} root_trace_name={trace.root_trace_name!r}; {relationship} "
                        "-- time+service match only; application logs carry no trace ID today, so this "
                        "is NOT a confirmed causal link to this incident, only a candidate in the same window"
                    ),
                    reference={"trace_id": trace.trace_id},
                )
            )
        outcomes.append(
            SourceOutcome(
                source="tempo",
                status="ok" if traces else "no_data",
                detail=(
                    f"{len(traces)} candidate trace(s) found rooted at checkout-service in this window "
                    "(time+service correlation only, not a confirmed causal link)"
                    if traces
                    else "no checkout-service-rooted traces found in this window"
                ),
                query_summary="Tempo tag search: service.name=checkout-service",
            )
        )


class _IdSequence:
    """E1, E2, E3, ... — deterministic, stable within one collection."""

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"E{self._n}"
