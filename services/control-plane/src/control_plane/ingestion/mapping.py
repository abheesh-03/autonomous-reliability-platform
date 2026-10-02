"""Alertmanager FIRING alert -> reliability.incidents field mapping
(Phase 3C).

Only ever called for alerts whose status == "firing" — resolved-only
notifications are acknowledged but never reach this function (see
ingestion/service.py). Field choices mirror
database/migrations/V1__create_incident_schema.sql exactly; this
module never invents a column and never stores a fabricated
Alertmanager event id — source_fingerprint is the alert's own real
`fingerprint`, not Alertmanager's per-delivery groupKey (which would
incorrectly collapse every alert in one notification group into a
single fingerprint).
"""

from datetime import datetime
from typing import TypedDict

from control_plane.domain.alertmanager_webhook import AlertmanagerAlert


class IncidentFields(TypedDict):
    source: str
    source_fingerprint: str
    title: str
    description: str | None
    severity: str
    first_seen_at: datetime
    last_seen_at: datetime


def map_firing_alert_to_incident_fields(alert: AlertmanagerAlert, *, ingested_at: datetime) -> IncidentFields:
    # labels.alertname is guaranteed present and non-blank by
    # AlertmanagerAlert's own validation; annotations.summary is not
    # guaranteed, so the fallback keeps title always non-blank,
    # satisfying incidents' own `CHECK (btrim(title) <> '')`.
    summary = (alert.annotations.get("summary") or "").strip()
    title = summary if summary else alert.labels["alertname"].strip()

    return IncidentFields(
        source="alertmanager",
        source_fingerprint=alert.fingerprint,
        title=title,
        description=alert.annotations.get("description") or None,
        severity=alert.labels["severity"],
        first_seen_at=alert.startsAt,
        # "The time of accepted firing ingestion", not the alert's own
        # startsAt — ingested_at is captured once per webhook batch by
        # the caller (ingestion/service.py), not re-read per alert.
        last_seen_at=ingested_at,
    )
