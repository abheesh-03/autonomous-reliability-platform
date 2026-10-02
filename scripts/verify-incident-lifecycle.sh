#!/usr/bin/env bash
#
# verify-incident-lifecycle.sh — Phase 3D real PostgreSQL incident
# lifecycle acceptance.
#
# Proves the real PATCH /api/v1/incidents/{id}/status endpoint and the
# real Alertmanager-driven automatic resolution path
# (POST /internal/v1/alertmanager/webhook), backed by the real
# PostgreSQL reliability.incidents table, work end-to-end: the full
# state machine, optimistic-concurrency (expected_status), real
# PostgreSQL restart durability, occurrence-identity recurrence/stale-
# replay handling, concurrent-request safety, and access control.
#
# Webhook payloads here are POSTed directly to control-plane's own
# endpoint (not through a real Alertmanager) — this is deliberate and
# consistent with scripts/verify-webhook-ingestion.sh's own convention:
# it isolates and proves the ingestion/resolution logic itself. The
# genuine Prometheus -> Alertmanager -> webhook -> resolution chain is
# proven separately and exclusively by scripts/verify-alert-lifecycle.sh
# (VERIFY_INGESTION=true) / `make verify-alert-ingestion`.
#
# Safe to rerun against a nonempty local database: every row this
# script creates uses a `source` value unique to this specific
# execution, and cleanup deletes only rows matching that exact value —
# never another run's rows, and never real data. Does not reset or
# delete any volume at any point.
#
# Post-review correction: sections 8-10 below specifically reproduce
# the occurrence-watermark regression independent review found (a
# firing update into a still-active incident never advanced
# first_seen_at, so a later delayed resolved notification for the
# ORIGINAL occurrence could incorrectly resolve an incident that had
# already moved on, and a delayed duplicate replay of the occurrence it
# now represented could be mistaken for a genuine new recurrence) —
# see database/migrations/V2__add_occurrence_watermark.sql and
# docs/architecture/phase-3d-incident-lifecycle.md.
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
# 0. Prepare secrets; bring up postgres + control-plane
# --------------------------------------------------------------------
section "0. Prepare secrets; confirm postgres + control-plane ready"

./scripts/init-webhook-secret.sh

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (copy .env.example to .env)}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (copy .env.example to .env)}"
LIFECYCLE_TOKEN="${CONTROL_PLANE_LIFECYCLE_TOKEN:?CONTROL_PLANE_LIFECYCLE_TOKEN must be set — run scripts/init-webhook-secret.sh}"
WEBHOOK_TOKEN="${CONTROL_PLANE_WEBHOOK_TOKEN:?CONTROL_PLANE_WEBHOOK_TOKEN must be set — run scripts/init-webhook-secret.sh}"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
LIFECYCLE_AUTH_HEADER="Authorization: Bearer $LIFECYCLE_TOKEN"
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
TEST_SOURCE="verify-incident-lifecycle-test-${RUN_ID}"
# Section 9 drives real occurrence-identity scenarios through the
# actual webhook endpoint, which always writes source='alertmanager'
# (by design) — those rows can't carry TEST_SOURCE, so they're scoped
# by this run's own unique fingerprint instead, the same
# fingerprint-prefix pattern scripts/verify-webhook-ingestion.sh
# already uses for the identical reason. Defined here (not inline in
# section 9) so the cleanup trap below can reach it even if the script
# fails before section 9 ever runs.
AM_FP="verify-incident-lifecycle-am-${RUN_ID}"
# WM_FP: the occurrence-watermark regression scenario (sections 8-10) —
# same rationale and scoping pattern as AM_FP above, a distinct
# fingerprint so it never collides with it.
WM_FP="verify-incident-lifecycle-wm-${RUN_ID}"
CLEANUP_SQL="DELETE FROM reliability.incidents WHERE source = '$TEST_SOURCE' OR (source = 'alertmanager' AND source_fingerprint IN ('$AM_FP', '$WM_FP'));"

psql_exec() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

POSTGRES_STOPPED_BY_THIS_SCRIPT=false

besteffort_cleanup() {
  local exit_status=$?
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

insert_incident() {
  # Args: fingerprint status [resolved_at_sql_expr]
  # occurrence_starts_at (V2, NOT NULL, no column default — same
  # convention as first_seen_at/last_seen_at) is set equal to
  # first_seen_at: a row inserted directly like this has never
  # accepted a newer firing observation since creation.
  local fp="$1" st="$2" resolved_expr="${3:-NULL}"
  psql_exec -t -A -c "
    INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at, resolved_at)
    VALUES ('$TEST_SOURCE', '$fp', 'Lifecycle test incident', 'warning', '$st', now() - interval '10 minutes', now(), now() - interval '10 minutes', $resolved_expr)
    RETURNING id;
  " | head -1
}

db_occurrence_starts_at() {
  psql_exec -t -A -c "SELECT occurrence_starts_at FROM reliability.incidents WHERE id = '$1';"
}

db_status() {
  psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id = '$1';"
}

db_resolved_at() {
  psql_exec -t -A -c "SELECT resolved_at FROM reliability.incidents WHERE id = '$1';"
}

# PATCH $1=id $2=expected $3=target [$4=auth header, default lifecycle token]
# Leaves HTTP status in $PATCH_STATUS and body in $PATCH_BODY.
patch_status() {
  local id="$1" expected="$2" target="$3" auth_header="${4:-$LIFECYCLE_AUTH_HEADER}"
  local response curl_exit=0
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X PATCH \
    "$CONTROL_PLANE_URL/api/v1/incidents/$id/status" \
    -H "Content-Type: application/json" -H "$auth_header" \
    -d "{\"expected_status\":\"$expected\",\"target_status\":\"$target\"}")" || curl_exit=$?
  if [ "$curl_exit" -ne 0 ]; then
    PATCH_STATUS="000"
    PATCH_BODY=""
    return 0
  fi
  PATCH_STATUS="$(echo "$response" | tail -1)"
  PATCH_BODY="$(echo "$response" | sed '$d')"
}

post_alert() {
  # Args: alert_status fingerprint starts_at [ends_at]
  local alert_status="$1" fp="$2" starts_at="$3" ends_at="${4:-}"
  # Embedded directly into Python source below, so this must be a
  # Python literal (None), not JSON's null.
  local ends_at_json="None"
  [ -n "$ends_at" ] && ends_at_json="'$ends_at'"
  local body response curl_exit=0
  body="$(python3 -c "
import json
print(json.dumps({
    'version': '4', 'groupKey': 'test', 'status': '$alert_status', 'receiver': 'control-plane-webhook',
    'alerts': [{
        'status': '$alert_status',
        'labels': {'alertname': 'VerifyIncidentLifecycleTest', 'severity': 'critical'},
        'annotations': {'summary': 'lifecycle test occurrence'},
        'startsAt': '$starts_at',
        'endsAt': $ends_at_json,
        'fingerprint': '$fp',
    }],
}))
")"
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' -X POST "$WEBHOOK_URL" \
    -H 'Content-Type: application/json' -H "Authorization: Bearer $WEBHOOK_TOKEN" -d "$body")" || curl_exit=$?
  if [ "$curl_exit" -ne 0 ]; then
    POST_STATUS="000"
    POST_BODY=""
    return 0
  fi
  POST_STATUS="$(echo "$response" | tail -1)"
  POST_BODY="$(echo "$response" | sed '$d')"
}

# --------------------------------------------------------------------
# 1. Create a run-scoped incident; read its initial open status
# --------------------------------------------------------------------
section "1. Create a run-scoped incident; confirm initial open status"

id1="$(insert_incident "fp-progression" open)"
[ -n "$id1" ] || fail "insert for fp-progression returned no id"

detail_status="$(curl -s --connect-timeout 2 --max-time 10 -o /tmp/vil-detail.json -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$id1")"
[ "$detail_status" = "200" ] || fail "GET /api/v1/incidents/$id1 returned $detail_status"
python3 -c "
import json
body = json.load(open('/tmp/vil-detail.json'))
assert body['status'] == 'open', body
assert body['resolved_at'] is None, body
print('  initial status via HTTP matches DB: open')
"
rm -f /tmp/vil-detail.json

# --------------------------------------------------------------------
# 2. Walk every permitted transition along one real path, verifying
#    the DB after each step matches the HTTP response
# --------------------------------------------------------------------
section "2. Walk every permitted transition; verify DB matches HTTP at each step"

# open -> investigating -> remediating -> investigating -> resolved
# (resolved -> closed is done as its own explicit step below, so
# resolved_at can be captured in between — see the post-review fix
# note immediately after this loop for why that ordering matters.)
for step in "open:investigating" "investigating:remediating" "remediating:investigating" "investigating:resolved"; do
  expected="${step%%:*}"
  target="${step##*:}"
  patch_status "$id1" "$expected" "$target"
  [ "$PATCH_STATUS" = "200" ] || fail "PATCH $expected -> $target returned $PATCH_STATUS: $PATCH_BODY"
  http_status_val="$(echo "$PATCH_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  [ "$http_status_val" = "$target" ] || fail "HTTP response status=$http_status_val, expected $target"
  db_status_val="$(db_status "$id1")"
  [ "$db_status_val" = "$target" ] || fail "DB status=$db_status_val after PATCH $expected -> $target, expected $target"
  echo "  $expected -> $target: HTTP and DB both confirm '$target'"
done

# Post-review correction: this MUST be captured here, immediately after
# entering resolved and before the resolved -> closed transition below
# — capturing it only after closing (the original bug) reads the
# already-closed row twice, which can never catch a real regression
# since it is trivially comparing one value to itself.
resolved_at_after_resolve="$(db_resolved_at "$id1")"
[ -n "$resolved_at_after_resolve" ] || fail "resolved_at is empty after transitioning to resolved"
echo "  resolved_at set on entering resolved: $resolved_at_after_resolve"

patch_status "$id1" resolved closed
[ "$PATCH_STATUS" = "200" ] || fail "PATCH resolved -> closed returned $PATCH_STATUS: $PATCH_BODY"
http_status_val="$(echo "$PATCH_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
[ "$http_status_val" = "closed" ] || fail "HTTP response status=$http_status_val, expected closed"
db_status_val="$(db_status "$id1")"
[ "$db_status_val" = "closed" ] || fail "DB status=$db_status_val after PATCH resolved -> closed, expected closed"
echo "  resolved -> closed: HTTP and DB both confirm 'closed'"

resolved_at_after_close="$(db_resolved_at "$id1")"
[ "$resolved_at_after_close" = "$resolved_at_after_resolve" ] || fail "resolved_at changed across resolved -> closed: $resolved_at_after_resolve -> $resolved_at_after_close"
echo "  resolved_at preserved across resolved -> closed (closure never overwrites it)"

# --------------------------------------------------------------------
# 3. A second path: open -> acknowledged -> resolved
# --------------------------------------------------------------------
section "3. A second permitted path: open -> acknowledged -> resolved"

id2="$(insert_incident "fp-ack-path" open)"
patch_status "$id2" open acknowledged
[ "$PATCH_STATUS" = "200" ] || fail "PATCH open -> acknowledged returned $PATCH_STATUS"
patch_status "$id2" acknowledged resolved
[ "$PATCH_STATUS" = "200" ] || fail "PATCH acknowledged -> resolved returned $PATCH_STATUS"
[ "$(db_status "$id2")" = "resolved" ] || fail "fp-ack-path did not reach resolved"
echo "  open -> acknowledged -> resolved confirmed"

# --------------------------------------------------------------------
# 4. Reject forbidden transitions; row left completely unchanged
# --------------------------------------------------------------------
section "4. Reject forbidden transitions; row left unchanged"

id3="$(insert_incident "fp-forbidden" open)"
updated_at_before="$(psql_exec -t -A -c "SELECT updated_at FROM reliability.incidents WHERE id = '$id3';")"

for forbidden in "open:remediating" "open:closed" "closed:open"; do
  expected="${forbidden%%:*}"
  target="${forbidden##*:}"
  patch_status "$id3" "$expected" "$target"
  [ "$PATCH_STATUS" = "409" ] || fail "PATCH $expected -> $target returned $PATCH_STATUS, expected 409 (illegal transition)"
done
[ "$(db_status "$id3")" = "open" ] || fail "fp-forbidden's status changed despite only illegal transition attempts"
updated_at_after="$(psql_exec -t -A -c "SELECT updated_at FROM reliability.incidents WHERE id = '$id3';")"
[ "$updated_at_after" = "$updated_at_before" ] || fail "updated_at changed despite only illegal transition attempts: $updated_at_before -> $updated_at_after"
echo "  illegal transitions all returned 409; row (including updated_at) completely unchanged"

# --------------------------------------------------------------------
# 5. Reject a stale expected_status
# --------------------------------------------------------------------
section "5. Reject a stale expected_status"

id4="$(insert_incident "fp-stale-expected" open)"
patch_status "$id4" open acknowledged
[ "$PATCH_STATUS" = "200" ] || fail "setup PATCH open -> acknowledged failed: $PATCH_STATUS"

patch_status "$id4" open investigating  # stale: actual is now acknowledged
[ "$PATCH_STATUS" = "409" ] || fail "stale expected_status (open, actual acknowledged) returned $PATCH_STATUS, expected 409"
[ "$(db_status "$id4")" = "acknowledged" ] || fail "fp-stale-expected's status changed despite a stale PATCH attempt"
echo "  stale expected_status correctly rejected with 409; row unchanged"

# --------------------------------------------------------------------
# 6. Access control via the real HTTP route
# --------------------------------------------------------------------
section "6. Access control"

status_noauth="$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/$id4/status" \
  -H 'Content-Type: application/json' -d '{"expected_status":"acknowledged","target_status":"resolved"}')"
[ "$status_noauth" = "401" ] || fail "PATCH with no Authorization header returned $status_noauth, expected 401"

patch_status "$id4" acknowledged resolved "Authorization: Bearer wrong-token-value"
[ "$PATCH_STATUS" = "401" ] || fail "PATCH with an incorrect token returned $PATCH_STATUS, expected 401"

patch_status "$id4" acknowledged resolved "Authorization: Bearer $WEBHOOK_TOKEN"
[ "$PATCH_STATUS" = "401" ] || fail "PATCH using the WEBHOOK token returned $PATCH_STATUS, expected 401 — the lifecycle endpoint must not accept it"

[ "$(db_status "$id4")" = "acknowledged" ] || fail "fp-stale-expected's status changed despite only unauthenticated/misauthenticated attempts"
echo "  missing token, wrong token, and the (distinct) webhook token all correctly rejected with 401; row unchanged"

# --------------------------------------------------------------------
# 7. Invalid UUID / missing incident / invalid status value
# --------------------------------------------------------------------
section "7. Invalid UUID, missing incident, invalid status value"

status_bad_uuid="$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/not-a-uuid/status" \
  -H 'Content-Type: application/json' -H "$LIFECYCLE_AUTH_HEADER" -d '{"expected_status":"open","target_status":"acknowledged"}')"
[ "$status_bad_uuid" = "422" ] || fail "malformed UUID path returned $status_bad_uuid, expected 422"

random_uuid="$(python3 -c 'import uuid; print(uuid.uuid4())')"
patch_status "$random_uuid" open acknowledged
[ "$PATCH_STATUS" = "404" ] || fail "PATCH for a well-formed but nonexistent UUID returned $PATCH_STATUS, expected 404"

status_bad_target="$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/$id4/status" \
  -H 'Content-Type: application/json' -H "$LIFECYCLE_AUTH_HEADER" -d '{"expected_status":"acknowledged","target_status":"bogus"}')"
[ "$status_bad_target" = "422" ] || fail "invalid target_status returned $status_bad_target, expected 422"
echo "  malformed UUID -> 422, nonexistent UUID -> 404, invalid target_status -> 422"

# --------------------------------------------------------------------
# 8. Occurrence watermark setup: a newer firing into a STILL-ACTIVE
#    incident updates it in place and advances the watermark — set up
#    here, before the restart in section 9, so that restart can also
#    prove the watermark itself survives it without a second, separate
#    restart.
# --------------------------------------------------------------------
section "8. Occurrence watermark: a newer firing into a still-active incident updates it and advances the watermark"

wm_a_start="2026-02-01T10:00:00Z"
wm_a_end="2026-02-01T10:05:00Z"
wm_b_start="2026-02-01T11:00:00Z"
wm_b_end="2026-02-01T11:05:00Z"

post_alert firing "$WM_FP" "$wm_a_start"
[ "$POST_STATUS" = "200" ] || fail "firing A (watermark scenario) returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==1, b"
wm_x_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$WM_FP';" | head -1)"
[ -n "$wm_x_id" ] || fail "no row found for watermark occurrence A"

wm_first_seen_before="$(psql_exec -t -A -c "SELECT first_seen_at FROM reliability.incidents WHERE id='$wm_x_id';")"
post_alert firing "$WM_FP" "$wm_b_start"
[ "$POST_STATUS" = "200" ] || fail "firing B into still-active X returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_updated']==1 and b['incidents_created']==0, b"
row_count_wm="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$WM_FP';")"
[ "$row_count_wm" = "1" ] || fail "firing B into still-active X incorrectly created a second row (found $row_count_wm)"
wm_first_seen_after="$(psql_exec -t -A -c "SELECT first_seen_at FROM reliability.incidents WHERE id='$wm_x_id';")"
[ "$wm_first_seen_after" = "$wm_first_seen_before" ] || fail "first_seen_at changed when B updated still-active X: $wm_first_seen_before -> $wm_first_seen_after"
wm_occurrence_starts_at_before_restart="$(db_occurrence_starts_at "$wm_x_id")"
echo "  B's newer firing updated the still-active incident in place (1 row); first_seen_at preserved; watermark advanced to $wm_occurrence_starts_at_before_restart"

# --------------------------------------------------------------------
# 9. Durability: status, resolved_at, AND the occurrence watermark all
#    survive a real PostgreSQL restart
# --------------------------------------------------------------------
section "9. Status, resolved_at, and the occurrence watermark all survive a real PostgreSQL restart"

patch_status "$id4" acknowledged resolved
[ "$PATCH_STATUS" = "200" ] || fail "setup PATCH acknowledged -> resolved failed: $PATCH_STATUS"
resolved_at_before_restart="$(db_resolved_at "$id4")"
[ -n "$resolved_at_before_restart" ] || fail "resolved_at empty before restart"

docker compose restart postgres >/dev/null
postgres_healthy_after_restart=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  [ "$health" = "healthy" ] && postgres_healthy_after_restart=true && break
  sleep 3
done
[ "$postgres_healthy_after_restart" = true ] || fail "postgres did not become healthy again after restart"

ready_after_restart=false
for i in $(seq 1 20); do
  status="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/health/ready" || echo 000)"
  [ "$status" = "200" ] && ready_after_restart=true && break
  sleep 3
done
[ "$ready_after_restart" = true ] || fail "control-plane readiness never recovered to 200 after the postgres restart"

status_after_restart="$(db_status "$id4")"
resolved_at_after_restart="$(db_resolved_at "$id4")"
[ "$status_after_restart" = "resolved" ] || fail "status did not survive restart: $status_after_restart"
[ "$resolved_at_after_restart" = "$resolved_at_before_restart" ] || fail "resolved_at did not survive restart unchanged: $resolved_at_before_restart -> $resolved_at_after_restart"

wm_occurrence_starts_at_after_restart="$(db_occurrence_starts_at "$wm_x_id")"
[ "$wm_occurrence_starts_at_after_restart" = "$wm_occurrence_starts_at_before_restart" ] || fail "occurrence watermark did not survive restart unchanged: $wm_occurrence_starts_at_before_restart -> $wm_occurrence_starts_at_after_restart"

detail_status_after_restart="$(curl -s --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$id4")"
[ "$detail_status_after_restart" = "200" ] || fail "GET /api/v1/incidents/$id4 after restart returned $detail_status_after_restart"
echo "  status ('resolved'), resolved_at, and the occurrence watermark ($wm_occurrence_starts_at_after_restart) all survived a real PostgreSQL restart"

# --------------------------------------------------------------------
# 10. Occurrence watermark continued: a delayed resolved notification
#     for the SUPERSEDED occurrence A must be rejected (the exact
#     regression independent review found — comparing against the
#     immutable first_seen_at instead of the watermark would wrongly
#     resolve this incident here); B then resolves correctly using its
#     own startsAt; a delayed DUPLICATE firing replay of B, arriving
#     after that resolution, must not create a new incident (the other
#     half of the same regression); and a genuinely new, later
#     occurrence C must still create one, preserving history.
# --------------------------------------------------------------------
section "10. Occurrence watermark: delayed resolved-A rejected, B resolves via its own startsAt, delayed duplicate firing-B after resolution ignored, genuine occurrence C preserves history"

post_alert resolved "$WM_FP" "$wm_a_start" "$wm_a_end"
[ "$POST_STATUS" = "200" ] || fail "delayed resolved-A (watermark scenario) returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==0 and b['incidents_ignored']==1, b"
[ "$(db_status "$wm_x_id")" != "resolved" ] || fail "a delayed resolved notification for the superseded occurrence A incorrectly resolved X (X already represents B, not A) -- THIS IS THE REGRESSION"
echo "  delayed resolved-A notification correctly rejected by the watermark (X still represents B, not A); X remains active"

post_alert resolved "$WM_FP" "$wm_b_start" "$wm_b_end"
[ "$POST_STATUS" = "200" ] || fail "resolving B (its own startsAt) returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==1, b"
[ "$(db_status "$wm_x_id")" = "resolved" ] || fail "B's own resolved notification did not resolve X"
echo "  B resolved X using its own startsAt (matching the watermark exactly)"

post_alert firing "$WM_FP" "$wm_b_start"
[ "$POST_STATUS" = "200" ] || fail "delayed duplicate firing-B replay (watermark scenario) returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==0 and b['incidents_ignored']==1, b"
row_count_wm_after="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$WM_FP';")"
[ "$row_count_wm_after" = "1" ] || fail "a delayed duplicate firing replay of B incorrectly created a new incident (expected still 1 row, found $row_count_wm_after) -- THIS IS THE REGRESSION"
echo "  delayed duplicate firing-B replay (after resolution) correctly rejected by the watermark; still exactly 1 historical row"

wm_c_start="2026-02-01T12:00:00Z"
post_alert firing "$WM_FP" "$wm_c_start"
[ "$POST_STATUS" = "200" ] || fail "firing genuinely new occurrence C returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==1, b"
row_count_wm_final="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$WM_FP';")"
[ "$row_count_wm_final" = "2" ] || fail "genuine new occurrence C did not create a distinct second row (found $row_count_wm_final)"
[ "$(db_status "$wm_x_id")" = "resolved" ] || fail "X's historical resolved status was disturbed by C's creation"
echo "  genuinely new occurrence C created a distinct incident; X's history preserved"

# --------------------------------------------------------------------
# 11. Occurrence A resolution, a subsequent legitimate occurrence B,
#     and a delayed notification for A that must not corrupt B
# --------------------------------------------------------------------
section "11. Occurrence identity: resolve A, recur as B, delayed A notification must not corrupt B"

occ_fp="fp-occurrence-${RUN_ID}"
occ_a_start="2026-01-01T10:00:00Z"
occ_a_end="2026-01-01T10:30:00Z"
occ_b_start="2026-01-02T09:00:00Z"

# The webhook always writes source='alertmanager' (by design — see
# ingestion/mapping.py), so this scenario is driven through the real
# webhook end-to-end and cleaned up via AM_FP (defined up front,
# alongside TEST_SOURCE, so the cleanup trap can always reach it).

post_alert firing "$AM_FP" "$occ_a_start"
[ "$POST_STATUS" = "200" ] || fail "firing occurrence A returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==1, b"

occ_a_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$AM_FP';" | head -1)"
[ -n "$occ_a_id" ] || fail "no row found for occurrence A"

post_alert resolved "$AM_FP" "$occ_a_start" "$occ_a_end"
[ "$POST_STATUS" = "200" ] || fail "resolving occurrence A returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==1, b"
[ "$(psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id='$occ_a_id';")" = "resolved" ] || fail "occurrence A did not resolve"

post_alert firing "$AM_FP" "$occ_b_start"
[ "$POST_STATUS" = "200" ] || fail "firing occurrence B (genuine recurrence) returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==1, b"
occ_b_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$AM_FP' AND status NOT IN ('resolved','closed');" | head -1)"
[ -n "$occ_b_id" ] && [ "$occ_b_id" != "$occ_a_id" ] || fail "occurrence B was not created as a distinct new row"

row_count_am="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$AM_FP';")"
[ "$row_count_am" = "2" ] || fail "expected exactly 2 rows (resolved A + active B), found $row_count_am"
echo "  occurrence A resolved; genuine recurrence B created as a distinct row; both preserved ($occ_a_id resolved, $occ_b_id active)"

# A delayed resolved notification for the OLD occurrence A must not
# touch the new, active occurrence B.
post_alert resolved "$AM_FP" "$occ_a_start" "$occ_a_end"
[ "$POST_STATUS" = "200" ] || fail "delayed resolved-A notification returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==0 and b['incidents_ignored']==1, b"
[ "$(psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id='$occ_b_id';")" != "resolved" ] || fail "a delayed resolved notification for A incorrectly resolved B"
echo "  delayed resolved-A notification safely ignored; B remains active and untouched"

# A delayed firing replay of the already-resolved A must not recreate
# or reopen it.
post_alert firing "$AM_FP" "$occ_a_start"
[ "$POST_STATUS" = "200" ] || fail "delayed firing-A replay returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==0 and b['incidents_ignored']==1, b"
row_count_am_after="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$AM_FP';")"
[ "$row_count_am_after" = "2" ] || fail "a delayed firing replay of A changed the row count (expected still 2, found $row_count_am_after)"
echo "  delayed firing-A replay safely ignored; still exactly 2 historical rows"

# --------------------------------------------------------------------
# 12. Concurrent transition attempts: exactly one winner
# --------------------------------------------------------------------
section "12. Concurrent transition attempts from the same expected_status: exactly one winner"

id5="$(insert_incident "fp-concurrency" open)"
concurrency_tmpdir="$(mktemp -d)"
for i in $(seq 1 10); do
  curl -s -o "$concurrency_tmpdir/resp_$i.json" -w '%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/$id5/status" \
    -H "Content-Type: application/json" -H "$LIFECYCLE_AUTH_HEADER" \
    -d '{"expected_status":"open","target_status":"acknowledged"}' > "$concurrency_tmpdir/code_$i.txt" 2>&1 &
done
wait

success_count=0
conflict_count=0
other_count=0
for i in $(seq 1 10); do
  code="$(cat "$concurrency_tmpdir/code_$i.txt")"
  case "$code" in
    200) success_count=$((success_count + 1)) ;;
    409) conflict_count=$((conflict_count + 1)) ;;
    *) other_count=$((other_count + 1)) ;;
  esac
done
rm -rf "$concurrency_tmpdir"

[ "$success_count" = "1" ] || fail "expected exactly 1 of 10 concurrent same-expected-status PATCH requests to succeed, got $success_count"
[ "$conflict_count" = "9" ] || fail "expected exactly 9 of 10 concurrent requests to be rejected as stale (409), got $conflict_count"
[ "$other_count" = "0" ] || fail "expected zero unexpected response codes among the 10 concurrent requests, got $other_count"
[ "$(db_status "$id5")" = "acknowledged" ] || fail "final status after the concurrency race is not 'acknowledged'"
echo "  10 concurrent requests from the same expected_status: exactly 1 succeeded (200), 9 correctly rejected as stale (409), final state consistent"

# --------------------------------------------------------------------
# 13. Historical rows remain intact throughout
# --------------------------------------------------------------------
section "13. Historical rows remain intact"

final_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = '$TEST_SOURCE' OR (source='alertmanager' AND source_fingerprint IN ('$AM_FP', '$WM_FP'));")"
# id1 (progression), id2 (ack path), id3 (forbidden), id4 (stale/access/restart),
# id5 (concurrency) = 5 TEST_SOURCE rows, plus 2 alertmanager-sourced AM_FP
# occurrence rows (A resolved + B active) plus 2 alertmanager-sourced
# WM_FP watermark rows (X resolved + C active) = 9.
[ "$final_count" = "9" ] || fail "expected exactly 9 total rows across this run (5 lifecycle + 2 occurrence + 2 watermark), found $final_count"
echo "  all 9 rows created by this run are still present and accounted for (no row silently lost)"

# --------------------------------------------------------------------
# 14. Clean up ONLY this execution's test-created rows
# --------------------------------------------------------------------
section "14. Clean up only this execution's test-created rows"

psql_exec -c "$CLEANUP_SQL"
remaining="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = '$TEST_SOURCE' OR (source='alertmanager' AND source_fingerprint IN ('$AM_FP', '$WM_FP'));")"
[ "$remaining" = "0" ] || fail "cleanup did not remove all of this run's rows (still present: $remaining)"
echo "  cleaned up: 9 -> 0 rows for this run"
trap - EXIT

echo ""
echo "SUCCESS: Phase 3D incident lifecycle verification passed (real PostgreSQL, real HTTP API, real concurrency, real restart durability, real occurrence-identity handling)."
