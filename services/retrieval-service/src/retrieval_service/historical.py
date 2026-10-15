"""Builds a bounded, sanitized textual representation of ONE real
incident (Phase 6 §7), from fields control-plane's existing GET APIs
actually return -- never an invented field, never a direct read of
reliability.incidents/reliability.incident_events.

This representation is what gets chunked (chunking.py) and embedded;
it is deliberately built from the SAME kind of fields
investigator_service.evidence_collector already uses for its own
incident-core evidence item, so a historical incident's retrieval
chunk and a current incident's own evidence item describe comparable
things. An incident with no audit events produces a representation
with an explicit "(no audit events recorded)" line -- never invented
history (Phase 6 §7).
"""

from retrieval_service.domain.incident_snapshot import IncidentEventSnapshot, IncidentSnapshot
from retrieval_service.redaction import redact


def build_historical_incident_text(
    incident: IncidentSnapshot,
    events: list[IncidentEventSnapshot],
    events_total: int,
    max_text_length: int,
) -> str:
    title = redact(incident.title)[:max_text_length]
    description = redact(incident.description)[:max_text_length] if incident.description else "(none)"

    lines = [
        f"Historical incident {incident.id}",
        f"title: {title}",
        f"description: {description}",
        f"severity: {incident.severity}",
        f"source: {incident.source}",
        f"status: {incident.status}",
        f"first_seen_at: {incident.first_seen_at.isoformat()}",
        f"last_seen_at: {incident.last_seen_at.isoformat()}",
        f"resolved_at: {incident.resolved_at.isoformat() if incident.resolved_at else 'null'}",
        "",
        "Audit timeline:",
    ]

    if not events:
        lines.append("  (no audit events recorded for this incident)")
    else:
        for ev in events:
            lines.append(
                f"  - {ev.occurred_at.isoformat()}: {ev.event_type} by {ev.actor_type} "
                f"({ev.previous_status or 'null'} -> {ev.new_status})"
            )
        if len(events) < events_total:
            lines.append(
                f"  (only {len(events)} of {events_total} real audit events included due to the "
                "configured safety cap -- this is a genuine gap in what was indexed, not the complete "
                "real history)"
            )

    return "\n".join(lines)
