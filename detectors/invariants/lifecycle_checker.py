"""Gate D: the one concrete invariant checker this phase implements --
incident lifecycle event consistency, backed by control-plane's real,
existing, read-only `GET /api/v1/incidents` and
`GET /api/v1/incidents/{id}/events` APIs.

Event semantics were INSPECTED directly in
`services/control-plane/src/control_plane/repositories/
incident_repository.py` and `domain/lifecycle.py` before writing this
checker (never assumed):

  - 'created': ALWAYS previous_status=None, new_status='open' (the
    INSERT path always sets status='open').
  - 'observed': ALWAYS previous_status == new_status -- Alertmanager
    re-delivering the same still-firing alert while the incident is
    already active; genuinely NOT a status change.
  - 'status_transition': ALWAYS previous_status != new_status, and
    ALWAYS validated (by both the operator PATCH endpoint and the
    Alertmanager auto-resolution path) against the SAME centralized
    state machine before being persisted.

`ALLOWED_TRANSITIONS`/`VALID_STATUSES` below are a deliberate, cited
COPY of `control_plane.domain.lifecycle.ALLOWED_TRANSITIONS` /
`control_plane.domain.incident.VALID_STATUSES` -- this package has no
shared-library import boundary into that service, so the 6-entry
matrix and 6-value vocabulary are reproduced here explicitly, not
invented. If control-plane's own matrix ever changes, this constant
must be updated to match (see
`docs/architecture/phase-11b-autonomous-failure-discovery.md` section
8 for this exact limitation, stated honestly).

Ordering: events are sorted by (occurred_at, id) -- id as the
tie-breaker, mirroring the real API's own
`ORDER BY occurred_at ASC, id ASC` exactly, so even equal timestamps
(a documented, legitimate possibility) never produce an
ordering-dependent false violation.
"""

from datetime import datetime

from detectors.clients.control_plane_client import ControlPlaneClient, ControlPlaneUnavailableError, IncidentEventRecord
from detectors.schemas.invariant import (
    InvariantCheckReport,
    InvariantCheckResult,
    InvariantDefinition,
    InvariantViolation,
)

VALID_STATUSES: frozenset[str] = frozenset(
    {"open", "acknowledged", "investigating", "remediating", "resolved", "closed"}
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"acknowledged", "investigating", "resolved"}),
    "acknowledged": frozenset({"investigating", "resolved"}),
    "investigating": frozenset({"remediating", "resolved"}),
    "remediating": frozenset({"investigating", "resolved"}),
    "resolved": frozenset({"closed"}),
    "closed": frozenset(),
}

INVARIANT_DEFINITION = InvariantDefinition(
    invariant_id="incident_lifecycle_event_consistency",
    description=(
        "Every incident's recorded audit-event history is internally consistent with control-plane's own "
        "lifecycle state machine: the first event is 'created' (previous_status=None, new_status='open'); "
        "every 'observed' event records no actual status change; every 'status_transition' event moves "
        "between two DIFFERENT, legal statuses per the state machine."
    ),
    required_sources=[
        "control-plane GET /api/v1/incidents",
        "control-plane GET /api/v1/incidents/{id}/events",
    ],
    scope="one incident's complete (fully-paginated) event history",
    expected_condition="see description",
    completeness_prerequisites=[
        "the full event history must be retrievable within the client's bounded pagination limits"
    ],
    evidence_required=["the incident's own full, ordered event list"],
    severity_hint="medium -- an inconsistency here indicates a bug in control-plane's own audit trail, not a production application incident",
    verification_method="deterministic replay of ALLOWED_TRANSITIONS against each recorded event, read-only",
)


def _check_one_incident(incident_id: str, events: list[IncidentEventRecord]) -> list[InvariantViolation]:
    if not events:
        return []  # a genuinely eventless incident (e.g. pre-audit-trail) is explicitly valid per the real API's own docstring

    ordered = sorted(events, key=lambda e: (e.occurred_at, e.id))
    violations: list[InvariantViolation] = []

    first = ordered[0]
    if first.event_type != "created":
        violations.append(
            InvariantViolation(
                subject_id=incident_id,
                explanation=f"first recorded event is {first.event_type!r}, expected 'created'",
                evidence_reference=f"event id={first.id}",
            )
        )
    elif first.previous_status is not None or first.new_status != "open":
        violations.append(
            InvariantViolation(
                subject_id=incident_id,
                explanation=(
                    f"'created' event has previous_status={first.previous_status!r}, "
                    f"new_status={first.new_status!r} (expected None, 'open')"
                ),
                evidence_reference=f"event id={first.id}",
            )
        )

    for e in ordered:
        for status in (e.previous_status, e.new_status):
            if status is not None and status not in VALID_STATUSES:
                violations.append(
                    InvariantViolation(
                        subject_id=incident_id,
                        explanation=f"status value {status!r} is outside the known vocabulary {sorted(VALID_STATUSES)}",
                        evidence_reference=f"event id={e.id}",
                    )
                )

    # Correction-round Issue 2: replay the history in order, tracking
    # the EXPECTED CURRENT STATUS as a running value -- the previous
    # implementation validated each event's own (previous_status,
    # new_status) pair against the abstract transition matrix in
    # isolation, which let a `status_transition` event's
    # `previous_status` silently disagree with what the PRIOR events
    # actually established (e.g. "created: None->open" followed by
    # "status_transition: investigating->resolved", with no recorded
    # transition into 'investigating' at all -- individually legal per
    # the matrix, but discontinuous as a sequence). Continuity is now
    # checked explicitly: every 'observed' and 'status_transition'
    # event's own `previous_status` must equal `expected_status`
    # (whatever the prior events in THIS SAME replay established),
    # never merely "some legal prior status per the matrix in the
    # abstract". `expected_status` only ever changes on a validated
    # 'status_transition' -- 'observed' never mutates it, matching the
    # real system's own semantics.
    expected_status = first.new_status if first.event_type == "created" else None

    for e in ordered[1:]:
        if e.event_type == "created":
            violations.append(
                InvariantViolation(
                    subject_id=incident_id,
                    explanation="an extra 'created' event was recorded after the first",
                    evidence_reference=f"event id={e.id}",
                )
            )
        elif e.event_type == "observed":
            if e.previous_status != e.new_status:
                violations.append(
                    InvariantViolation(
                        subject_id=incident_id,
                        explanation=(
                            f"'observed' event recorded an actual status change "
                            f"({e.previous_status!r} -> {e.new_status!r}); 'observed' must never change status"
                        ),
                        evidence_reference=f"event id={e.id}",
                    )
                )
            elif expected_status is not None and e.previous_status != expected_status:
                violations.append(
                    InvariantViolation(
                        subject_id=incident_id,
                        explanation=(
                            f"'observed' event's previous_status ({e.previous_status!r}) does not match the "
                            f"status established by the preceding event history ({expected_status!r}) -- "
                            "discontinuous history"
                        ),
                        evidence_reference=f"event id={e.id}",
                    )
                )
        elif e.event_type == "status_transition":
            if e.previous_status is None:
                violations.append(
                    InvariantViolation(
                        subject_id=incident_id,
                        explanation="'status_transition' event has previous_status=None -- only 'created' may have that",
                        evidence_reference=f"event id={e.id}",
                    )
                )
            elif e.previous_status == e.new_status:
                violations.append(
                    InvariantViolation(
                        subject_id=incident_id,
                        explanation=(
                            f"'status_transition' event recorded no actual change "
                            f"({e.previous_status!r} -> {e.new_status!r})"
                        ),
                        evidence_reference=f"event id={e.id}",
                    )
                )
            else:
                if e.new_status not in ALLOWED_TRANSITIONS.get(e.previous_status, frozenset()):
                    violations.append(
                        InvariantViolation(
                            subject_id=incident_id,
                            explanation=f"illegal transition {e.previous_status!r} -> {e.new_status!r} per the lifecycle matrix",
                            evidence_reference=f"event id={e.id}",
                        )
                    )
                if expected_status is not None and e.previous_status != expected_status:
                    violations.append(
                        InvariantViolation(
                            subject_id=incident_id,
                            explanation=(
                                f"'status_transition' event claims previous_status={e.previous_status!r}, but the "
                                f"preceding event history establishes the status was actually {expected_status!r} "
                                f"at that point -- no recorded transition into {e.previous_status!r} exists "
                                "(discontinuous history)"
                            ),
                            evidence_reference=f"event id={e.id}",
                        )
                    )
                # Advance the tracked state regardless of whether this
                # transition was itself flagged above -- a discontinuity
                # is reported once, at the point it was introduced,
                # never re-derived from an already-flagged event's own
                # (still real, recorded) new_status going forward.
                expected_status = e.new_status
        # any event_type outside the three known ones is itself a (structural, schema-level) surprise this
        # checker cannot interpret meaningfully -- deliberately NOT flagged as a lifecycle violation, since
        # it is a different class of problem (an unrecognized EventType the service's own schema would
        # already reject at the HTTP layer before this checker ever saw it).

    return violations


async def check_incident_lifecycle_consistency(
    client: ControlPlaneClient,
    incident_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> InvariantCheckReport:
    violations: list[InvariantViolation] = []
    evidence_provenance: list[str] = []
    subjects_checked = 0
    incomplete_count = 0

    for incident_id in incident_ids:
        try:
            page = await client.list_all_incident_events(incident_id)
        except ControlPlaneUnavailableError as exc:
            return InvariantCheckReport(
                invariant_id=INVARIANT_DEFINITION.invariant_id,
                checked_observation_window_start=window_start.isoformat(),
                checked_observation_window_end=window_end.isoformat(),
                result=InvariantCheckResult.SOURCE_UNAVAILABLE,
                subjects_checked=subjects_checked,
                violations=violations,
                explanation=f"control-plane became unreachable while checking incident {incident_id}: {exc}",
                evidence_provenance=evidence_provenance,
            )

        if not page.complete:
            incomplete_count += 1
            continue  # never judge an incomplete/possibly-truncated history

        subjects_checked += 1
        evidence_provenance.append(f"GET /api/v1/incidents/{incident_id}/events (total={page.total})")
        violations.extend(_check_one_incident(incident_id, page.events))

    # Final evidence-integrity correction round, Issue B: SATISFIED is
    # now only ever returned when EVERY requested incident's history
    # was both completely retrieved AND passed validation -- a
    # complete, clean incident sitting alongside an INCOMPLETE one
    # must never be reported as if the whole requested set were
    # satisfied. A proven violation among the completely-checked
    # incidents still takes priority (VIOLATED), but the explanation
    # now also names the separate, unresolved incomplete-history gap
    # rather than silently dropping it.
    if violations:
        result = InvariantCheckResult.VIOLATED
        explanation = f"{len(violations)} violation(s) found across {subjects_checked} checked incident(s)"
        if incomplete_count:
            explanation += (
                f"; additionally, {incomplete_count} incident(s) had incomplete/unretrievable event history and "
                "could not be checked (not counted as either satisfied or violated)"
            )
    elif incomplete_count > 0:
        result = InvariantCheckResult.INSUFFICIENT_EVIDENCE
        explanation = (
            (f"{subjects_checked} incident(s) were completely checked with no violations, but " if subjects_checked else "")
            + f"{incomplete_count} incident(s) had incomplete/unretrievable event history -- the full requested "
            "set cannot be established as SATISFIED until every requested history is completely retrieved"
        )
    elif subjects_checked == 0:
        result = InvariantCheckResult.INSUFFICIENT_EVIDENCE
        explanation = "no incidents were available to check"
    else:
        result = InvariantCheckResult.SATISFIED
        explanation = f"all {subjects_checked} checked incident(s) (complete event history) satisfied lifecycle consistency"

    return InvariantCheckReport(
        invariant_id=INVARIANT_DEFINITION.invariant_id,
        checked_observation_window_start=window_start.isoformat(),
        checked_observation_window_end=window_end.isoformat(),
        result=result,
        subjects_checked=subjects_checked,
        violations=violations,
        explanation=explanation,
        evidence_provenance=evidence_provenance,
    )
