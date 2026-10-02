#!/usr/bin/env bash
#
# verify-webhook-ingestion.sh — Phase 3C focused webhook ingestion
# verification.
#
# Proves the real POST /internal/v1/alertmanager/webhook endpoint,
# backed by the real PostgreSQL reliability.incidents table, works
# end-to-end — authentication, payload validation, atomic
# create-or-update deduplication (the real partial unique index,
# incidents_active_fingerprint_uniq), transaction boundaries, and a
# real PostgreSQL outage returning 503. Payloads are POSTed directly to
# control-plane's own webhook endpoint (never through Alertmanager
# itself) — this is deliberate: it isolates and proves the ingestion
# endpoint's own correctness in detail. The genuine
# Prometheus -> Alertmanager -> webhook -> incident chain is proven
# separately and exclusively by
# scripts/verify-alert-lifecycle.sh (VERIFY_INGESTION=true) /
# `make verify-alert-ingestion` — see that script's own docstring.
#
# Safe to rerun against a nonempty local database: every row this
# script creates uses a source_fingerprint carrying a UUID unique to
# this specific execution, and cleanup deletes only rows matching that
# exact prefix — never another run's rows, and never real data (the
# `source` column is always the fixed literal "alertmanager", set by
# the application itself, so — unlike scripts/verify-control-plane.sh,
# which can scope cleanup by a unique `source` value — this script
# scopes by source_fingerprint prefix instead, the same pattern
# scripts/verify-persistence.sh already uses for the same reason).
# Does not reset or delete any volume at any point.
#
# Exits non-zero immediately on the first failed check.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

section() {
  echo ""
  echo "=== $1 ==="
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# --------------------------------------------------------------------
# 0. Prepare the webhook secret and bring up postgres + control-plane
# --------------------------------------------------------------------
section "0. Prepare webhook secret; confirm postgres + control-plane ready"

./scripts/init-webhook-secret.sh

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (copy .env.example to .env)}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (copy .env.example to .env)}"
WEBHOOK_TOKEN="${CONTROL_PLANE_WEBHOOK_TOKEN:?CONTROL_PLANE_WEBHOOK_TOKEN must be set — run scripts/init-webhook-secret.sh}"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
WEBHOOK_URL="$CONTROL_PLANE_URL/internal/v1/alertmanager/webhook"

docker compose up -d postgres
postgres_healthy=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  [ "$health" = "healthy" ] && postgres_healthy=true && break
  echo "  attempt $i/20: postgres health=$health"
  sleep 3
done
[ "$postgres_healthy" = true ] || fail "postgres did not become healthy in time"

docker compose run --rm flyway migrate >/dev/null

# Recreates control-plane if CONTROL_PLANE_WEBHOOK_TOKEN changed since
# it last started (Compose detects the resolved-config diff) — so a
# freshly-generated secret always actually reaches a running process,
# with no manual restart needed.
docker compose up -d control-plane

cp_healthy=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q control-plane)" 2>/dev/null || true)"
  [ "$health" = "healthy" ] && cp_healthy=true && break
  echo "  attempt $i/20: control-plane docker health=$health"
  sleep 3
done
[ "$cp_healthy" = true ] || fail "control-plane did not become healthy in time"

ready_ok=false
for i in $(seq 1 20); do
  status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/health/ready" || echo 000)"
  [ "$status" = "200" ] && ready_ok=true && break
  echo "  attempt $i/20: GET /health/ready -> $status"
  sleep 3
done
[ "$ready_ok" = true ] || fail "control-plane readiness never reached 200"
echo "  postgres and control-plane ready"

RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
FP_PREFIX="verify-webhook-ingestion-${RUN_ID}"
CLEANUP_SQL="DELETE FROM reliability.incidents WHERE source = 'alertmanager' AND source_fingerprint LIKE '${FP_PREFIX}-%';"

psql_exec() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

# Set around the deliberate postgres outage in section 9 so the EXIT
# trap below knows whether it, not the user's own environment, is
# responsible for postgres currently being stopped.
POSTGRES_STOPPED_BY_THIS_SCRIPT=false

besteffort_cleanup() {
  # Captured as the very first statement: this is the exit status that
  # triggered the trap (e.g. from an earlier `fail()`'s `exit 1`, or a
  # natural 0). Explicitly restored via `exit "$exit_status"` below so
  # nothing this trap does — including a failed cleanup attempt or the
  # postgres-restart wait loop — can ever change the script's own
  # final/reported exit status.
  local exit_status=$?

  # Section 9 deliberately stops postgres to prove a real outage
  # returns 503. If an assertion fails after that stop but before the
  # section's own restart, postgres would otherwise be left stopped —
  # and the cleanup DELETE just below can never reach a stopped
  # database anyway. Restore it first, best-effort, bounded.
  if [ "$POSTGRES_STOPPED_BY_THIS_SCRIPT" = true ]; then
    echo "" >&2
    echo "-- trap: restoring postgres (this script left it stopped) --" >&2
    docker compose start postgres >/dev/null 2>&1 || true
    for i in $(seq 1 20); do
      health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
      [ "$health" = "healthy" ] && break
      sleep 3
    done
  fi

  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$CLEANUP_SQL" >/dev/null 2>&1 || true

  exit "$exit_status"
}
trap besteffort_cleanup EXIT

fingerprint_count() {
  psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = 'alertmanager' AND source_fingerprint = '$1';"
}

now_iso() {
  python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())'
}

# POSTs a one-alert webhook payload. Args: auth_header(or ""),
# fingerprint, status(firing|resolved), severity, summary, startsAt.
# Leaves HTTP status in $WH_STATUS and body in $WH_BODY.
post_single_alert() {
  local auth="$1" fp="$2" alert_status="$3" severity="$4" summary="$5" starts_at="$6"
  local body response curl_exit=0
  body="$(python3 -c "
import json
print(json.dumps({
    'version': '4', 'groupKey': 'test', 'status': '$alert_status', 'receiver': 'control-plane-webhook',
    'alerts': [{
        'status': '$alert_status',
        'labels': {'alertname': 'VerifyWebhookIngestionTest', 'severity': '$severity'},
        'annotations': {'summary': '$summary'},
        'startsAt': '$starts_at',
        'fingerprint': '$fp',
    }],
}))
")"
  if [ -n "$auth" ]; then
    response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X POST "$WEBHOOK_URL" \
      -H 'Content-Type: application/json' -H "Authorization: Bearer $auth" -d "$body")" || curl_exit=$?
  else
    response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X POST "$WEBHOOK_URL" \
      -H 'Content-Type: application/json' -d "$body")" || curl_exit=$?
  fi
  if [ "$curl_exit" -ne 0 ]; then
    WH_STATUS="000"
    WH_BODY=""
    return 0
  fi
  WH_STATUS="$(echo "$response" | tail -1)"
  WH_BODY="$(echo "$response" | sed '$d')"
}

# --------------------------------------------------------------------
# 1. Authentication
# --------------------------------------------------------------------
section "1. Authentication"

post_single_alert "" "${FP_PREFIX}-auth-a" firing critical "unauthenticated" "$(now_iso)"
[ "$WH_STATUS" = "401" ] || fail "missing Authorization header returned $WH_STATUS, expected 401: $WH_BODY"
[ "$(fingerprint_count "${FP_PREFIX}-auth-a")" = "0" ] || fail "an unauthenticated request wrote a row"
echo "  missing Authorization header -> 401, zero writes"

post_single_alert "wrong-token-value" "${FP_PREFIX}-auth-b" firing critical "wrong token" "$(now_iso)"
[ "$WH_STATUS" = "401" ] || fail "incorrect Bearer token returned $WH_STATUS, expected 401: $WH_BODY"
[ "$(fingerprint_count "${FP_PREFIX}-auth-b")" = "0" ] || fail "an incorrectly-authenticated request wrote a row"
echo "  incorrect Bearer token -> 401, zero writes"

# --------------------------------------------------------------------
# 2. Payload validation
# --------------------------------------------------------------------
section "2. Payload validation (422)"

status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" -d '{"not":"a valid payload"}')"
[ "$status" = "422" ] || fail "malformed payload returned $status, expected 422"
echo "  malformed payload -> 422"

status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" \
  -d '{"version":"4","groupKey":"x","status":"firing","receiver":"y","alerts":[]}')"
[ "$status" = "422" ] || fail "empty alert batch returned $status, expected 422"
echo "  empty alert batch -> 422"

mixed_valid_fp="${FP_PREFIX}-invalid-batch-valid"
mixed_body="$(python3 -c "
import json
print(json.dumps({
    'version': '4', 'groupKey': 'x', 'status': 'firing', 'receiver': 'y',
    'alerts': [
        {'status': 'firing', 'labels': {'alertname': 'OK', 'severity': 'critical'},
         'annotations': {}, 'startsAt': '$(now_iso)', 'fingerprint': '$mixed_valid_fp'},
        {'status': 'firing', 'labels': {'severity': 'critical'},
         'annotations': {}, 'startsAt': '$(now_iso)', 'fingerprint': '${FP_PREFIX}-invalid-batch-bad'},
    ],
}))
")"
status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" -d "$mixed_body")"
[ "$status" = "422" ] || fail "a batch with one invalid alert (missing alertname) returned $status, expected 422"
[ "$(fingerprint_count "$mixed_valid_fp")" = "0" ] || fail "an invalid batch still wrote its OTHER, valid alert — zero partial writes required"
echo "  a batch containing one invalid alert -> 422, and its other, otherwise-valid alert was NOT written"

# --------------------------------------------------------------------
# 3. First firing webhook creates an incident
# --------------------------------------------------------------------
section "3. First firing webhook creates an incident"

fp1="${FP_PREFIX}-a"
post_single_alert "$WEBHOOK_TOKEN" "$fp1" firing critical "Verify webhook ingestion test A" "$(now_iso)"
[ "$WH_STATUS" = "200" ] || fail "valid firing webhook returned $WH_STATUS, expected 200: $WH_BODY"
echo "$WH_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body == {'firing_processed': 1, 'resolved_ignored': 0, 'incidents_created': 1, 'incidents_updated': 0}, body
print('  ack body OK:', body)
"

id1="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source_fingerprint = '$fp1';" | head -1)"
[ -n "$id1" ] || fail "no row found for $fp1 after a 200 response"
status_val="$(psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id = '$id1';")"
[ "$status_val" = "open" ] || fail "newly created incident status=$status_val, expected open"
echo "  incident created: id=$id1 status=open"

# --------------------------------------------------------------------
# 4. A repeated firing webhook updates the same incident (exactly one
#    active row, id/first_seen_at/status preserved, last_seen_at
#    advances)
# --------------------------------------------------------------------
section "4. Repeated firing webhook updates the same incident"

first_seen_before="$(psql_exec -t -A -c "SELECT first_seen_at FROM reliability.incidents WHERE id = '$id1';")"
last_seen_before="$(psql_exec -t -A -c "SELECT last_seen_at FROM reliability.incidents WHERE id = '$id1';")"
sleep 2

post_single_alert "$WEBHOOK_TOKEN" "$fp1" firing critical "Verify webhook ingestion test A (updated)" "$(now_iso)"
[ "$WH_STATUS" = "200" ] || fail "repeated firing webhook returned $WH_STATUS, expected 200: $WH_BODY"
echo "$WH_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body == {'firing_processed': 1, 'resolved_ignored': 0, 'incidents_created': 0, 'incidents_updated': 1}, body
print('  ack body OK (updated, not created):', body)
"

row_count="$(fingerprint_count "$fp1")"
[ "$row_count" = "1" ] || fail "expected exactly 1 active row for $fp1 after a duplicate delivery, found $row_count"

id1_after="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source_fingerprint = '$fp1';")"
[ "$id1_after" = "$id1" ] || fail "incident id changed across a duplicate firing delivery: $id1 -> $id1_after"
first_seen_after="$(psql_exec -t -A -c "SELECT first_seen_at FROM reliability.incidents WHERE id = '$id1';")"
[ "$first_seen_after" = "$first_seen_before" ] || fail "first_seen_at changed across a duplicate delivery: $first_seen_before -> $first_seen_after"
last_seen_after="$(psql_exec -t -A -c "SELECT last_seen_at FROM reliability.incidents WHERE id = '$id1';")"
[ "$last_seen_after" != "$last_seen_before" ] || fail "last_seen_at did not advance across a duplicate delivery"
title_after="$(psql_exec -t -A -c "SELECT title FROM reliability.incidents WHERE id = '$id1';")"
[ "$title_after" = "Verify webhook ingestion test A (updated)" ] || fail "title was not refreshed on duplicate delivery: $title_after"
echo "  exactly 1 active row; id/first_seen_at preserved ($first_seen_before); last_seen_at advanced ($last_seen_before -> $last_seen_after); title refreshed"

# --------------------------------------------------------------------
# 5. A resolved historical incident is preserved; a new active
#    incident with the same fingerprint is allowed
# --------------------------------------------------------------------
section "5. Resolved historical incident preserved; new active incident allowed"

psql_exec -c "UPDATE reliability.incidents SET status = 'resolved', resolved_at = now() WHERE id = '$id1';" >/dev/null

post_single_alert "$WEBHOOK_TOKEN" "$fp1" firing critical "Verify webhook ingestion test A (recurred)" "$(now_iso)"
[ "$WH_STATUS" = "200" ] || fail "firing webhook after manual resolution returned $WH_STATUS, expected 200: $WH_BODY"
echo "$WH_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['incidents_created'] == 1 and body['incidents_updated'] == 0, body
print('  ack body OK (a NEW incident, not an update of the resolved one):', body)
"

row_count="$(fingerprint_count "$fp1")"
[ "$row_count" = "2" ] || fail "expected exactly 2 rows for $fp1 (1 resolved historical + 1 new active), found $row_count"
resolved_row_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source_fingerprint = '$fp1' AND status = 'resolved';")"
[ "$resolved_row_id" = "$id1" ] || fail "the original resolved row's id changed or is missing"
active_row_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source_fingerprint = '$fp1' AND status NOT IN ('resolved','closed');")"
[ -n "$active_row_id" ] && [ "$active_row_id" != "$id1" ] || fail "no distinct new active row was created alongside the preserved resolved one"
echo "  2 rows present: resolved historical ($id1, untouched) + new active ($active_row_id)"

# --------------------------------------------------------------------
# 6. Multiple distinct fingerprints produce distinct rows
# --------------------------------------------------------------------
section "6. Multiple distinct fingerprints produce distinct rows"

fp2="${FP_PREFIX}-b"
fp3="${FP_PREFIX}-c"
multi_body="$(python3 -c "
import json
now = '$(now_iso)'
print(json.dumps({
    'version': '4', 'groupKey': 'x', 'status': 'firing', 'receiver': 'y',
    'alerts': [
        {'status': 'firing', 'labels': {'alertname': 'MultiA', 'severity': 'warning'},
         'annotations': {}, 'startsAt': now, 'fingerprint': '$fp2'},
        {'status': 'firing', 'labels': {'alertname': 'MultiB', 'severity': 'info'},
         'annotations': {}, 'startsAt': now, 'fingerprint': '$fp3'},
    ],
}))
")"
status="$(curl -s --connect-timeout 2 --max-time 10 -o /tmp/verify-webhook-multi-resp.json -w '%{http_code}' -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" -d "$multi_body")"
[ "$status" = "200" ] || fail "multi-alert firing batch returned $status, expected 200: $(cat /tmp/verify-webhook-multi-resp.json)"
python3 -c "
import json
body = json.load(open('/tmp/verify-webhook-multi-resp.json'))
assert body == {'firing_processed': 2, 'resolved_ignored': 0, 'incidents_created': 2, 'incidents_updated': 0}, body
print('  ack body OK:', body)
"
rm -f /tmp/verify-webhook-multi-resp.json
[ "$(fingerprint_count "$fp2")" = "1" ] || fail "expected exactly 1 row for $fp2"
[ "$(fingerprint_count "$fp3")" = "1" ] || fail "expected exactly 1 row for $fp3"
echo "  2 distinct fingerprints -> 2 distinct rows"

# --------------------------------------------------------------------
# 7. Mixed firing/resolved notification; resolved-only creates nothing
# --------------------------------------------------------------------
section "7. Mixed firing/resolved batch; resolved-only creates no incident"

fp_firing="${FP_PREFIX}-mixed-firing"
fp_resolved="${FP_PREFIX}-mixed-resolved"
mixed_fr_body="$(python3 -c "
import json
now = '$(now_iso)'
print(json.dumps({
    'version': '4', 'groupKey': 'x', 'status': 'firing', 'receiver': 'y',
    'alerts': [
        {'status': 'firing', 'labels': {'alertname': 'MixedFiring', 'severity': 'critical'},
         'annotations': {}, 'startsAt': now, 'fingerprint': '$fp_firing'},
        {'status': 'resolved', 'labels': {'alertname': 'MixedResolved'},
         'annotations': {}, 'startsAt': now, 'fingerprint': '$fp_resolved'},
    ],
}))
")"
status="$(curl -s --connect-timeout 2 --max-time 10 -o /tmp/verify-webhook-mixed-resp.json -w '%{http_code}' -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" -d "$mixed_fr_body")"
[ "$status" = "200" ] || fail "mixed firing/resolved batch returned $status, expected 200"
python3 -c "
import json
body = json.load(open('/tmp/verify-webhook-mixed-resp.json'))
assert body == {'firing_processed': 1, 'resolved_ignored': 1, 'incidents_created': 1, 'incidents_updated': 0}, body
print('  ack body OK:', body)
"
rm -f /tmp/verify-webhook-mixed-resp.json
[ "$(fingerprint_count "$fp_firing")" = "1" ] || fail "expected exactly 1 row for the firing alert in the mixed batch"
[ "$(fingerprint_count "$fp_resolved")" = "0" ] || fail "a resolved-only alert in a mixed batch wrote an incident row"
echo "  mixed batch: firing alert created an incident, resolved alert created none"

fp_resolved_only="${FP_PREFIX}-resolved-only"
post_single_alert "$WEBHOOK_TOKEN" "$fp_resolved_only" resolved critical "resolved only" "$(now_iso)"
[ "$WH_STATUS" = "200" ] || fail "resolved-only webhook returned $WH_STATUS, expected 200: $WH_BODY"
echo "$WH_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body == {'firing_processed': 0, 'resolved_ignored': 1, 'incidents_created': 0, 'incidents_updated': 0}, body
print('  ack body OK (resolved-only):', body)
"
[ "$(fingerprint_count "$fp_resolved_only")" = "0" ] || fail "a resolved-only notification created an incident"
echo "  resolved-only notification: acknowledged, zero incidents created"

# --------------------------------------------------------------------
# 8. The existing GET incidents API exposes the result
# --------------------------------------------------------------------
section "8. The existing GET /api/v1/incidents API exposes the ingested incident"

detail_status="$(curl -s --connect-timeout 2 --max-time 10 -o /tmp/verify-webhook-detail.json -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$id1")"
[ "$detail_status" = "200" ] || fail "GET /api/v1/incidents/$id1 returned $detail_status, expected 200"
python3 -c "
import json
body = json.load(open('/tmp/verify-webhook-detail.json'))
assert body['id'] == '$id1', body
assert body['source'] == 'alertmanager', body
assert body['status'] == 'resolved', body
print('  GET /api/v1/incidents/{id} correctly exposes the webhook-ingested, later-resolved incident')
"
rm -f /tmp/verify-webhook-detail.json

# --------------------------------------------------------------------
# 9. Database outage returns 503 and writes nothing
# --------------------------------------------------------------------
section "9. Database outage returns 503, writes nothing"

docker compose stop postgres >/dev/null
POSTGRES_STOPPED_BY_THIS_SCRIPT=true
echo "  postgres stopped"

fp_outage="${FP_PREFIX}-outage"
post_single_alert "$WEBHOOK_TOKEN" "$fp_outage" firing critical "during outage" "$(now_iso)"
[ "$WH_STATUS" = "503" ] || fail "a webhook delivery during a real postgres outage returned $WH_STATUS, expected 503: $WH_BODY"
echo "  webhook delivery during postgres outage -> 503"

docker compose start postgres >/dev/null
postgres_healthy_after=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  [ "$health" = "healthy" ] && postgres_healthy_after=true && break
  echo "  attempt $i/20: postgres health=$health (recovering)"
  sleep 3
done
[ "$postgres_healthy_after" = true ] || fail "postgres did not become healthy again after the outage"
# Restarted successfully by the normal flow above — the EXIT trap no
# longer needs to do this itself.
POSTGRES_STOPPED_BY_THIS_SCRIPT=false

[ "$(fingerprint_count "$fp_outage")" = "0" ] || fail "a row for $fp_outage exists despite the 503 during the outage — a partial/ghost write occurred"
echo "  postgres recovered; confirmed zero rows were written during the outage"

ready_after_outage=false
for i in $(seq 1 20); do
  status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/health/ready" || echo 000)"
  [ "$status" = "200" ] && ready_after_outage=true && break
  sleep 3
done
[ "$ready_after_outage" = true ] || fail "control-plane readiness never recovered to 200 after the postgres outage"

post_single_alert "$WEBHOOK_TOKEN" "$fp_outage" firing critical "after recovery" "$(now_iso)"
[ "$WH_STATUS" = "200" ] || fail "a webhook delivery after recovery returned $WH_STATUS, expected 200: $WH_BODY"
[ "$(fingerprint_count "$fp_outage")" = "1" ] || fail "normal ingestion did not resume correctly after the outage"
echo "  normal ingestion resumed after postgres recovery (control-plane container was never restarted)"

# --------------------------------------------------------------------
# 10. Clean up ONLY this execution's test-created rows
# --------------------------------------------------------------------
section "10. Clean up only this execution's test-created rows"

before_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = 'alertmanager' AND source_fingerprint LIKE '${FP_PREFIX}-%';")"
# 2 rows for fp1 (section 5's resolved-historical + new-active pair) +
# 1 each for fp2, fp3 (section 6), the mixed-batch firing alert
# (section 7), and the post-recovery outage alert (section 9) = 6.
# auth failures, 422s, and resolved-only/resolved-in-a-mixed-batch
# deliveries are all asserted to write zero rows above.
[ "$before_count" = "6" ] || fail "expected exactly 6 rows for this run's fingerprint prefix before cleanup, found: $before_count"
# Not suppressed: a cleanup failure here fails the whole script.
psql_exec -c "$CLEANUP_SQL"
after_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = 'alertmanager' AND source_fingerprint LIKE '${FP_PREFIX}-%';")"
[ "$after_count" = "0" ] || fail "cleanup did not remove all of this run's rows (still present: $after_count)"
echo "  cleaned up: $before_count -> $after_count rows for fingerprint prefix '${FP_PREFIX}-'"
trap - EXIT

echo ""
echo "SUCCESS: Phase 3C webhook ingestion verification passed (real PostgreSQL, real HTTP API, real atomic upsert/dedup, real outage recovery)."
