"""Unit tests for POST /internal/v1/alertmanager/webhook (Phase 3C).

Like test_incidents.py, these use the in-memory FakeIncidentRepository
(conftest.py) via FastAPI's dependency_overrides — no real database.
Real PostgreSQL atomic-upsert/deduplication behavior is proven
separately by scripts/verify-webhook-ingestion.sh; see that script's
and conftest.FakeIncidentRepository's own docstrings. These tests
exist to prove the route/validation/auth/mapping layer behaves
correctly in isolation.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError

from control_plane.api.webhook_limits import MAX_WEBHOOK_BODY_BYTES

from control_plane.api.dependencies import get_incident_repository
from control_plane.main import app
from tests.conftest import WEBHOOK_TOKEN, make_incident_row

WEBHOOK_URL = "/internal/v1/alertmanager/webhook"
AUTH_HEADERS = {"Authorization": f"Bearer {WEBHOOK_TOKEN}"}


def _alert(**overrides) -> dict:
    now = datetime.now(UTC).isoformat()
    alert = {
        "status": "firing",
        "labels": {"alertname": "TelemetryPipelineUnavailable", "severity": "critical"},
        "annotations": {"summary": "OTel Collector scrape target is down", "description": "detailed text"},
        "startsAt": now,
        "fingerprint": "fp-abc123",
    }
    alert.update(overrides)
    return alert


def _resolved_alert(*, starts_at: str, ends_at: str | None = None, **overrides) -> dict:
    """A resolved alert needs a valid endsAt (required, tz-aware, >=
    startsAt) per domain/alertmanager_webhook.py's Phase 3D validation
    — defaults to 1 second after startsAt."""
    if ends_at is None:
        ends_at = (datetime.fromisoformat(starts_at) + timedelta(seconds=1)).isoformat()
    return _alert(status="resolved", startsAt=starts_at, endsAt=ends_at, **overrides)


def _payload(*alerts: dict, status: str = "firing") -> dict:
    return {
        "version": "4",
        "groupKey": "{}:{alertname=...}",
        "status": status,
        "receiver": "control-plane-webhook",
        "alerts": list(alerts) or [_alert()],
    }


def test_valid_authenticated_firing_payload_creates_incident(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 1,
        "resolved_processed": 0,
        "incidents_created": 1,
        "incidents_updated": 0,
        "incidents_resolved": 0,
        "incidents_ignored": 0,
    }
    assert len(repo.rows) == 1
    assert repo.rows[0]["source"] == "alertmanager"
    assert repo.rows[0]["source_fingerprint"] == "fp-abc123"
    assert repo.rows[0]["status"] == "open"
    assert repo.rows[0]["resolved_at"] is None
    assert repo.commit_count == 1


def test_missing_bearer_token_returns_401(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, json=_payload(_alert()))

    assert response.status_code == 401
    assert repo.rows == []


def test_incorrect_bearer_token_returns_401(use_repository, client):
    repo = use_repository([])

    response = client.post(WEBHOOK_URL, headers={"Authorization": "Bearer wrong-token"}, json=_payload(_alert()))

    assert response.status_code == 401
    assert repo.rows == []


def test_malformed_payload_returns_422(use_repository, client):
    use_repository([])

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json={"not": "a valid alertmanager payload"})

    assert response.status_code == 422


def test_missing_required_label_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(labels={"severity": "critical"})  # no alertname

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_unsupported_severity_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(labels={"alertname": "X", "severity": "catastrophic"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_invalid_fingerprint_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(fingerprint="   ")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_invalid_timestamp_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(startsAt="not-a-timestamp")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert))

    assert response.status_code == 422


def test_resolved_alert_missing_ends_at_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(status="resolved", fingerprint="fp-no-endsat")  # no endsAt at all

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert, status="resolved"))

    assert response.status_code == 422


def test_resolved_alert_ends_at_before_starts_at_returns_422(use_repository, client):
    use_repository([])

    starts_at = datetime.now(UTC)
    bad_alert = _alert(
        status="resolved",
        fingerprint="fp-bad-endsat",
        startsAt=starts_at.isoformat(),
        endsAt=(starts_at - timedelta(minutes=5)).isoformat(),
    )

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert, status="resolved"))

    assert response.status_code == 422


def test_resolved_alert_naive_ends_at_returns_422(use_repository, client):
    use_repository([])

    bad_alert = _alert(
        status="resolved", fingerprint="fp-naive-endsat", endsAt="2026-01-01T00:00:00"
    )  # no timezone offset

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(bad_alert, status="resolved"))

    assert response.status_code == 422


def test_empty_alert_batch_returns_422(use_repository, client):
    use_repository([])

    body = _payload()
    body["alerts"] = []
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=body)

    assert response.status_code == 422


def test_multi_alert_notification_creates_distinct_incidents(use_repository, client):
    repo = use_repository([])

    alert_a = _alert(fingerprint="fp-a")
    alert_b = _alert(fingerprint="fp-b")

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert_a, alert_b))

    assert response.status_code == 200
    body = response.json()
    assert body["firing_processed"] == 2
    assert body["incidents_created"] == 2
    assert body["incidents_ignored"] == 0
    fingerprints = {row["source_fingerprint"] for row in repo.rows}
    assert fingerprints == {"fp-a", "fp-b"}


def test_mixed_firing_and_resolved_notification(use_repository, client):
    repo = use_repository([])

    firing = _alert(fingerprint="fp-firing")
    # No incident exists yet for fp-resolved, so this resolved alert
    # has nothing to resolve — safely ignored (Phase 3D), not an error.
    resolved = _resolved_alert(fingerprint="fp-resolved", starts_at=datetime.now(UTC).isoformat(), labels={"alertname": "X"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(firing, resolved, status="firing"))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 1,
        "resolved_processed": 1,
        "incidents_created": 1,
        "incidents_updated": 0,
        "incidents_resolved": 0,
        "incidents_ignored": 1,
    }
    assert len(repo.rows) == 1
    assert repo.rows[0]["source_fingerprint"] == "fp-firing"


def test_resolved_notification_with_no_matching_active_incident_is_ignored(use_repository, client):
    repo = use_repository([])

    resolved = _resolved_alert(
        fingerprint="fp-resolved-only", starts_at=datetime.now(UTC).isoformat(), labels={"alertname": "X"}
    )

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 0,
        "resolved_processed": 1,
        "incidents_created": 0,
        "incidents_updated": 0,
        "incidents_resolved": 0,
        "incidents_ignored": 1,
    }
    assert repo.rows == []


def test_summary_and_description_mapping(use_repository, client):
    repo = use_repository([])

    alert = _alert(annotations={"summary": "Custom summary text", "description": "Custom description text"})

    client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert repo.rows[0]["title"] == "Custom summary text"
    assert repo.rows[0]["description"] == "Custom description text"


def test_safe_title_fallback_to_alertname(use_repository, client):
    repo = use_repository([])

    alert = _alert(annotations={}, labels={"alertname": "FallbackAlertName", "severity": "warning"})

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    assert repo.rows[0]["title"] == "FallbackAlertName"
    assert repo.rows[0]["description"] is None


def test_duplicate_firing_preserves_incident_identity(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(hours=1)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-dup",
        status="acknowledged",
        first_seen_at=occurrence_starts_at,
    )
    repo = use_repository([existing])

    # startsAt MUST match the active incident's first_seen_at for this
    # to be recognized as a repeat delivery of the SAME occurrence
    # (Phase 3D occurrence-identity matching, ingestion/service.py) —
    # a mismatched startsAt would instead be conservatively ignored.
    alert = _alert(fingerprint="fp-dup", startsAt=occurrence_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 1,
        "resolved_processed": 0,
        "incidents_created": 0,
        "incidents_updated": 1,
        "incidents_resolved": 0,
        "incidents_ignored": 0,
    }
    assert len(repo.rows) == 1
    assert repo.rows[0]["id"] == existing["id"]
    assert repo.rows[0]["first_seen_at"] == existing["first_seen_at"]
    # Status is preserved, not reset to "open".
    assert repo.rows[0]["status"] == "acknowledged"


def test_firing_older_than_active_incident_is_ignored(use_repository, client):
    # A firing delivery OLDER than the currently active incident's
    # first_seen_at (a stale replay of an occurrence that predates the
    # one we already know about) must never regress that active
    # incident.
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-older-stale",
        status="investigating",
        title="Original title",
        first_seen_at=datetime.now(UTC) - timedelta(hours=2),
    )
    repo = use_repository([existing])

    older_starts_at = datetime.now(UTC) - timedelta(hours=3)
    alert = _alert(fingerprint="fp-older-stale", startsAt=older_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_created"] == 0
    assert body["incidents_updated"] == 0
    assert body["incidents_ignored"] == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["title"] == "Original title"
    assert repo.rows[0]["status"] == "investigating"


def test_firing_newer_than_active_incident_still_updates_it(use_repository, client):
    # A firing delivery NEWER than the currently active incident's
    # occurrence watermark means the active row was never resolved
    # (e.g. a missed resolved notification) but Alertmanager is
    # reporting ongoing/renewed firing activity for it regardless. This
    # can only happen while the row is still active (the partial unique
    # index blocks a second active row), so it can never be a genuine
    # resolved-then-recurred occurrence — it must be treated as an
    # update, not silently dropped forever. A real integration run
    # (scripts/verify-alert-lifecycle.sh) found exactly this scenario
    # against a real, previously-unresolved incident. first_seen_at
    # stays untouched, but the watermark (occurrence_starts_at) MUST
    # advance to this delivery's startsAt — see
    # test_delayed_resolved_for_superseded_occurrence_does_not_resolve_active_incident
    # for why that advancement matters (post-review correction).
    original_first_seen_at = datetime.now(UTC) - timedelta(hours=2)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-newer-active",
        status="investigating",
        title="Original title",
        first_seen_at=original_first_seen_at,
    )
    repo = use_repository([existing])

    newer_starts_at = datetime.now(UTC)
    alert = _alert(fingerprint="fp-newer-active", startsAt=newer_starts_at.isoformat(), annotations={"summary": "Renewed firing"})
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_created"] == 0
    assert body["incidents_updated"] == 1
    assert body["incidents_ignored"] == 0
    assert len(repo.rows) == 1
    # Status and first_seen_at are never touched by this update.
    assert repo.rows[0]["status"] == "investigating"
    assert repo.rows[0]["first_seen_at"] == original_first_seen_at
    assert repo.rows[0]["title"] == "Renewed firing"
    # The watermark DOES advance — this is the post-review correction.
    assert repo.rows[0]["occurrence_starts_at"] == newer_starts_at


def test_stale_firing_replay_does_not_recreate_resolved_incident(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(hours=3)
    resolved_historical = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-stale-replay",
        status="resolved",
        first_seen_at=occurrence_starts_at,
        resolved_at=datetime.now(UTC) - timedelta(hours=1),
    )
    repo = use_repository([resolved_historical])

    # A delayed/retried firing notification for the SAME (now
    # resolved) occurrence must be ignored, not reopen or duplicate it.
    alert = _alert(fingerprint="fp-stale-replay", startsAt=occurrence_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 1,
        "resolved_processed": 0,
        "incidents_created": 0,
        "incidents_updated": 0,
        "incidents_resolved": 0,
        "incidents_ignored": 1,
    }
    assert len(repo.rows) == 1
    assert repo.rows[0]["status"] == "resolved"


def test_genuine_recurrence_creates_new_incident_preserving_history(use_repository, client):
    old_occurrence_starts_at = datetime.now(UTC) - timedelta(days=1)
    resolved_historical = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-recurrence",
        status="resolved",
        first_seen_at=old_occurrence_starts_at,
        resolved_at=datetime.now(UTC) - timedelta(hours=12),
    )
    repo = use_repository([resolved_historical])

    new_occurrence_starts_at = datetime.now(UTC)
    alert = _alert(fingerprint="fp-recurrence", startsAt=new_occurrence_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_created"] == 1
    assert body["incidents_ignored"] == 0
    assert len(repo.rows) == 2
    statuses = {row["id"]: row["status"] for row in repo.rows}
    assert statuses[resolved_historical["id"]] == "resolved"
    new_rows = [row for row in repo.rows if row["id"] != resolved_historical["id"]]
    assert len(new_rows) == 1
    assert new_rows[0]["status"] == "open"


def test_alertmanager_resolves_matching_active_occurrence(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(minutes=30)
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-resolve-me",
        status="investigating",
        first_seen_at=occurrence_starts_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    ends_at = datetime.now(UTC)
    resolved = _resolved_alert(
        fingerprint="fp-resolve-me", starts_at=occurrence_starts_at.isoformat(), ends_at=ends_at.isoformat()
    )
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "firing_processed": 0,
        "resolved_processed": 1,
        "incidents_created": 0,
        "incidents_updated": 0,
        "incidents_resolved": 1,
        "incidents_ignored": 0,
    }
    assert repo.rows[0]["status"] == "resolved"
    assert repo.rows[0]["resolved_at"] is not None
    assert repo.rows[0]["first_seen_at"] == occurrence_starts_at


def test_duplicate_resolution_is_idempotent(use_repository, client):
    occurrence_starts_at = datetime.now(UTC) - timedelta(minutes=30)
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-dup-resolve",
        status="open",
        first_seen_at=occurrence_starts_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    resolved = _resolved_alert(fingerprint="fp-dup-resolve", starts_at=occurrence_starts_at.isoformat())
    first = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert first.status_code == 200
    assert first.json()["incidents_resolved"] == 1

    # A second, duplicate resolved delivery for the exact same
    # occurrence must not error and must not change anything further —
    # the incident is already resolved.
    second = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))
    assert second.status_code == 200
    body = second.json()
    assert body["incidents_resolved"] == 0
    assert body["incidents_ignored"] == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["status"] == "resolved"


def test_resolved_notification_for_unobserved_newer_occurrence_does_not_resolve_active_incident(use_repository, client):
    # Post-review correction: the original implementation compared a
    # resolved alert's startsAt against the active incident's
    # first_seen_at using "equal or newer resolves it" — which meant a
    # resolved notification carrying a startsAt NEWER than anything
    # this service ever saw fire would still resolve the incident. That
    # is "blindly" resolving an older incident from a notification this
    # service has no actual evidence pertains to it (it never observed
    # a firing alert for that startsAt at all). The corrected behavior
    # requires an EXACT watermark (occurrence_starts_at) match — see
    # ingestion/service.py's own docstring.
    original_first_seen_at = datetime.now(UTC) - timedelta(hours=2)
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-resolve-unobserved",
        status="open",
        first_seen_at=original_first_seen_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    unobserved_newer_starts_at = datetime.now(UTC)
    resolved = _resolved_alert(fingerprint="fp-resolve-unobserved", starts_at=unobserved_newer_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_resolved"] == 0
    assert body["incidents_ignored"] == 1
    assert repo.rows[0]["status"] == "open"
    assert repo.rows[0]["resolved_at"] is None


def test_delayed_resolved_for_superseded_occurrence_does_not_resolve_active_incident(use_repository, client):
    # Reproduces the exact regression independent review found: A fires
    # (creating the incident), B fires later while A's incident is
    # STILL ACTIVE (updating it in place and advancing the watermark —
    # see test_firing_newer_than_active_incident_still_updates_it), and
    # only then does a delayed resolved notification for the ORIGINAL
    # occurrence A arrive. It must NOT resolve the incident, because the
    # incident now represents B, not A.
    a_starts_at = datetime.now(UTC) - timedelta(hours=2)
    b_starts_at = datetime.now(UTC) - timedelta(hours=1)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-superseded",
        status="open",
        first_seen_at=a_starts_at,
        occurrence_starts_at=b_starts_at,  # B already accepted; watermark advanced
        resolved_at=None,
    )
    repo = use_repository([existing])

    delayed_resolved_a = _resolved_alert(
        fingerprint="fp-superseded", starts_at=a_starts_at.isoformat(), ends_at=(a_starts_at + timedelta(minutes=5)).isoformat()
    )
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(delayed_resolved_a, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_resolved"] == 0
    assert body["incidents_ignored"] == 1
    assert repo.rows[0]["status"] == "open"
    assert repo.rows[0]["resolved_at"] is None
    # The watermark itself is also untouched by an ignored event.
    assert repo.rows[0]["occurrence_starts_at"] == b_starts_at


def test_resolved_notification_matching_watermark_resolves_incident(use_repository, client):
    # The positive counterpart: B resolves correctly using its OWN
    # startsAt once it is the incident's current watermark.
    a_starts_at = datetime.now(UTC) - timedelta(hours=2)
    b_starts_at = datetime.now(UTC) - timedelta(hours=1)
    existing = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-resolve-watermark-match",
        status="open",
        first_seen_at=a_starts_at,
        occurrence_starts_at=b_starts_at,
        resolved_at=None,
    )
    repo = use_repository([existing])

    resolved_b = _resolved_alert(fingerprint="fp-resolve-watermark-match", starts_at=b_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(resolved_b, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_resolved"] == 1
    assert body["incidents_ignored"] == 0
    assert repo.rows[0]["status"] == "resolved"
    assert repo.rows[0]["resolved_at"] is not None
    # first_seen_at is still never touched by resolution.
    assert repo.rows[0]["first_seen_at"] == a_starts_at


def test_delayed_duplicate_firing_after_occurrence_resolved_does_not_create_incident(use_repository, client):
    # Reproduces the second half of the exact regression independent
    # review found: A fires, B fires later while A's incident is still
    # active (updating it, watermark -> B), B resolves, and THEN a
    # delayed duplicate firing replay of B arrives. Comparing against
    # the resolved row's immutable first_seen_at (A's startsAt) would
    # incorrectly treat B's startsAt as "newer than anything on record"
    # and spawn a second, spurious incident. Comparing against the
    # watermark (which reflects B, the occurrence the row actually last
    # represented) correctly recognizes this as a stale replay.
    a_starts_at = datetime.now(UTC) - timedelta(hours=2)
    b_starts_at = datetime.now(UTC) - timedelta(hours=1)
    resolved_historical = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-delayed-duplicate-after-resolve",
        status="resolved",
        first_seen_at=a_starts_at,
        occurrence_starts_at=b_starts_at,  # the row's last accepted occurrence was B, not A
        resolved_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    repo = use_repository([resolved_historical])

    delayed_duplicate_b = _alert(fingerprint="fp-delayed-duplicate-after-resolve", startsAt=b_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(delayed_duplicate_b))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_created"] == 0
    assert body["incidents_updated"] == 0
    assert body["incidents_ignored"] == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["status"] == "resolved"


def test_genuine_subsequent_occurrence_after_watermark_advance_creates_new_incident(use_repository, client):
    # The full chain's final step: after A -> B (update) -> B resolved,
    # a genuinely NEW occurrence C (startsAt strictly newer than B's
    # watermark) must still create a new incident, preserving the
    # resolved row's history untouched.
    a_starts_at = datetime.now(UTC) - timedelta(hours=2)
    b_starts_at = datetime.now(UTC) - timedelta(hours=1)
    c_starts_at = datetime.now(UTC)
    resolved_historical = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-genuine-after-watermark",
        status="resolved",
        first_seen_at=a_starts_at,
        occurrence_starts_at=b_starts_at,
        resolved_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    repo = use_repository([resolved_historical])

    alert_c = _alert(fingerprint="fp-genuine-after-watermark", startsAt=c_starts_at.isoformat())
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(alert_c))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_created"] == 1
    assert body["incidents_ignored"] == 0
    assert len(repo.rows) == 2
    statuses = {row["id"]: row["status"] for row in repo.rows}
    assert statuses[resolved_historical["id"]] == "resolved"
    new_rows = [row for row in repo.rows if row["id"] != resolved_historical["id"]]
    assert len(new_rows) == 1
    assert new_rows[0]["status"] == "open"
    assert new_rows[0]["occurrence_starts_at"] == c_starts_at


def test_stale_resolved_notification_cannot_resolve_newer_recurrence(use_repository, client):
    old_occurrence_starts_at = datetime.now(UTC) - timedelta(days=1)
    new_occurrence_starts_at = datetime.now(UTC)
    # The NEW occurrence is the one currently active.
    active = make_incident_row(
        source="alertmanager",
        source_fingerprint="fp-stale-resolve",
        status="open",
        first_seen_at=new_occurrence_starts_at,
        resolved_at=None,
    )
    repo = use_repository([active])

    # A delayed resolved notification for the OLD occurrence must not
    # resolve the new, active one.
    stale_resolved = _resolved_alert(
        fingerprint="fp-stale-resolve",
        starts_at=old_occurrence_starts_at.isoformat(),
        ends_at=(old_occurrence_starts_at + timedelta(minutes=5)).isoformat(),
    )
    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(stale_resolved, status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body["incidents_resolved"] == 0
    assert body["incidents_ignored"] == 1
    assert repo.rows[0]["status"] == "open"
    assert repo.rows[0]["resolved_at"] is None


def test_database_error_during_ingestion_returns_503_not_success(use_repository, client):
    class _BrokenRepository:
        async def acquire_fingerprint_lock(self, **kwargs):
            raise OperationalError("SELECT pg_advisory_xact_lock(...)", {}, Exception("connection refused, password=supersecret"))

        async def commit(self):
            raise AssertionError("commit() must never be reached if acquire_fingerprint_lock raised")

    app.dependency_overrides[get_incident_repository] = lambda: _BrokenRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "supersecret" not in response.text


def test_database_outage_produces_503(use_repository, client):
    class _OutageRepository:
        async def acquire_fingerprint_lock(self, **kwargs):
            raise OperationalError("SELECT pg_advisory_xact_lock(...)", {}, Exception("could not connect to server"))

        async def commit(self):
            raise AssertionError("commit() must never be reached after a connection failure")

    app.dependency_overrides[get_incident_repository] = lambda: _OutageRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503


def test_dns_resolution_failure_also_produces_503(use_repository, client):
    # A real integration run (scripts/verify-webhook-ingestion.sh,
    # section 9) found that fully stopping PostgreSQL can surface as a
    # raw socket.gaierror from asyncpg, never wrapped into a
    # SQLAlchemyError — main.py registers a second handler
    # (OSError -> 503) specifically so this still returns 503, not an
    # unhandled 500. This test reproduces that at the unit level.
    class _DnsFailureRepository:
        async def acquire_fingerprint_lock(self, **kwargs):
            import socket

            raise socket.gaierror("[Errno -2] Name or service not known")

        async def commit(self):
            raise AssertionError("commit() must never be reached after a connection failure")

    app.dependency_overrides[get_incident_repository] = lambda: _DnsFailureRepository()

    response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}


def test_no_secrets_in_auth_error_responses(use_repository, client):
    use_repository([])

    missing = client.post(WEBHOOK_URL, json=_payload(_alert()))
    wrong = client.post(WEBHOOK_URL, headers={"Authorization": "Bearer wrong-token"}, json=_payload(_alert()))

    for response in (missing, wrong):
        assert response.status_code == 401
        assert WEBHOOK_TOKEN not in response.text


def test_unconfigured_server_secret_fails_closed(use_repository, client):
    use_repository([])
    original = app.state.webhook_token
    app.state.webhook_token = None
    try:
        response = client.post(WEBHOOK_URL, headers=AUTH_HEADERS, json=_payload(_alert()))
        assert response.status_code == 401
    finally:
        app.state.webhook_token = original


def test_oversized_body_returns_413(use_repository, client):
    repo = use_repository([])

    oversized = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        content=oversized,
    )

    assert response.status_code == 413
    assert repo.rows == []
    assert WEBHOOK_TOKEN not in response.text


def test_oversized_body_with_understated_content_length_still_returns_413(use_repository, client):
    # The real byte-count enforcement (not just the Content-Length
    # header) is what must catch this — a client could omit the header
    # entirely (chunked transfer-encoding) or simply lie about it.
    repo = use_repository([])

    oversized = b"y" * (MAX_WEBHOOK_BODY_BYTES + 1)
    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json", "Content-Length": "10"},
        content=oversized,
    )

    assert response.status_code == 413
    assert repo.rows == []


def test_body_at_the_size_limit_is_not_rejected_for_size(use_repository, client):
    # A payload AT the byte limit must not be rejected by the size
    # guard itself — it may still fail Pydantic validation (expected,
    # since this specific oversized-but-well-formed-looking body isn't
    # a real alert payload), but that must surface as 422, not 413.
    use_repository([])

    body = b'{"padding": "' + b"z" * (MAX_WEBHOOK_BODY_BYTES - 20) + b'"}'
    assert len(body) <= MAX_WEBHOOK_BODY_BYTES

    response = client.post(
        WEBHOOK_URL,
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        content=body,
    )

    assert response.status_code != 413
