#!/usr/bin/env bash
#
# verify-incident-audit.sh — Phase 3E real PostgreSQL incident audit
# trail acceptance.
#
# Proves, against the real running service and real PostgreSQL:
#   - the V3/V4 schema itself (reliability.incident_events — columns,
#     CHECK constraints, the supporting index, and append-only
#     enforcement covering UPDATE, DELETE, AND TRUNCATE — the last of
#     which bypasses row-level triggers entirely and needs its own
#     dedicated BEFORE TRUNCATE, FOR EACH STATEMENT trigger, added by
#     V4__harden_incident_audit.sql);
#   - occurred_at's column default is clock_timestamp() (genuine
#     insertion time), not now()/transaction-start time;
#   - every accepted creation/observation/operator-transition/
#     automatic-resolution produces exactly the expected event,
#     correctly attributed, and the incident's own current state
#     matches its audit timeline's last event;
#   - every rejected/ignored/no-op operation adds nothing;
#   - a real transaction rollback when an audit insert fails also
#     rolls back the incident mutation in the SAME transaction (not
#     merely designed to, demonstrated against real PostgreSQL);
#   - concurrent operator PATCH attempts produce exactly one event
#     (the winner's), never one per loser;
#   - the audit trail survives a real PostgreSQL restart;
#   - a pre-V3-style incident (inserted directly, never touched by
#     the application) legitimately has an empty audit timeline — not
#     an error, and not retroactively fabricated;
#   - an incident with more than 20 audit events correctly paginates,
#     with its resolving event genuinely beyond the default first page.
#
# Post-review-pattern cleanup, established by Phase 3E's own append-
# only/ON DELETE RESTRICT design (see
# database/migrations/V3__create_incident_audit.sql and
# docs/architecture/phase-3e-incident-audit.md): every incident this
# script mutates after creation ends up with real audit history and
# can therefore never be deleted. This script deletes nothing at all;
# it creates run-scoped rows (scoped by a UUID unique to this
# execution), confirms their exact expected final state and exact
# expected audit trail, and leaves them in place permanently — the
# same "retain real state, never delete" precedent already established
# for the real Collector-outage test's own ingested incidents, and
# (as of this phase) scripts/verify-webhook-ingestion.sh and
# scripts/verify-incident-lifecycle.sh's own test rows.
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
TEST_SOURCE="verify-incident-audit-test-${RUN_ID}"
AM_FP="verify-incident-audit-am-${RUN_ID}"

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
  # No cleanup DELETE — see the module docstring above. Nothing this
  # script creates is ever deleted, complete run or partial failure
  # alike.
  exit "$exit_status"
}
trap besteffort_cleanup EXIT

insert_incident() {
  # Args: fingerprint status. Direct SQL, bypassing the application
  # entirely — used only for section 9's "pre-V3-style incident" case
  # and as plain setup data elsewhere; never produces an audit event
  # by construction.
  local fp="$1" st="$2"
  psql_exec -t -A -c "
    INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
    VALUES ('$TEST_SOURCE', '$fp', 'Audit test incident', 'warning', '$st', now() - interval '10 minutes', now(), now() - interval '10 minutes')
    RETURNING id;
  " | sed -n '1p'
}

db_status() {
  psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id = '$1';"
}

events_count_for() {
  psql_exec -t -A -c "SELECT count(*) FROM reliability.incident_events WHERE incident_id = '$1';"
}

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

get_events() {
  local id="$1"
  curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$id/events"
}

post_alert() {
  local alert_status="$1" fp="$2" starts_at="$3" ends_at="${4:-}"
  local ends_at_json="None"
  [ -n "$ends_at" ] && ends_at_json="'$ends_at'"
  local body response curl_exit=0
  body="$(python3 -c "
import json
print(json.dumps({
    'version': '4', 'groupKey': 'test', 'status': '$alert_status', 'receiver': 'control-plane-webhook',
    'alerts': [{
        'status': '$alert_status',
        'labels': {'alertname': 'VerifyIncidentAuditTest', 'severity': 'critical'},
        'annotations': {'summary': 'audit test occurrence'},
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
# 1. V3 schema: columns, constraints, index, and append-only triggers
# --------------------------------------------------------------------
section "1. V3 schema: table, constraints, index, append-only triggers"

table_exists="$(psql_exec -t -A -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='reliability' AND table_name='incident_events');")"
[ "$table_exists" = "t" ] || fail "reliability.incident_events does not exist after migration"

index_exists="$(psql_exec -t -A -c "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='reliability' AND tablename='incident_events' AND indexname='incident_events_incident_id_occurred_at_idx');")"
[ "$index_exists" = "t" ] || fail "incident_events_incident_id_occurred_at_idx does not exist"

fk_restrict="$(psql_exec -t -A -c "
  SELECT confdeltype FROM pg_constraint WHERE conname = 'incident_events_incident_id_fkey';
")"
[ "$fk_restrict" = "r" ] || fail "incident_events_incident_id_fkey is not ON DELETE RESTRICT (confdeltype=$fk_restrict)"
echo "  table, index, and ON DELETE RESTRICT foreign key all present"

seed_id="$(insert_incident "fp-audit-schema" open)"
seed_event_id="$(psql_exec -t -A -c "
  INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, previous_status, new_status, metadata)
  VALUES ('$seed_id', 'created', 'alertmanager', NULL, 'open', '{}'::jsonb)
  RETURNING id;
" | sed -n '1p')"
[ -n "$seed_event_id" ] || fail "a valid, directly-inserted audit event was unexpectedly rejected"

update_blocked="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "UPDATE reliability.incident_events SET new_status = 'closed' WHERE id = '$seed_event_id';" 2>&1 | grep -c "append-only" || true)"
[ "$update_blocked" -ge "1" ] || fail "a direct UPDATE on reliability.incident_events was NOT blocked — append-only trigger is not working"
echo "  direct UPDATE on incident_events correctly blocked by the append-only trigger"

delete_blocked="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DELETE FROM reliability.incident_events WHERE id = '$seed_event_id';" 2>&1 | grep -c "append-only" || true)"
[ "$delete_blocked" -ge "1" ] || fail "a direct DELETE on reliability.incident_events was NOT blocked — append-only trigger is not working"
echo "  direct DELETE on incident_events correctly blocked by the append-only trigger"

# Post-review correction: TRUNCATE bypasses row-level BEFORE
# UPDATE/DELETE triggers entirely (it never fires row-level triggers
# at all — that's exactly why it's fast). V4 adds a dedicated
# BEFORE TRUNCATE, FOR EACH STATEMENT trigger; this must be proven too,
# not just UPDATE/DELETE.
#
# IMPORTANT safety property: this attempt is wrapped in an explicit
# BEGIN ... ROLLBACK (never COMMIT) specifically so that even if the
# guard trigger were accidentally missing or broken — i.e. even if
# TRUNCATE actually succeeded inside this transaction — the ROLLBACK
# immediately after would still undo it before anything could ever be
# persisted. This script must never be capable of actually destroying
# this (or any) database's real incident_events history, regardless of
# whether the fix it is testing for works.
total_events_before_truncate_test="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incident_events;")"
set +e
truncate_output="$(docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL' 2>&1
BEGIN;
TRUNCATE reliability.incident_events;
ROLLBACK;
SQL
)"
truncate_exit=$?
set -e
[ "$truncate_exit" -ne 0 ] || fail "a direct TRUNCATE on reliability.incident_events was NOT rejected — append-only enforcement is incomplete (this would have deleted ALL audit history)"
echo "$truncate_output" | grep -q "append-only" || fail "TRUNCATE failed for an unexpected reason (not the append-only guard): $truncate_output"
total_events_after_truncate_test="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incident_events;")"
[ "$total_events_after_truncate_test" = "$total_events_before_truncate_test" ] || fail "the TOTAL incident_events row count changed across the TRUNCATE test ($total_events_before_truncate_test -> $total_events_after_truncate_test) — real audit history may have been lost"
echo "  direct TRUNCATE on incident_events correctly blocked by the append-only trigger; all $total_events_after_truncate_test existing rows (across the whole table, not just this run's) survive intact"

# Post-review correction: occurred_at's column DEFAULT must be
# clock_timestamp() (genuine insertion-time), not now()/CURRENT_TIMESTAMP/
# transaction_timestamp() (transaction-start-time, which is wrong under
# concurrent writes — see database/migrations/V4__harden_incident_audit.sql
# and docs/architecture/phase-3e-incident-audit.md for the full
# reasoning). Checked directly against the real column metadata, not
# inferred from timing behavior (which would be flaky to assert on).
occurred_at_default="$(psql_exec -t -A -c "
  SELECT column_default FROM information_schema.columns
  WHERE table_schema = 'reliability' AND table_name = 'incident_events' AND column_name = 'occurred_at';
")"
[ "$occurred_at_default" = "clock_timestamp()" ] || fail "reliability.incident_events.occurred_at's default is '$occurred_at_default', expected 'clock_timestamp()'"
echo "  occurred_at's column default is clock_timestamp() (genuine insertion time, not transaction-start time)"

delete_incident_blocked="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DELETE FROM reliability.incidents WHERE id = '$seed_id';" 2>&1 | grep -c "violates" || true)"
[ "$delete_incident_blocked" -ge "1" ] || fail "deleting an incident with recorded audit history was NOT blocked by ON DELETE RESTRICT"
echo "  deleting an incident with recorded audit history correctly blocked (ON DELETE RESTRICT)"

bad_metadata_rejected="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, previous_status, new_status, metadata)
  VALUES ('$seed_id', 'created', 'alertmanager', NULL, 'open', '[1,2,3]'::jsonb);
" 2>&1 | grep -c "incident_events_metadata_check" || true)"
[ "$bad_metadata_rejected" -ge "1" ] || fail "a non-object metadata value (a JSON array) was NOT rejected by incident_events_metadata_check"
echo "  non-object metadata correctly rejected (incident_events_metadata_check)"

bad_shape_rejected="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, previous_status, new_status, metadata)
  VALUES ('$seed_id', 'created', 'alertmanager', 'acknowledged', 'open', '{}'::jsonb);
" 2>&1 | grep -c "incident_events_created_shape" || true)"
[ "$bad_shape_rejected" -ge "1" ] || fail "a 'created' event with a non-NULL previous_status was NOT rejected by incident_events_created_shape"
echo "  'created' event with a non-NULL previous_status correctly rejected (incident_events_created_shape)"

# --------------------------------------------------------------------
# 2. Successful creation: incident state matches its audit timeline
# --------------------------------------------------------------------
section "2. Successful creation: incident state matches its audit timeline"

occ_a_start="2026-04-01T10:00:00Z"
post_alert firing "$AM_FP" "$occ_a_start"
[ "$POST_STATUS" = "200" ] || fail "firing webhook returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_created']==1, b"

am_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$AM_FP';" | sed -n '1p')"
[ -n "$am_id" ] || fail "no row found for $AM_FP"

response="$(get_events "$am_id")"
events_status="$(echo "$response" | tail -1)"
events_body="$(echo "$response" | sed '$d')"
[ "$events_status" = "200" ] || fail "GET events for $am_id returned $events_status"
echo "$events_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['total'] == 1, body
e = body['items'][0]
assert e['event_type'] == 'created', e
assert e['actor_type'] == 'alertmanager', e
assert e['previous_status'] is None, e
assert e['new_status'] == 'open', e
assert set(e['metadata']) <= {'source_fingerprint', 'observed_starts_at'}, e
print('  creation event OK:', e['event_type'], e['actor_type'], e['previous_status'], '->', e['new_status'])
"
[ "$(db_status "$am_id")" = "open" ] || fail "incident status does not match its own creation event's new_status"
echo "  incident's real status ('open') matches its audit timeline's only event"

# --------------------------------------------------------------------
# 3. Accepted observation: incident state matches its audit timeline
# --------------------------------------------------------------------
section "3. Accepted observation: incident state matches its audit timeline"

occ_b_start="2026-04-01T11:00:00Z"
post_alert firing "$AM_FP" "$occ_b_start"
[ "$POST_STATUS" = "200" ] || fail "second (newer) firing returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_updated']==1 and b['incidents_created']==0, b"

response="$(get_events "$am_id")"
events_body="$(echo "$response" | sed '$d')"
echo "$events_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['total'] == 2, body
created, observed = body['items']
assert created['event_type'] == 'created', created
assert observed['event_type'] == 'observed', observed
assert observed['actor_type'] == 'alertmanager', observed
assert observed['previous_status'] == observed['new_status'] == 'open', observed
print('  observation event OK, correctly ordered after creation:', [e['event_type'] for e in body['items']])
"

# --------------------------------------------------------------------
# 4. Operator PATCH: incident state matches its audit timeline
# --------------------------------------------------------------------
section "4. Operator PATCH transition: incident state matches its audit timeline"

patch_id="$(insert_incident "fp-audit-patch" open)"
[ "$(events_count_for "$patch_id")" = "0" ] || fail "a freshly, directly-inserted incident already has audit events"

patch_status "$patch_id" open acknowledged
[ "$PATCH_STATUS" = "200" ] || fail "PATCH open -> acknowledged returned $PATCH_STATUS: $PATCH_BODY"

response="$(get_events "$patch_id")"
events_body="$(echo "$response" | sed '$d')"
echo "$events_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['total'] == 1, body
e = body['items'][0]
assert e['event_type'] == 'status_transition', e
assert e['actor_type'] == 'operator', e
assert e['previous_status'] == 'open', e
assert e['new_status'] == 'acknowledged', e
print('  operator transition event OK:', e['actor_type'], e['previous_status'], '->', e['new_status'])
"
[ "$(db_status "$patch_id")" = "acknowledged" ] || fail "incident status does not match its own transition event's new_status"

# --------------------------------------------------------------------
# 5. Automatic resolution: incident state matches its audit timeline
# --------------------------------------------------------------------
section "5. Automatic resolution: incident state matches its audit timeline"

occ_b_end="2026-04-01T11:30:00Z"
post_alert resolved "$AM_FP" "$occ_b_start" "$occ_b_end"
[ "$POST_STATUS" = "200" ] || fail "resolving webhook returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==1, b"

response="$(get_events "$am_id")"
events_body="$(echo "$response" | sed '$d')"
echo "$events_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['total'] == 3, body
resolution = body['items'][2]
assert resolution['event_type'] == 'status_transition', resolution
assert resolution['actor_type'] == 'alertmanager', resolution
assert resolution['previous_status'] == 'open', resolution
assert resolution['new_status'] == 'resolved', resolution
assert resolution['metadata'].get('resolution_source') == 'alertmanager_webhook', resolution
print('  automatic resolution event OK:', resolution['actor_type'], resolution['previous_status'], '->', resolution['new_status'])
"
[ "$(db_status "$am_id")" = "resolved" ] || fail "incident status does not match its own resolution event's new_status"
echo "  incident's real final status ('resolved') matches its audit timeline's last event"

# --------------------------------------------------------------------
# 6. Rejected/ignored/no-op operations add nothing
# --------------------------------------------------------------------
section "6. Rejected/ignored/no-op operations add nothing to the audit trail"

noop_id="$(insert_incident "fp-audit-noop" open)"

patch_status "$noop_id" open remediating  # illegal transition
[ "$PATCH_STATUS" = "409" ] || fail "illegal transition did not return 409"
[ "$(events_count_for "$noop_id")" = "0" ] || fail "an illegal (409) transition recorded an audit event"

patch_status "$noop_id" acknowledged investigating  # stale expected_status
[ "$PATCH_STATUS" = "409" ] || fail "stale expected_status did not return 409"
[ "$(events_count_for "$noop_id")" = "0" ] || fail "a stale-expected_status (409) attempt recorded an audit event"

patch_status "$noop_id" open open  # same-status no-op
[ "$PATCH_STATUS" = "200" ] || fail "same-status no-op did not return 200"
[ "$(events_count_for "$noop_id")" = "0" ] || fail "a same-status no-op recorded an audit event"
echo "  illegal transition (409), stale expected_status (409), and same-status no-op (200) all recorded zero events"

stale_fp="verify-incident-audit-stale-${RUN_ID}"
post_alert firing "$stale_fp" "2026-04-01T09:00:00Z"
[ "$POST_STATUS" = "200" ] || fail "setup firing for stale-replay test returned $POST_STATUS"
stale_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$stale_fp';" | sed -n '1p')"
post_alert firing "$stale_fp" "2026-04-01T08:00:00Z"  # strictly OLDER -> ignored
[ "$POST_STATUS" = "200" ] || fail "stale firing replay returned $POST_STATUS"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_ignored']==1, b"
[ "$(events_count_for "$stale_id")" = "1" ] || fail "a stale/ignored firing replay added an audit event (expected still exactly 1, the original creation)"
echo "  a stale/ignored firing replay recorded zero additional events"

resolved_no_active_fp="verify-incident-audit-no-active-${RUN_ID}"
post_alert resolved "$resolved_no_active_fp" "2026-04-01T09:00:00Z" "2026-04-01T09:30:00Z"
[ "$POST_STATUS" = "200" ] || fail "resolved-with-no-matching-active-incident returned $POST_STATUS"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_ignored']==1, b"
no_active_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$resolved_no_active_fp';")"
[ "$no_active_count" = "0" ] || fail "a resolved notification with no matching active incident unexpectedly created a row"
echo "  an ignored resolved notification (no matching active incident) created no incident and no event"

dup_resolve_fp="verify-incident-audit-dup-resolve-${RUN_ID}"
post_alert firing "$dup_resolve_fp" "2026-04-01T09:00:00Z"
[ "$POST_STATUS" = "200" ] || fail "setup firing for duplicate-resolution test returned $POST_STATUS"
dup_resolve_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$dup_resolve_fp';" | sed -n '1p')"
post_alert resolved "$dup_resolve_fp" "2026-04-01T09:00:00Z" "2026-04-01T09:30:00Z"
[ "$POST_STATUS" = "200" ] || fail "first resolution returned $POST_STATUS"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==1, b"
[ "$(events_count_for "$dup_resolve_id")" = "2" ] || fail "expected exactly 2 events (created + resolved) after the first resolution"
post_alert resolved "$dup_resolve_fp" "2026-04-01T09:00:00Z" "2026-04-01T09:30:00Z"
[ "$POST_STATUS" = "200" ] || fail "duplicate resolution returned $POST_STATUS"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_ignored']==1 and b['incidents_resolved']==0, b"
[ "$(events_count_for "$dup_resolve_id")" = "2" ] || fail "a duplicate resolved delivery after success recorded a second status_transition event"
echo "  a duplicate resolved delivery after successful resolution recorded zero additional events"

# --------------------------------------------------------------------
# 7. Real transaction rollback when an audit insertion fails
# --------------------------------------------------------------------
section "7. Real transaction rollback: an audit-insertion failure rolls back the incident mutation too"

rollback_id="$(insert_incident "fp-audit-rollback" open)"
rollback_status_before="$(db_status "$rollback_id")"
rollback_events_before="$(events_count_for "$rollback_id")"

# A deliberately invalid audit event (previous_status must be NULL for
# a 'created' event — incident_events_created_shape) inside the SAME
# transaction as a real incident UPDATE, issued as ONE multi-statement
# psql invocation under ON_ERROR_STOP=1 so the whole block aborts (and
# therefore rolls back, since COMMIT is never reached) the instant the
# INSERT violates its CHECK constraint — proving, against real
# PostgreSQL, that an audit-insert failure takes the incident mutation
# down with it, not merely that the application is designed to behave
# this way.
set +e
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
BEGIN;
UPDATE reliability.incidents SET status = 'acknowledged' WHERE id = '$rollback_id' AND status = 'open';
INSERT INTO reliability.incident_events (incident_id, event_type, actor_type, previous_status, new_status, metadata)
VALUES ('$rollback_id', 'created', 'alertmanager', 'open', 'open', '{}'::jsonb);
COMMIT;
SQL
rollback_block_exit=$?
set -e
[ "$rollback_block_exit" -ne 0 ] || fail "the deliberately invalid audit insert was NOT rejected — rollback could not be tested"

rollback_status_after="$(db_status "$rollback_id")"
rollback_events_after="$(events_count_for "$rollback_id")"
[ "$rollback_status_after" = "$rollback_status_before" ] || fail "incident status changed ($rollback_status_before -> $rollback_status_after) despite the audit insert in the same transaction failing"
[ "$rollback_events_after" = "$rollback_events_before" ] || fail "an audit event was recorded despite the same transaction's own INSERT failing its CHECK constraint"
echo "  real transaction rollback confirmed: the incident UPDATE and the failing audit INSERT, in the same transaction, rolled back together"

# --------------------------------------------------------------------
# 8. Concurrent PATCH operations create only the winner's event
# --------------------------------------------------------------------
section "8. Concurrent PATCH operations create only the winner's event"

concurrency_id="$(insert_incident "fp-audit-concurrency" open)"
concurrency_tmpdir="$(mktemp -d)"
for i in $(seq 1 10); do
  curl -s -o /dev/null -w '%{http_code}' -X PATCH "$CONTROL_PLANE_URL/api/v1/incidents/$concurrency_id/status" \
    -H "Content-Type: application/json" -H "$LIFECYCLE_AUTH_HEADER" \
    -d '{"expected_status":"open","target_status":"acknowledged"}' > "$concurrency_tmpdir/code_$i.txt" 2>&1 &
done
wait

success_count=0
for i in $(seq 1 10); do
  code="$(cat "$concurrency_tmpdir/code_$i.txt")"
  [ "$code" = "200" ] && success_count=$((success_count + 1))
done
rm -rf "$concurrency_tmpdir"
[ "$success_count" = "1" ] || fail "expected exactly 1 of 10 concurrent PATCH requests to succeed, got $success_count"

concurrency_events="$(events_count_for "$concurrency_id")"
[ "$concurrency_events" = "1" ] || fail "expected exactly 1 audit event after 10 concurrent PATCH attempts (one winner), found $concurrency_events"
echo "  10 concurrent PATCH requests: exactly 1 succeeded, and exactly 1 audit event was recorded (never one per loser)"

# --------------------------------------------------------------------
# 9. Audit records persist across a real PostgreSQL restart
# --------------------------------------------------------------------
section "9. Audit records persist across a real PostgreSQL restart"

pre_existing_id="$(insert_incident "fp-audit-pre-v3-style" open)"
[ "$(events_count_for "$pre_existing_id")" = "0" ] || fail "a freshly, directly-inserted incident already has audit events"

events_before_restart="$(get_events "$am_id")"
events_before_restart_body="$(echo "$events_before_restart" | sed '$d')"

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

events_after_restart="$(get_events "$am_id")"
events_after_restart_body="$(echo "$events_after_restart" | sed '$d')"
[ "$events_before_restart_body" = "$events_after_restart_body" ] || fail "audit timeline changed across a real PostgreSQL restart"
echo "  audit timeline (3 events for $am_id) byte-for-byte unchanged across a real PostgreSQL restart"

# --------------------------------------------------------------------
# 10. A pre-V3-style incident legitimately has an empty audit timeline
# --------------------------------------------------------------------
section "10. A pre-V3-style incident (never touched by the application) legitimately has an empty audit timeline"

response="$(get_events "$pre_existing_id")"
events_status="$(echo "$response" | tail -1)"
events_body="$(echo "$response" | sed '$d')"
[ "$events_status" = "200" ] || fail "GET events for a never-mutated incident returned $events_status, expected 200"
echo "$events_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body == {'items': [], 'total': 0, 'limit': 20, 'offset': 0}, body
print('  200 with a genuinely empty timeline, not a 404 and not fabricated history')
"

# --------------------------------------------------------------------
# 11. Missing incident, invalid UUID, invalid pagination
# --------------------------------------------------------------------
section "11. Missing incident, invalid UUID, invalid pagination"

random_uuid="$(python3 -c 'import uuid; print(uuid.uuid4())')"
missing_status="$(curl -s -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$random_uuid/events")"
[ "$missing_status" = "404" ] || fail "GET events for a nonexistent incident returned $missing_status, expected 404"

bad_uuid_status="$(curl -s -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/not-a-uuid/events")"
[ "$bad_uuid_status" = "422" ] || fail "GET events for a malformed UUID returned $bad_uuid_status, expected 422"

bad_limit_status="$(curl -s -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$am_id/events?limit=0")"
[ "$bad_limit_status" = "422" ] || fail "GET events with limit=0 returned $bad_limit_status, expected 422"

bad_offset_status="$(curl -s -o /dev/null -w '%{http_code}' "$CONTROL_PLANE_URL/api/v1/incidents/$am_id/events?offset=-1")"
[ "$bad_offset_status" = "422" ] || fail "GET events with offset=-1 returned $bad_offset_status, expected 422"
echo "  missing incident -> 404, malformed UUID -> 422, invalid limit/offset -> 422"

# --------------------------------------------------------------------
# 12. Pagination: an incident with more than 20 audit events, including
#     a resolution beyond page one
# --------------------------------------------------------------------
section "12. Pagination: an incident with more than 20 audit events, including a resolution beyond page one"

PAGINATION_FP="verify-incident-audit-pagination-${RUN_ID}"
pagination_base_iso() {
  python3 -c "from datetime import datetime, timedelta, timezone; print((datetime(2026,5,1,0,0,tzinfo=timezone.utc) + timedelta(minutes=$1)).isoformat())"
}

post_alert firing "$PAGINATION_FP" "$(pagination_base_iso 0)"
[ "$POST_STATUS" = "200" ] || fail "setup firing for pagination test returned $POST_STATUS: $POST_BODY"
pagination_id="$(psql_exec -t -A -c "SELECT id FROM reliability.incidents WHERE source='alertmanager' AND source_fingerprint='$PAGINATION_FP';" | sed -n '1p')"
[ -n "$pagination_id" ] || fail "no row found for $PAGINATION_FP"

# 20 further, strictly increasing-startsAt firing deliveries — each an
# accepted "observed" event into the same still-active incident (Phase
# 3D's watermark comparison updates on startsAt strictly newer than the
# current watermark; see docs/architecture/phase-3d-incident-lifecycle.md).
for i in $(seq 1 20); do
  post_alert firing "$PAGINATION_FP" "$(pagination_base_iso "$i")"
  [ "$POST_STATUS" = "200" ] || fail "observation #$i for pagination test returned $POST_STATUS: $POST_BODY"
done

post_alert resolved "$PAGINATION_FP" "$(pagination_base_iso 20)" "$(pagination_base_iso 25)"
[ "$POST_STATUS" = "200" ] || fail "resolving the pagination test incident returned $POST_STATUS: $POST_BODY"
echo "$POST_BODY" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b['incidents_resolved']==1, b"

pagination_total_events="$(events_count_for "$pagination_id")"
[ "$pagination_total_events" = "22" ] || fail "expected exactly 22 audit events for the pagination test incident (1 created + 20 observed + 1 resolved), found $pagination_total_events"

# Confirm the DEFAULT (unpaginated, limit=20) first page does NOT
# contain the resolving event — this is exactly the real gap
# independent review found in scripts/verify-ingestion.py's
# verify_audit_trail: a naive single-page GET against a long-lived
# incident can miss the resolution entirely.
first_page="$(get_events "$pagination_id")"
first_page_body="$(echo "$first_page" | sed '$d')"
echo "$first_page_body" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['total'] == 22, body
assert len(body['items']) == 20, body
assert not any(e['event_type'] == 'status_transition' for e in body['items']), 'the resolving event incorrectly appeared on the default first page'
print('  confirmed: the default first page (limit=20) does NOT contain the resolving event — exactly the gap this regression test guards against')
"

# Now fetch ALL pages, deliberately with a page size (10) smaller than
# the API's default (20) to force several real page boundaries, and
# confirm the complete, de-duplicated timeline: exactly 22 distinct
# event ids (no duplicates, nothing missing), the resolving event
# present and correctly attributed, and the creation event present.
pagination_summary="$(python3 -c "
import json, urllib.request
base = '$CONTROL_PLANE_URL'
incident_id = '$pagination_id'
items = []
offset = 0
page_size = 10
while True:
    with urllib.request.urlopen(f'{base}/api/v1/incidents/{incident_id}/events?limit={page_size}&offset={offset}') as resp:
        body = json.load(resp)
    page_items = body['items']
    items.extend(page_items)
    total = body['total']
    offset += page_size
    if not page_items or offset >= total:
        break
ids = [e['id'] for e in items]
assert len(ids) == len(set(ids)), f'duplicate event ids across pages: {ids}'
assert len(items) == total == 22, (len(items), total)
resolving = [e for e in items if e['event_type'] == 'status_transition' and e['new_status'] == 'resolved']
assert len(resolving) == 1, resolving
assert resolving[0]['actor_type'] == 'alertmanager', resolving[0]
created = [e for e in items if e['event_type'] == 'created']
assert len(created) == 1, created
print(json.dumps({'total': total, 'distinct_ids': len(set(ids)), 'resolving_actor': resolving[0]['actor_type']}))
")"
echo "  full paginated fetch (page size 10, smaller than the API's default limit) confirmed exactly 22 distinct events, no duplicates, resolving event present and correctly attributed: $pagination_summary"

# --------------------------------------------------------------------
# 13. Historical rows and their audit trails remain intact; nothing
#     is deleted (append-only by design). Post-review correction:
#     scoped EXACTLY to this run's own rows — the original LIKE
#     'verify-incident-audit-%' pattern matched every previous run's
#     retained rows too (since this script, by design, never deletes
#     anything — see the module docstring), which both inflated the
#     counts and made an exact assertion impossible. Scoped here to
#     the exact unique TEST_SOURCE plus the exact four run-specific
#     Alertmanager fingerprints this run itself created incidents
#     under (AM_FP, stale_fp, dup_resolve_fp, PAGINATION_FP) —
#     resolved_no_active_fp is deliberately excluded, since it never
#     creates an incident at all (asserted in section 6 above).
# --------------------------------------------------------------------
section "13. Historical rows and audit trails remain intact; nothing deleted"

ROWS_WHERE_SQL="source = '$TEST_SOURCE' OR (source = 'alertmanager' AND source_fingerprint IN ('$AM_FP', '$stale_fp', '$dup_resolve_fp', '$PAGINATION_FP'))"

final_incident_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE $ROWS_WHERE_SQL;")"
final_event_count="$(psql_exec -t -A -c "
  SELECT count(*) FROM reliability.incident_events ev
  JOIN reliability.incidents inc ON inc.id = ev.incident_id
  WHERE $ROWS_WHERE_SQL;
")"
# Independently re-traced through every section above:
#   TEST_SOURCE (direct-insert incidents): seed_id, patch_id, noop_id,
#     rollback_id, concurrency_id, pre_existing_id = 6 incidents.
#     Events: seed_id 1 (the manually-inserted seed event) + patch_id 1
#     (one successful PATCH) + noop_id 0 (every attempt rejected) +
#     rollback_id 0 (rolled back) + concurrency_id 1 (one winner of 10)
#     + pre_existing_id 0 (never mutated) = 3 events.
#   AM_FP: 1 incident (am_id). Events: created + observed + resolved = 3.
#   stale_fp: 1 incident. Events: created (the stale replay is ignored,
#     adding nothing) = 1.
#   dup_resolve_fp: 1 incident. Events: created + resolved (the
#     duplicate resolution is ignored, adding nothing) = 2.
#   PAGINATION_FP: 1 incident. Events: created + 20 observed + resolved
#     = 22.
#   Total incidents: 6 + 1 + 1 + 1 + 1 = 10.
#   Total events:    3 + 3 + 1 + 2 + 22 = 31.
[ "$final_incident_count" = "10" ] || fail "expected exactly 10 incidents scoped to this run, found $final_incident_count"
[ "$final_event_count" = "31" ] || fail "expected exactly 31 audit events scoped to this run, found $final_event_count"
echo "  confirmed: exactly $final_incident_count incidents and exactly $final_event_count audit events created by THIS run (not conflated with any prior run's retained rows) — all permanently retained, none deleted (append-only by design)"
trap - EXIT

echo ""
echo "SUCCESS: Phase 3E incident audit trail verification passed (real PostgreSQL, real HTTP API, real transactional atomicity, real concurrency, real restart durability, append-only enforcement including TRUNCATE, genuine insertion-time timestamps, pagination beyond the first page)."
