#!/usr/bin/env bash
#
# verify-persistence.sh — Phase 3A persistence verification.
#
# Proves the incident domain model (reliability.incidents, applied via
# the versioned Flyway migration in database/migrations/) is real,
# durable PostgreSQL persistence — not SQLite, not a mocked repository,
# not a simulated database. Runs entirely against the real pinned
# postgres:18 image and the real pinned flyway/flyway:13.9.0 image,
# using the project's existing Docker Compose services.
#
# Safe to rerun against a nonempty local database, and safe on a
# completely fresh database (e.g. a new GitHub Actions postgres_data
# volume): every row this script creates is scoped under a single
# run-unique marker (source='verify-persistence-test' AND
# source_fingerprint LIKE '<this run's UUID>%'), and only rows matching
# that exact marker are ever deleted — other runs' test rows, any real
# data, and the optional pre-existing Phase 0 fixture
# (public.phase_02_verification, present on an existing local database
# but absent on a fresh one) are never touched, created, or deleted.
# Does not reset or delete the postgres_data volume at any point.
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

# A run-unique marker: every row this script inserts uses this exact
# "source" value AND a source_fingerprint prefixed with this run's own
# UUID, so cleanup can be scoped to exactly this execution — never a
# different run's rows (including a previous, still-present test run's
# rows on a database that was never cleaned, or a concurrently running
# instance of this same script). Generated via Python's stdlib (already
# a dependency elsewhere in this repo), not `uuidgen`, since `uuidgen`
# is not guaranteed present on every CI runner image.
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
TEST_SOURCE="verify-persistence-test"
TEST_FINGERPRINT="verify-persistence-test-${RUN_ID}"
CLEANUP_SQL="DELETE FROM reliability.incidents WHERE source = '$TEST_SOURCE' AND source_fingerprint LIKE '${TEST_FINGERPRINT}%';"

psql_exec() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

# Best-effort only: used exclusively by the EXIT trap, so a cleanup
# failure while unwinding after an earlier test already failed never
# masks that original failure (and never introduces a second, confusing
# failure of its own). The normal, happy-path cleanup in section 15
# below is a separate, NON-suppressed call — if that one fails, the
# script fails, since a cleanup failure on an otherwise-successful run
# is a real problem worth surfacing.
besteffort_cleanup() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$CLEANUP_SQL" >/dev/null 2>&1 || true
}
trap besteffort_cleanup EXIT

# Returns 0 (and prints nothing of interest) only if the given SQL
# statement is rejected with EXACTLY the expected PostgreSQL SQLSTATE —
# not merely "the command failed somehow". A connection failure, a SQL
# syntax error, a missing table, or any other unexpected SQLSTATE fails
# this whole script, same as the statement being incorrectly accepted.
# If expected_constraint is given, also requires psql's verbose error
# output to name that exact constraint.
expect_rejected() {
  local description="$1" sql="$2" expected_sqlstate="$3" expected_constraint="${4:-}"
  local reject_log actual_sqlstate actual_constraint

  reject_log="$(mktemp)"
  if docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$sql" >/dev/null 2>"$reject_log"; then
    rm -f "$reject_log"
    fail "$description: statement was incorrectly ACCEPTED (expected SQLSTATE $expected_sqlstate): $sql"
  fi

  actual_sqlstate="$(sed -n 's/^ERROR:  \([0-9A-Z]\{5\}\):.*/\1/p' "$reject_log" | head -1)"
  if [ "$actual_sqlstate" != "$expected_sqlstate" ]; then
    fail "$description: expected SQLSTATE $expected_sqlstate but got $( [ -n "$actual_sqlstate" ] && echo "$actual_sqlstate" || echo "<no recognizable PostgreSQL SQLSTATE — connection, Docker, or infrastructure failure?>" ); full psql output: $(cat "$reject_log")"
  fi

  actual_constraint="$(sed -n 's/^CONSTRAINT NAME:  //p' "$reject_log" | head -1)"
  if [ -n "$expected_constraint" ] && [ "$actual_constraint" != "$expected_constraint" ]; then
    fail "$description: expected violation of constraint '$expected_constraint' but psql reported '$actual_constraint'; full output: $(cat "$reject_log")"
  fi

  echo "  correctly rejected ($description): SQLSTATE=$actual_sqlstate${actual_constraint:+ constraint=$actual_constraint}"
  rm -f "$reject_log"
}

# --------------------------------------------------------------------
# 1. PostgreSQL becomes healthy
# --------------------------------------------------------------------
section "1. PostgreSQL becomes healthy"

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

echo ""
echo "-- checking for the optional, pre-existing Phase 0 verification"
echo "   fixture (public.phase_02_verification). It exists on this"
echo "   machine's long-running local database but is NOT expected on a"
echo "   fresh database (e.g. a new GitHub Actions postgres_data volume)"
echo "   — this script never creates, overwrites, or deletes it either"
echo "   way, only reads it when present --"
phase0_fixture_present=false
phase0_before=""
phase0_table_exists="$(psql_exec -t -A -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'phase_02_verification');")"
if [ "$phase0_table_exists" = "t" ]; then
  phase0_before="$(psql_exec -t -A -c "SELECT message FROM public.phase_02_verification WHERE id = 1;")"
  if [ -n "$phase0_before" ]; then
    phase0_fixture_present=true
    echo "  Phase 0 fixture present: message='$phase0_before' (will be re-checked, unchanged, after the restart below)"
  else
    echo "  public.phase_02_verification exists but has no id=1 row — treating as absent; nothing to verify"
  fi
else
  echo "  public.phase_02_verification not present (expected on a fresh database) — proceeding normally"
fi

# --------------------------------------------------------------------
# 2. Versioned migrations apply successfully
# --------------------------------------------------------------------
section "2. Versioned migrations apply successfully"

docker compose run --rm flyway migrate

# --------------------------------------------------------------------
# 3. Expected schema/table/indexes exist
# --------------------------------------------------------------------
section "3. Expected schema/table/indexes exist"

table_exists="$(psql_exec -t -A -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'reliability' AND table_name = 'incidents');")"
[ "$table_exists" = "t" ] || fail "reliability.incidents table does not exist after migration"
echo "  reliability.incidents exists"

# --------------------------------------------------------------------
# 4-7. Insert a valid incident; read it back; verify UUID, timestamps,
#      and default initial status
# --------------------------------------------------------------------
section "4-7. Insert, read back, and verify a valid incident"

incident_id="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, description, severity, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '$TEST_FINGERPRINT', 'Verification incident', 'Created by scripts/verify-persistence.sh', 'critical', now(), now(), now())
  RETURNING id;
" | head -1)"
[ -n "$incident_id" ] || fail "INSERT of a valid incident returned no id"
echo "  inserted incident id=$incident_id"

row="$(psql_exec -t -A -F'|' -c "
  SELECT id, status, resolved_at, first_seen_at, last_seen_at, created_at, updated_at
  FROM reliability.incidents WHERE id = '$incident_id';
")"
[ -n "$row" ] || fail "could not read back the just-inserted incident (id=$incident_id)"
echo "  read back: $row"

IFS='|' read -r read_id read_status read_resolved_at read_first_seen read_last_seen read_created read_updated <<<"$row"

echo "$read_id" | grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' \
  || fail "id is not a well-formed UUID: $read_id"
[ "$read_id" = "$incident_id" ] || fail "read-back id ($read_id) does not match inserted id ($incident_id)"
echo "  id is a well-formed UUID and matches the inserted id"

for ts_value in "$read_first_seen" "$read_last_seen" "$read_created" "$read_updated"; do
  [ -n "$ts_value" ] || fail "a required timestamp column was empty/null"
done
echo "  first_seen_at/last_seen_at/created_at/updated_at are all populated"

[ -z "$read_resolved_at" ] || fail "resolved_at should be NULL for a freshly created incident, got: $read_resolved_at"
echo "  resolved_at is NULL, as expected for a new incident"

# Confirms the column DEFAULT only — omitting `status` on INSERT yields
# 'open'. This is not a creation-time invariant the database enforces
# against a caller who explicitly inserts a different valid status
# (e.g. status='investigating' on INSERT succeeds today; only the
# status-vocabulary CHECK restricts which values are legal at all).
# Real creation/transition enforcement is Phase 3D's job.
[ "$read_status" = "open" ] || fail "status should default to 'open' when omitted on INSERT, got: $read_status"
echo "  status defaults to 'open' when omitted on INSERT (not yet an enforced creation-time invariant — see Phase 3D)"

# --------------------------------------------------------------------
# 8. Invalid severity/status rejected (exact SQLSTATE 23514: check_violation)
# --------------------------------------------------------------------
section "8. Invalid severity/status rejected"

# occurrence_starts_at (Phase 3D V2, NOT NULL, no column default — same
# convention as first_seen_at/last_seen_at) is supplied in every INSERT
# below, including the intentionally-invalid ones: omitting it would
# make the INSERT fail with a NOT NULL violation (23502) instead of the
# specific check_violation/unique_violation each test actually means to
# exercise.
expect_rejected "invalid severity" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('$TEST_SOURCE', '${TEST_FINGERPRINT}-bad-severity', 'Bad severity', 'catastrophic', now(), now(), now());" \
  "23514"

expect_rejected "invalid status" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('$TEST_SOURCE', '${TEST_FINGERPRINT}-bad-status', 'Bad status', 'info', 'triaging', now(), now(), now());" \
  "23514"

# --------------------------------------------------------------------
# 9. Blank required identifiers rejected (SQLSTATE 23514: check_violation)
# --------------------------------------------------------------------
section "9. Blank required identifiers rejected"

expect_rejected "blank title" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('$TEST_SOURCE', '${TEST_FINGERPRINT}-blank-title', '   ', 'info', now(), now(), now());" \
  "23514"

expect_rejected "blank source" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('', '${TEST_FINGERPRINT}-blank-source', 'Blank source', 'info', now(), now(), now());" \
  "23514"

expect_rejected "blank source_fingerprint" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('$TEST_SOURCE', '  ', 'Blank fingerprint', 'info', now(), now(), now());" \
  "23514"

# --------------------------------------------------------------------
# 10. Duplicate active incidents rejected (SQLSTATE 23505: unique_violation)
# --------------------------------------------------------------------
section "10. Duplicate active incidents rejected"

echo "-- this is a sequential check (one INSERT, then a second against the"
echo "   same still-open database connection pattern), not an empirical"
echo "   two-session concurrency race test. The protection it proves —"
echo "   that a second INSERT for the same (source, source_fingerprint)"
echo "   while the first is still active is rejected — comes entirely"
echo "   from PostgreSQL's own real unique index enforcement"
echo "   (incidents_active_fingerprint_uniq), which is what actually"
echo "   provides safety under real concurrent writers, not anything"
echo "   this script does procedurally --"

expect_rejected "duplicate active (source, source_fingerprint)" \
  "INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at) VALUES ('$TEST_SOURCE', '$TEST_FINGERPRINT', 'Duplicate while active', 'warning', now(), now(), now());" \
  "23505" "incidents_active_fingerprint_uniq"

echo ""
echo "-- confirming the policy's other half: once the original is"
echo "   resolved, the same (source, source_fingerprint) may be used"
echo "   again by a new active incident, and the resolved row is kept,"
echo "   not overwritten --"
psql_exec -c "UPDATE reliability.incidents SET status = 'resolved', resolved_at = now() WHERE id = '$incident_id';" >/dev/null

recurred_id="$(psql_exec -t -A -c "
  INSERT INTO reliability.incidents (source, source_fingerprint, title, severity, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('$TEST_SOURCE', '$TEST_FINGERPRINT', 'Recurred after resolution', 'warning', now(), now(), now())
  RETURNING id;
" | head -1)"
[ -n "$recurred_id" ] || fail "re-using (source, source_fingerprint) after the prior incident resolved was unexpectedly rejected"
[ "$recurred_id" != "$incident_id" ] || fail "re-using the fingerprint after resolution should create a NEW row, got the same id back"
echo "  new active incident ($recurred_id) created after prior ($incident_id) resolved"

remaining_for_fingerprint="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents WHERE source_fingerprint = '$TEST_FINGERPRINT';")"
[ "$remaining_for_fingerprint" = "2" ] || fail "expected exactly 2 historical rows for this fingerprint (1 resolved + 1 active), found: $remaining_for_fingerprint"
echo "  both the resolved original and the new active incident are preserved (2 rows total)"

# --------------------------------------------------------------------
# 11. Appropriate indexes exist
# --------------------------------------------------------------------
section "11. Appropriate indexes exist"

expected_indexes="incidents_active_fingerprint_uniq incidents_last_seen_at_idx incidents_pkey incidents_severity_idx incidents_status_idx"
actual_indexes="$(psql_exec -t -A -c "SELECT indexname FROM pg_indexes WHERE schemaname = 'reliability' AND tablename = 'incidents' ORDER BY indexname;" | tr '\n' ' ' | sed 's/ *$//')"
for idx in $expected_indexes; do
  echo "$actual_indexes" | grep -qw "$idx" || fail "expected index '$idx' not found (actual indexes: $actual_indexes)"
done
echo "  all expected indexes present: $actual_indexes"

# --------------------------------------------------------------------
# 12. Migrations are safe to rerun
# --------------------------------------------------------------------
section "12. Migrations are safe to rerun"

rerun_output="$(docker compose run --rm flyway migrate 2>&1)"
echo "$rerun_output"
echo "$rerun_output" | grep -qi "up to date\|No migration necessary" \
  || fail "rerunning 'flyway migrate' against an already-migrated schema did not report it was already up to date"
echo "  rerun confirmed safe (no-op)"

# --------------------------------------------------------------------
# 13-14. Restart PostgreSQL without deleting its volume; verify the
#        inserted incident survives
# --------------------------------------------------------------------
section "13-14. PostgreSQL restart persistence"

docker compose restart postgres >/dev/null

postgres_healthy_after_restart=false
for i in $(seq 1 20); do
  health="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || true)"
  echo "  attempt $i/20: health=$health"
  if [ "$health" = "healthy" ]; then
    postgres_healthy_after_restart=true
    break
  fi
  sleep 3
done
[ "$postgres_healthy_after_restart" = true ] || fail "postgres did not become healthy again after restart"

survived_row="$(psql_exec -t -A -F'|' -c "SELECT status, resolved_at IS NOT NULL FROM reliability.incidents WHERE id = '$incident_id';")"
[ -n "$survived_row" ] || fail "the incident inserted before the restart (id=$incident_id) is missing after restart"
echo "  original incident survived restart: $survived_row"

survived_recurred="$(psql_exec -t -A -c "SELECT status FROM reliability.incidents WHERE id = '$recurred_id';")"
[ "$survived_recurred" = "open" ] || fail "the recurred incident (id=$recurred_id) did not survive the restart with status=open, got: $survived_recurred"
echo "  recurred incident also survived restart: status=$survived_recurred"

echo ""
if [ "$phase0_fixture_present" = true ]; then
  echo "-- re-confirming the pre-existing Phase 0 verification fixture"
  echo "   survived the restart unchanged --"
  phase0_after="$(psql_exec -t -A -c "SELECT message FROM public.phase_02_verification WHERE id = 1;")"
  [ "$phase0_after" = "$phase0_before" ] || fail "public.phase_02_verification changed across the restart (before='$phase0_before' after='${phase0_after:-<empty>}')"
  echo "  public.phase_02_verification still intact: message='$phase0_after'"
else
  echo "-- Phase 0 fixture was not present before this run (fresh"
  echo "   database); nothing to re-check after restart --"
fi

# --------------------------------------------------------------------
# 15. Clean up ONLY this run's test-created data
# --------------------------------------------------------------------
section "15. Clean up only this run's test-created data"

before_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents;")"
# Not suppressed: a cleanup failure here fails the whole script, unlike
# the best-effort trap above, since this runs only on an otherwise
# fully successful pass.
psql_exec -c "$CLEANUP_SQL"
after_count="$(psql_exec -t -A -c "SELECT count(*) FROM reliability.incidents;")"
removed=$((before_count - after_count))
echo "  reliability.incidents row count: $before_count -> $after_count ($removed row(s) removed, scoped to source='$TEST_SOURCE' AND source_fingerprint LIKE '${TEST_FINGERPRINT}%')"
[ "$removed" -eq 2 ] || fail "expected to clean up exactly 2 rows created by this run (the original + the recurred incident), removed: $removed"
trap - EXIT

echo ""
echo "SUCCESS: Phase 3A persistence verification passed (migrations, schema, constraints, deduplication, restart persistence)."
