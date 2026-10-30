#!/usr/bin/env bash
#
# test-retention-timeout.sh -- Phase 17A correction round, item 6.
#
# Real proof, against a real, disposable PostgreSQL instance (its own
# throwaway network -- never the developer's own dev stack/db), that
# scripts/prune-telemetry-samples.py:
#   1. validates TELEMETRY_RETENTION_DAYS/TELEMETRY_RETENTION_BATCH_SIZE
#      and refuses an out-of-bounds value WITHOUT ever connecting to
#      the database;
#   2. dry-run/execute report and delete correctly, preserving recent
#      rows;
#   3. -- the real fault-injected case -- when a batch's own DELETE is
#      blocked behind another session's held lock on
#      reliability.telemetry_samples, the script does NOT hang
#      indefinitely: it fails within its own statement timeout, exits
#      non-zero, and never claims success.
#
# Runs the REAL Flyway migrations (database/migrations/) unmodified
# to create reliability.telemetry_samples and its real foreign-key
# dependencies -- never a hand-reimplemented schema.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"

RUN_ID="$$-$(date +%s)"
CONTAINER_NAME="arp-retention-proof-$RUN_ID"
NETWORK_NAME="arp-retention-proof-net-$RUN_ID"
IMAGE="pgvector/pgvector:pg18"
BOOTSTRAP_PW="proof-bootstrap-$RUN_ID"
PRUNE_IMAGE_TAG="arp-retention-proof-pruner-$RUN_ID"

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }
fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  docker rmi "$PRUNE_IMAGE_TAG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== starting a disposable PostgreSQL instance (no volume, no published port, its own network) =="
docker network create "$NETWORK_NAME" >/dev/null
docker run -d --name "$CONTAINER_NAME" --network "$NETWORK_NAME" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb \
  "$IMAGE" >/dev/null

echo "== waiting for it to become ready =="
ready=0
for _ in $(seq 1 60); do
  if docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" psql -U postgres -d proofdb -c "SELECT 1;" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" -eq 1 ] || fail "the disposable postgres instance never became ready"

echo "== applying the REAL Flyway migrations (database/migrations/, unmodified) =="
docker run --rm --network "$NETWORK_NAME" \
  -e FLYWAY_URL="jdbc:postgresql://$CONTAINER_NAME:5432/proofdb" \
  -e FLYWAY_USER=postgres \
  -e FLYWAY_PASSWORD="$BOOTSTRAP_PW" \
  -e FLYWAY_SCHEMAS=reliability \
  -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
  -v "$REPO_ROOT/database/migrations:/flyway/sql:ro" \
  flyway/flyway:13.9.0 migrate >/dev/null

psql_proof() {
  docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -U postgres -d proofdb "$@"
}

echo "== seeding one real service + integration_credential + a mix of old/recent telemetry_samples rows =="
psql_proof -c "
  INSERT INTO reliability.services (id, organization_id, name, kind, created_by_user_id)
  VALUES ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'proof-service', 'other', 'proof-user');
  INSERT INTO reliability.integration_credentials
    (id, organization_id, service_id, connection_type, credential_id, credential_secret_hash, status, created_by_user_id)
  VALUES
    ('33333333-3333-3333-3333-333333333333', '22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111',
     'opentelemetry', 'proof-credential-id', 'deadbeef', 'active', 'proof-user');
  INSERT INTO reliability.telemetry_samples
    (organization_id, service_id, integration_credential_id, observed_at, request_count, duration_sum_seconds, is_error)
  SELECT
    '22222222-2222-2222-2222-222222222222',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    now() - interval '60 days' - (n || ' seconds')::interval,
    1, 0.1, false
  FROM generate_series(1, 25) AS n;
  INSERT INTO reliability.telemetry_samples
    (organization_id, service_id, integration_credential_id, observed_at, request_count, duration_sum_seconds, is_error)
  VALUES
    ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', now() - interval '1 hour', 1, 0.1, false);
" 2>&1 | tail -5

echo "== building a disposable pruner image (reuses the real script unmodified) =="
docker build -q -t "$PRUNE_IMAGE_TAG" -f "$DEPLOY_DIR/retention-scheduler.Dockerfile" "$REPO_ROOT" >/dev/null

echo ""
echo "== proving invalid TELEMETRY_RETENTION_DAYS is rejected WITHOUT ever connecting to the database =="
if out="$(docker run --rm --network none \
  -e POSTGRES_HOST=unreachable-host -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=x -e POSTGRES_DB=proofdb \
  -e TELEMETRY_RETENTION_DAYS=-5 \
  --entrypoint python3 "$PRUNE_IMAGE_TAG" ./prune-telemetry-samples.py 2>&1)"; then
  case_fail "invalid TELEMETRY_RETENTION_DAYS=-5 unexpectedly exited 0"
else
  if echo "$out" | grep -q "out of the required bounds"; then
    case_pass "TELEMETRY_RETENTION_DAYS=-5 rejected before any DB connection attempt (ran with --network none)"
  else
    case_fail "TELEMETRY_RETENTION_DAYS=-5 failed, but not with the expected bounds message -- see: $out"
  fi
fi

echo ""
echo "== proving invalid TELEMETRY_RETENTION_BATCH_SIZE is rejected WITHOUT ever connecting =="
if out="$(docker run --rm --network none \
  -e POSTGRES_HOST=unreachable-host -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=x -e POSTGRES_DB=proofdb \
  -e TELEMETRY_RETENTION_BATCH_SIZE=0 \
  --entrypoint python3 "$PRUNE_IMAGE_TAG" ./prune-telemetry-samples.py 2>&1)"; then
  case_fail "invalid TELEMETRY_RETENTION_BATCH_SIZE=0 unexpectedly exited 0"
else
  if echo "$out" | grep -q "out of the required bounds"; then
    case_pass "TELEMETRY_RETENTION_BATCH_SIZE=0 rejected before any DB connection attempt (ran with --network none)"
  else
    case_fail "TELEMETRY_RETENTION_BATCH_SIZE=0 failed, but not with the expected bounds message -- see: $out"
  fi
fi

echo ""
echo "== proving a normal dry run reports the real eligible count without deleting anything =="
dry_out="$(docker run --rm --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$CONTAINER_NAME" -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb \
  -e TELEMETRY_RETENTION_DAYS=30 \
  --entrypoint python3 "$PRUNE_IMAGE_TAG" ./prune-telemetry-samples.py 2>&1)"
echo "$dry_out" | sed 's/^/  /'
remaining_before="$(psql_proof -t -A -c "SELECT count(*) FROM reliability.telemetry_samples;" | tr -d '[:space:]')"
if echo "$dry_out" | grep -q "eligible_rows=25" && [ "$remaining_before" = "26" ]; then
  case_pass "dry run reported eligible_rows=25 and deleted nothing (26 rows still present)"
else
  case_fail "dry run did not report the expected eligible count, or rows were deleted -- see output above (remaining=$remaining_before)"
fi

echo ""
echo "== proving --execute deletes only the old rows, preserving the recent one =="
exec_out="$(docker run --rm --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$CONTAINER_NAME" -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb \
  -e TELEMETRY_RETENTION_DAYS=30 -e TELEMETRY_RETENTION_BATCH_SIZE=10 \
  --entrypoint python3 "$PRUNE_IMAGE_TAG" ./prune-telemetry-samples.py --execute 2>&1)"
exec_status=$?
echo "$exec_out" | sed 's/^/  /'
remaining_after="$(psql_proof -t -A -c "SELECT count(*) FROM reliability.telemetry_samples;" | tr -d '[:space:]')"
recent_still_present="$(psql_proof -t -A -c "SELECT count(*) FROM reliability.telemetry_samples WHERE observed_at > now() - interval '1 day';" | tr -d '[:space:]')"
if [ "$exec_status" -eq 0 ] && [ "$remaining_after" = "1" ] && [ "$recent_still_present" = "1" ]; then
  case_pass "--execute deleted exactly the 25 old rows across batches (batch size 10), preserving the 1 recent row"
else
  case_fail "--execute did not leave the expected state (remaining=$remaining_after recent=$recent_still_present exit=$exec_status)"
fi

echo ""
echo "== re-seeding a fresh batch of old rows, then proving a lock-blocked DELETE fails closed within the statement timeout (never hangs, never reports success) =="
psql_proof -c "
  INSERT INTO reliability.telemetry_samples
    (organization_id, service_id, integration_credential_id, observed_at, request_count, duration_sum_seconds, is_error)
  SELECT
    '22222222-2222-2222-2222-222222222222',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    now() - interval '60 days' - (n || ' seconds')::interval,
    1, 0.1, false
  FROM generate_series(1, 5) AS n;
" >/dev/null 2>&1

LOCK_HOLD_LOG="$(mktemp)"
# Holds an ACCESS EXCLUSIVE lock on the table for 50s -- long enough
# to prove the pruner's own ~30s statement_timeout fires first, short
# enough this proof doesn't hang indefinitely either way.
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" \
  psql -v ON_ERROR_STOP=1 -U postgres -d proofdb \
  -c "BEGIN; LOCK TABLE reliability.telemetry_samples IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(50); COMMIT;" \
  > "$LOCK_HOLD_LOG" 2>&1 &
lock_holder_pid=$!
sleep 2  # let the lock actually be acquired before the pruner starts

start_ts="$(date +%s)"
# This pruner run is EXPECTED to fail (that is the whole point of
# this case) -- `set +e` around it, mirroring the exact fix applied
# to restore.sh's own pg_restore call this round: without it, `set -e`
# would abort THIS test script the instant the command substitution
# itself returns non-zero, before `blocked_status=$?` is ever reached.
set +e
blocked_out="$(docker run --rm --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$CONTAINER_NAME" -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb \
  -e TELEMETRY_RETENTION_DAYS=30 \
  --entrypoint python3 "$PRUNE_IMAGE_TAG" ./prune-telemetry-samples.py --execute 2>&1)"
blocked_status=$?
set -e
end_ts="$(date +%s)"
elapsed=$((end_ts - start_ts))
echo "$blocked_out" | sed 's/^/  /'
echo "  elapsed: ${elapsed}s, exit: $blocked_status"

wait "$lock_holder_pid" 2>/dev/null || true
rm -f "$LOCK_HOLD_LOG"

if [ "$blocked_status" -ne 0 ] && [ "$elapsed" -lt 45 ] && ! echo "$blocked_out" | grep -qi "done in.*deleted"; then
  case_pass "lock-blocked DELETE failed closed in ${elapsed}s (< the 50s lock hold), exit $blocked_status, never reported a completed run"
else
  case_fail "lock-blocked DELETE did not fail closed within the expected window (elapsed=${elapsed}s exit=$blocked_status) -- see output above"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL RETENTION TIMEOUT/BOUNDS PROOFS PASSED"
  exit 0
else
  echo "ONE OR MORE RETENTION TIMEOUT/BOUNDS PROOFS FAILED" >&2
  exit 1
fi
