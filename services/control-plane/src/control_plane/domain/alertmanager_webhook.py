"""Pydantic v2 request/response models for the Alertmanager webhook
ingestion endpoint (Phase 3C).

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
alerts actually get persisted is a per-alert decision made in
ingestion/service.py.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.domain.incident import VALID_SEVERITIES

# Reasonable, generous-but-bounded limits for a trusted internal
# endpoint (see api/webhook_auth.py — every request here is already
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
        # is useful even for a resolved-only acknowledgement. severity
        # is only required (and validated against the real DB
        # vocabulary) for a FIRING alert, since only firing alerts are
        # ever mapped onto an incident's severity column — a
        # resolved-only alert never reaches ingestion/mapping.py at
        # all (see ingestion/service.py), so it may legitimately lack
        # or carry a stale severity label.
        alertname = self.labels.get("alertname", "").strip()
        if not alertname:
            raise ValueError("labels.alertname is required and must not be blank")

        if self.status == "firing":
            severity = self.labels.get("severity")
            if severity not in VALID_SEVERITIES:
                raise ValueError(
                    f"labels.severity must be one of {sorted(VALID_SEVERITIES)} for a firing alert, got {severity!r}"
                )

        return self


class AlertmanagerWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal["4"]
    groupKey: str
    status: Literal["firing", "resolved"]
    receiver: str
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=MAX_ALERTS_PER_BATCH)


class WebhookAckResponse(BaseModel):
    """A deliberately small acknowledgement — no incident lifecycle
    transition is ever implemented by this endpoint (see
    ingestion/service.py's module docstring)."""

    firing_processed: int
    resolved_ignored: int
    incidents_created: int
    incidents_updated: int
