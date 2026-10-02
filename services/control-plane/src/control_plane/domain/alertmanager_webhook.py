"""Pydantic v2 request/response models for the Alertmanager webhook
ingestion endpoint (Phase 3C, extended Phase 3D).

Matches Alertmanager's real webhook_configs version-4 JSON payload
shape (notify/webhook.Message in Alertmanager's own source) — only the
fields this service actually needs are modeled; every model uses
`extra="ignore"` so fields we don't need (generatorURL,
truncatedAlerts, groupLabels, commonLabels, commonAnnotations,
externalURL, ...) are tolerated, not rejected. This means a slightly
richer future Alertmanager payload never starts failing ingestion.

Critically, alert-level status drives all ingestion behavior
(AlertmanagerAlert.status), never the group-level status
(AlertmanagerWebhookPayload.status) — a single delivery's `alerts` list
can and does contain a mix of "firing" and "resolved" entries (e.g. one
alert instance recovers while a sibling in the same group is still
firing), so only the group-level envelope is validated here; which
alerts actually get persisted, updated, or resolved is a per-alert
decision made in ingestion/service.py.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.domain.incident import VALID_SEVERITIES

# Reasonable, generous-but-bounded limits for a trusted internal
# endpoint (see api/auth.py — every request here is already
# Bearer-authenticated before this model is even parsed). Not a
# production rate-limiter; just enough to stop a wildly malformed or
# abusive payload from being accepted at all.
MAX_ALERTS_PER_BATCH = 100
MAX_LABELS_PER_ALERT = 50
MAX_LABEL_VALUE_LENGTH = 2000


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    # Phase 3D: required and validated only for a RESOLVED alert — the
    # genuine resolution time (see ingestion/service.py's resolution
    # handling). Alertmanager always includes this field for a firing
    # alert too, but sets it to the Go zero-value sentinel
    # ("0001-01-01T00:00:00Z", meaning "not yet known"), which this
    # model deliberately accepts but never relies on — firing alerts
    # never read endsAt at all.
    endsAt: datetime | None = None
    fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_alert(self) -> "AlertmanagerAlert":
        if not self.fingerprint.strip():
            raise ValueError("fingerprint must not be blank")

        if self.startsAt.tzinfo is None:
            raise ValueError("startsAt must include timezone information")

        for mapping_name, mapping in (("labels", self.labels), ("annotations", self.annotations)):
            if len(mapping) > MAX_LABELS_PER_ALERT:
                raise ValueError(f"{mapping_name} has too many entries (max {MAX_LABELS_PER_ALERT})")
            for key, value in mapping.items():
                if len(value) > MAX_LABEL_VALUE_LENGTH:
                    raise ValueError(f"{mapping_name}[{key!r}] exceeds {MAX_LABEL_VALUE_LENGTH} characters")

        # alertname is required on every alert regardless of status —
        # it is the safe title fallback (see ingestion/mapping.py) and
        # is useful even for a resolved notification. severity is only
        # required (and validated against the real DB vocabulary) for
        # a FIRING alert, since only firing alerts are ever mapped onto
        # an incident's severity column — a resolved alert may
        # legitimately lack or carry a stale severity label.
        alertname = self.labels.get("alertname", "").strip()
        if not alertname:
            raise ValueError("labels.alertname is required and must not be blank")

        if self.status == "firing":
            severity = self.labels.get("severity")
            if severity not in VALID_SEVERITIES:
                raise ValueError(
                    f"labels.severity must be one of {sorted(VALID_SEVERITIES)} for a firing alert, got {severity!r}"
                )

        if self.status == "resolved":
            # A resolved alert must carry a genuine, timezone-aware
            # resolution time that is not before its own startsAt —
            # "appropriate validation" before this value is ever used
            # to set resolved_at (ingestion/service.py). This also
            # rejects the Go zero-value sentinel a still-firing alert
            # carries, since year 1 is always before startsAt.
            if self.endsAt is None:
                raise ValueError("endsAt is required for a resolved alert")
            if self.endsAt.tzinfo is None:
                raise ValueError("endsAt must include timezone information")
            if self.endsAt < self.startsAt:
                raise ValueError("endsAt must not be before startsAt")

        return self


class AlertmanagerWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal["4"]
    groupKey: str
    status: Literal["firing", "resolved"]
    receiver: str
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=MAX_ALERTS_PER_BATCH)


class WebhookAckResponse(BaseModel):
    """A deliberately small acknowledgement.

    Phase 3D note: `resolved_processed` replaces Phase 3C's
    `resolved_ignored` field name — resolved alerts are no longer
    unconditionally ignored (see ingestion/service.py), so a field
    named "ignored" would now be actively misleading for the common
    case. `incidents_ignored` separately counts events that WERE
    safely skipped for a specific, legitimate reason (a stale/
    mismatched firing replay, a resolved notification with no matching
    active incident, or one that doesn't match the currently active
    occurrence) — see
    docs/architecture/phase-3d-incident-lifecycle.md.
    """

    firing_processed: int
    resolved_processed: int
    incidents_created: int
    incidents_updated: int
    incidents_resolved: int
    incidents_ignored: int
