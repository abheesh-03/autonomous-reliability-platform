#!/usr/bin/env bash
#
# verify-control-plane.sh — Phase 3B control-plane integration
# verification.
#
# Proves the real FastAPI control plane, backed by the real PostgreSQL
# reliability.incidents table, works end-to-end — not a mocked
# repository, not an in-process TestClient. Test incidents are inserted
# directly through PostgreSQL (never through an HTTP API — Phase 3B is
# read-only and there is no incident-creation endpoint), then fetched
# back through the actual running HTTP service.
#
# Safe to rerun against a nonempty local database: every row this
# script creates uses a `source` value unique to this specific
# execution (embedding a fresh UUID), and cleanup deletes only rows
# matching that exact value — never another run's rows, and never real
# data. Does not reset or delete any volume at any point.
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

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (copy .env.example to .env)}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (copy .env.example to .env)}"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"

# Run-unique marker: every test row's "source" embeds a fresh UUID, so
# filtering by it is inherently scoped to exactly this execution — no
# separate fingerprint-prefix scoping is needed (unlike
# scripts/verify-persistence.sh, which shares one fixed source string
# across runs and so needs that extra scoping).
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
TEST_SOURCE="verify-control-plane-test-${RUN_ID}"
CLEANUP_SQL="DELETE FROM reliability.incidents WHERE source = '$TEST_SOURCE';"

psql_exec() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

besteffort_cleanup() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$CLEANUP_SQL" >/dev/null 2>&1 || true
}
trap besteffort_cleanup EXIT

# GET $1 (path + query string) against the running control plane.
# Leaves the response body in $HTTP_BODY and the status code in
# $HTTP_STATUS. Bounded connect/total timeouts so a hung or
# unreachable control-plane can never stall the script indefinitely —
# this matters inside the bounded readiness/recovery retry loops
# (sections 3 and 13), which must keep retrying rather than aborting
# on one transient transport failure. A transport-level failure (e.g.
# connection refused while control-plane is restarting) is reported as
# HTTP_STATUS="000" with an empty body, distinct from any real HTTP
# status the service itself can return — deliberately not using curl
# --fail, since this script's own assertions intentionally expect and
# check for 404/422/503 responses, which --fail would turn into curl
# errors indistinguishable from a transport failure. The `|| curl_exit=$?`
# form keeps this failure from tripping `set -e` and aborting the
# script outright; callers that assert an exact 2xx status (the
# majority of call sites below) still fail immediately and correctly
# via their own `[ "$HTTP_STATUS" = "200" ] || fail ...` checks, since
# "000" never matches an expected status.
api_get() {
  local path="$1" response curl_exit=0
  response="$(curl -s --connect-timeout 2 --max-time 10 -w '\n%{http_code}' "$CONTROL_PLANE_URL$path")" || curl_exit=$?
  if [ "$curl_exit" -ne 0 ]; then
    HTTP_STATUS="000"
    HTTP_BODY=""
    return 0
  fi
  HTTP_STATUS="$(echo "$response" | tail -1)"
  HTTP_BODY="$(echo "$response" | sed '$d')"
}

# --------------------------------------------------------------------
# 1. Confirm PostgreSQL is healthy
# --------------------------------------------------------------------
section "1. PostgreSQL healthy"

docker compose up -d postgres

postgres_healthy=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  echo "  attempt $i/20: health=$health"
  if [ "$health" = "healthy" ]; then
    postgres_healthy=true
    break
  fi
  sleep 3
done
[ "$postgres_healthy" = true ] || fail "postgres did not become healthy in time"

# --------------------------------------------------------------------
# 2. Ensure Phase 3A migrations are applied (existing Flyway mechanism)
# --------------------------------------------------------------------
section "2. Apply Phase 3A migrations"

docker compose run --rm flyway migrate

# --------------------------------------------------------------------
# 3. Confirm control-plane liveness and readiness
# --------------------------------------------------------------------
section "3. control-plane liveness and readiness"

docker compose up -d control-plane

cp_healthy=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q control-plane)" 2>/dev/null || true)"
  echo "  attempt $i/20: docker health=$health"
  if [ "$health" = "healthy" ]; then
    cp_healthy=true
    break
  fi
  sleep 3
done
[ "$cp_healthy" = true ] || fail "control-plane did not become healthy (docker healthcheck, GET /health/live) in time"

api_get "/health/live"
[ "$HTTP_STATUS" = "200" ] || fail "GET /health/live returned $HTTP_STATUS, expected 200: $HTTP_BODY"
echo "  GET /health/live -> 200"

ready_ok=false
for i in $(seq 1 20); do
  api_get "/health/ready"
  if [ "$HTTP_STATUS" = "200" ]; then
    ready_ok=true
    break
  fi
  echo "  attempt $i/20: GET /health/ready -> $HTTP_STATUS (migrations may still be settling)"
  sleep 3
done
[ "$ready_ok" = true ] || fail "GET /health/ready never returned 200 after migrations were applied"
echo "  GET /health/ready -> 200"

# --------------------------------------------------------------------
# 4. Insert real test incidents directly through PostgreSQL
# --------------------------------------------------------------------
section "4. Insert real test incidents directly through PostgreSQL"

echo "-- four real rows, inserted via psql (never through an HTTP API —"
echo "   Phase 3B exposes no incident-creation endpoint), with"
echo "   deliberately staggered last_seen_at values so ordering and"
echo "   pagination are independently checkable --"

# occurrence_starts_at (Phase 3D V2, NOT NULL, no column default — same
# convention as first_seen_at/last_seen_at) is set equal to
# first_seen_at for each of these directly-inserted rows: none of them
# have ever accepted a newer firing observation since creation.
id_a="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '${TEST_SOURCE}-a', 'Checkout latency high', 'critical', 'open', now() - interval '3 minutes', now(), now() - interval '3 minutes')
  RETURNING id;
" | sed -n '1p')"

id_b="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '${TEST_SOURCE}-b', 'Payment errors elevated', 'warning', 'investigating', now() - interval '4 minutes', now() - interval '1 minute', now() - interval '4 minutes')
  RETURNING id;
" | sed -n '1p')"

id_c="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, resolved_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '${TEST_SOURCE}-c', 'Synthetic check flaky', 'info', 'resolved', now() - interval '10 minutes', now() - interval '2 minutes', now() - interval '2 minutes', now() - interval '10 minutes')
  RETURNING id;
" | sed -n '1p')"

id_d="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '${TEST_SOURCE}-d', 'Queue backlog growing', 'critical', 'acknowledged', now() - interval '8 minutes', now() - interval '3 minutes', now() - interval '8 minutes')
  RETURNING id;
" | sed -n '1p')"

for v in id_a id_b id_c id_d; do
  [ -n "${!v}" ] || fail "insert for $v returned no id"
done
echo "  inserted: a=$id_a b=$id_b c=$id_c d=$id_d"

a_updated_before="$(psql_exec -t -A -c "SELECT updated_at FROM reliability.incidents WHERE id = '$id_a';")"

# --------------------------------------------------------------------
# 5-6. Fetch via the running API; verify fields and timestamp
#      serialization
# --------------------------------------------------------------------
section "5-6. Fetch via the API; verify fields and timestamp serialization"

api_get "/api/v1/incidents/$id_a"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$id_a returned $HTTP_STATUS: $HTTP_BODY"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['id'] == '$id_a', body
assert body['source'] == '$TEST_SOURCE', body
assert body['source_fingerprint'] == '${TEST_SOURCE}-a', body
assert body['title'] == 'Checkout latency high', body
assert body['description'] is None, body
assert body['severity'] == 'critical', body
assert body['status'] == 'open', body
assert body['resolved_at'] is None, body
from datetime import datetime
for field in ('first_seen_at', 'last_seen_at', 'created_at', 'updated_at'):
    datetime.fromisoformat(body[field])
print('  fields and timestamp serialization OK')
"

# --------------------------------------------------------------------
# 7. Verify status, severity, and source filters
# --------------------------------------------------------------------
section "7. Verify status, severity, and source filters"

api_get "/api/v1/incidents?source=${TEST_SOURCE}&status=open"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
ids = [i['id'] for i in body['items']]
assert ids == ['$id_a'], body
assert body['total'] == 1, body
print('  status=open filter OK (matches only a)')
"

api_get "/api/v1/incidents?source=${TEST_SOURCE}&severity=critical"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
ids = {i['id'] for i in body['items']}
assert ids == {'$id_a', '$id_d'}, body
assert body['total'] == 2, body
print('  severity=critical filter OK (matches a and d)')
"

api_get "/api/v1/incidents?source=${TEST_SOURCE}"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
ids = {i['id'] for i in body['items']}
assert ids == {'$id_a', '$id_b', '$id_c', '$id_d'}, body
assert body['total'] == 4, body
print('  source filter OK (matches all 4 test rows, and only them)')
"

# --------------------------------------------------------------------
# 8. Verify deterministic ordering and pagination
# --------------------------------------------------------------------
section "8. Verify deterministic ordering and pagination"

api_get "/api/v1/incidents?source=${TEST_SOURCE}&limit=2&offset=0"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
ids = [i['id'] for i in body['items']]
assert ids == ['$id_a', '$id_b'], (ids, 'expected a,b (newest last_seen_at first)')
assert body['total'] == 4, body
assert body['limit'] == 2 and body['offset'] == 0, body
print('  page 1 (limit=2 offset=0) OK: a, b')
"

api_get "/api/v1/incidents?source=${TEST_SOURCE}&limit=2&offset=2"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
ids = [i['id'] for i in body['items']]
assert ids == ['$id_c', '$id_d'], (ids, 'expected c,d')
assert body['total'] == 4, body
assert body['limit'] == 2 and body['offset'] == 2, body
print('  page 2 (limit=2 offset=2) OK: c, d')
"

# --------------------------------------------------------------------
# 9. Verify total count and empty-result behavior
# --------------------------------------------------------------------
section "9. Verify total count and empty-result behavior"

api_get "/api/v1/incidents?source=${TEST_SOURCE}&status=closed"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body == {'items': [], 'total': 0, 'limit': 20, 'offset': 0}, body
print('  empty result for a real-but-unmatched filter combination: empty items array, total=0 (not a fabricated incident)')
"

# --------------------------------------------------------------------
# 10. Verify UUID detail lookup
# --------------------------------------------------------------------
section "10. Verify UUID detail lookup"

api_get "/api/v1/incidents/$id_c"
[ "$HTTP_STATUS" = "200" ] || fail "GET /api/v1/incidents/$id_c returned $HTTP_STATUS"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['status'] == 'resolved', body
assert body['resolved_at'] is not None, body
print('  detail lookup by UUID OK (resolved incident, resolved_at populated)')
"

# --------------------------------------------------------------------
# 11. Verify 404, 422, and invalid pagination handling
# --------------------------------------------------------------------
section "11. Verify 404, 422, and invalid pagination handling"

random_uuid="$(python3 -c 'import uuid; print(uuid.uuid4())')"
api_get "/api/v1/incidents/$random_uuid"
[ "$HTTP_STATUS" = "404" ] || fail "GET for a well-formed but nonexistent UUID returned $HTTP_STATUS, expected 404: $HTTP_BODY"
echo "  nonexistent UUID -> 404"

api_get "/api/v1/incidents/not-a-uuid"
[ "$HTTP_STATUS" = "422" ] || fail "GET for a malformed UUID returned $HTTP_STATUS, expected 422: $HTTP_BODY"
echo "  malformed UUID -> 422"

for bad_query in "limit=0" "limit=101" "offset=-1" "status=bogus" "severity=bogus"; do
  api_get "/api/v1/incidents?${bad_query}"
  [ "$HTTP_STATUS" = "422" ] || fail "GET /api/v1/incidents?${bad_query} returned $HTTP_STATUS, expected 422: $HTTP_BODY"
  echo "  invalid query ($bad_query) -> 422"
done

# --------------------------------------------------------------------
# 12. Verify read-only API calls do not unexpectedly modify records
# --------------------------------------------------------------------
section "12. Verify read-only API calls do not modify incident records"

api_get "/api/v1/incidents/$id_a" >/dev/null
api_get "/api/v1/incidents?source=${TEST_SOURCE}" >/dev/null
api_get "/api/v1/incidents/$id_a" >/dev/null

a_updated_after="$(psql_exec -t -A -c "SELECT updated_at FROM reliability.incidents WHERE id = '$id_a';")"
[ "$a_updated_after" = "$a_updated_before" ] || fail "incident $id_a's updated_at changed after read-only API calls (before=$a_updated_before after=$a_updated_after) — a GET must never write"
echo "  updated_at unchanged across multiple GET requests: $a_updated_before"

# --------------------------------------------------------------------
# 13. Verify the API recovers after a PostgreSQL restart (real pool)
# --------------------------------------------------------------------
section "13. Verify recovery after a PostgreSQL restart"

api_get "/health/ready"
[ "$HTTP_STATUS" = "200" ] || fail "readiness was not 200 before the restart (precondition failed): $HTTP_BODY"

docker compose restart postgres >/dev/null
echo "  postgres restarted"

postgres_healthy_after_restart=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  [ "$health" = "healthy" ] && postgres_healthy_after_restart=true && break
  sleep 3
done
[ "$postgres_healthy_after_restart" = true ] || fail "postgres did not become healthy again after restart"

recovered=false
for i in $(seq 1 20); do
  api_get "/health/ready"
  if [ "$HTTP_STATUS" = "200" ]; then
    recovered=true
    break
  fi
  echo "  attempt $i/20: GET /health/ready -> $HTTP_STATUS (recovering)"
  sleep 3
done
[ "$recovered" = true ] || fail "control-plane readiness never recovered to 200 after the PostgreSQL restart"
echo "  readiness recovered to 200 via the real connection pool (control-plane container was never restarted)"

api_get "/api/v1/incidents/$id_a"
[ "$HTTP_STATUS" = "200" ] || fail "a real data fetch after the restart returned $HTTP_STATUS, expected 200: $HTTP_BODY"
echo "$HTTP_BODY" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body['id'] == '$id_a', body
print('  real data fetch after restart OK — connection pool genuinely usable, not just readiness reporting healthy')
"

cp_container_status="$(docker compose ps control-plane --format '{{.Status}}')"
echo "  control-plane container status (should show one continuous uptime, never restarted): $cp_container_status"

# --------------------------------------------------------------------
# 14. Clean up ONLY this execution's test-created rows
# --------------------------------------------------------------------
section "14. Clean up only this execution's test-created rows"

before_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = '$TEST_SOURCE';")"
[ "$before_count" = "4" ] || fail "expected exactly 4 rows for this run's source before cleanup, found: $before_count"
# Not suppressed: a cleanup failure here fails the whole script (same
# reasoning as scripts/verify-persistence.sh's section 15).
psql_exec -c "$CLEANUP_SQL"
after_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source = '$TEST_SOURCE';")"
[ "$after_count" = "0" ] || fail "cleanup did not remove all of this run's rows (still present: $after_count)"
echo "  cleaned up: $before_count -> $after_count rows for source='$TEST_SOURCE'"
trap - EXIT

echo ""
echo "SUCCESS: Phase 3B control-plane integration verification passed (real PostgreSQL, real HTTP API, real restart recovery)."
