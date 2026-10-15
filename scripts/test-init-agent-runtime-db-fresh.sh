#!/usr/bin/env bash
#
# test-init-agent-runtime-db-fresh.sh — regression test for GitHub
# Actions run #32's failure:
#
#   ERROR: schema "reliability" does not exist
#   make: *** [Makefile:97: db-up] Error 3
#
# Root cause: on a genuinely fresh PostgreSQL volume (a new CI runner,
# never a preserved developer volume), scripts/init-agent-runtime-db.sh
# runs BEFORE Flyway has ever applied a migration -- the Flyway-owned
# `reliability` schema legitimately does not exist yet at that point.
# The script's own defense-in-depth REVOKEs used to reference that
# schema unconditionally, which failed outright on a database that had
# never been migrated. This was hidden locally because a developer's
# preserved PostgreSQL volume already has `reliability` from earlier
# phases.
#
# This test proves, against a REAL, but completely ISOLATED and
# temporary PostgreSQL instance (never the developer's own persistent
# `postgres_data` volume):
#
#   1. a brand-new container has no `reliability` schema at all.
#   2. the REAL, unmodified scripts/init-agent-runtime-db.sh succeeds
#      against it anyway, and does NOT create `reliability` itself.
#   3. after Flyway applies the real migrations (so `reliability` now
#      genuinely exists), rerunning that SAME script picks the REVOKEs
#      back up (observable directly in its own stdout).
#
# Deliberately does NOT re-prove the actual privilege boundary
# (SELECT/UPDATE/INSERT denial on reliability.*) -- that remains
# services/agent-runtime-service/tests/test_db_privilege_boundary.py's
# job, run in CI after this same migration step. This test is
# specifically about the INIT SCRIPT's own behavior across the
# fresh-vs-migrated boundary, not the privilege proof itself.
#
# Isolation: uses THIS repository's own real docker-compose.yml (never
# a duplicated/forked copy) under a distinct, PID-suffixed
# COMPOSE_PROJECT_NAME and a distinct POSTGRES_PORT -- Docker Compose
# derives container/volume/network names from the project name, so
# this can never collide with, read, or modify the developer's real
# "postgres_data" volume or running stack. Cleaned up unconditionally
# (`down -v`, removing the temporary volume too) via an EXIT trap, even
# on failure. The developer's own `.env` is read (for POSTGRES_USER/
# POSTGRES_DB/the AGENT_RUNTIME_DB_PASSWORD convention) exactly the
# same way a normal `./scripts/init-agent-runtime-db.sh` run already
# would -- never deleted or reset.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f .env ] || fail ".env does not exist -- run 'make db-up' at least once first (this test reuses its real POSTGRES_USER/POSTGRES_DB/AGENT_RUNTIME_DB_PASSWORD values, never generates its own)"

export COMPOSE_PROJECT_NAME="art-fresh-db-test-$$"
# PID-derived, not a single fixed port -- avoids colliding with the
# developer's real postgres (5432) and with a stale/leftover binding
# from an unrelated prior container on one specific fixed port.
export POSTGRES_PORT="$((20000 + ($$ % 10000)))"

cleanup() {
  local exit_status=$?
  echo "-- cleanup: tearing down the isolated test project ($COMPOSE_PROJECT_NAME), including its temporary volume --" >&2
  docker compose down -v >&2 2>&1 || true
  exit "$exit_status"
}
trap cleanup EXIT

echo "=== 1. Start an isolated, temporary postgres (project=$COMPOSE_PROJECT_NAME, port=$POSTGRES_PORT) ==="
docker compose up -d postgres >/dev/null

attempts=20
until docker compose exec -T postgres pg_isready >/dev/null 2>&1; do
  attempts=$((attempts - 1))
  [ "$attempts" -gt 0 ] || fail "isolated postgres did not become ready in time"
  sleep 2
done
echo "  isolated postgres is ready"

echo "=== 2. Confirm this isolated instance genuinely has NO reliability schema yet ==="
set -a
# shellcheck disable=SC1091
source .env
set +a
schema_exists_before="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'reliability');")"
[ "$schema_exists_before" = "f" ] || fail "expected a genuinely fresh instance with no reliability schema, but it already exists -- test isolation is broken"
echo "  confirmed: reliability schema does not exist (genuinely fresh)"

echo "=== 3. Run the REAL, unmodified scripts/init-agent-runtime-db.sh against it ==="
init_output="$(./scripts/init-agent-runtime-db.sh 2>&1)" || {
  echo "$init_output" >&2
  fail "init-agent-runtime-db.sh failed against a fresh database -- this is the exact GitHub Actions run #32 regression"
}
echo "$init_output"
echo "$init_output" | grep -qi "reliability schema does not exist yet" || fail "expected the script to explicitly report skipping the REVOKEs on a fresh database, but it did not say so"
echo "  confirmed: the script succeeded and explicitly reported skipping the REVOKEs"

echo "=== 4. Confirm the script did NOT create reliability itself ==="
schema_exists_after_init="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'reliability');")"
[ "$schema_exists_after_init" = "f" ] || fail "init-agent-runtime-db.sh created the reliability schema itself -- it must remain Flyway-owned"
echo "  confirmed: reliability still does not exist -- the script never created it"

echo "=== 5. Confirm the agent_runtime role/schema were still provisioned correctly ==="
role_exists="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_runtime');")"
[ "$role_exists" = "t" ] || fail "the agent_runtime role was not created even though reliability was legitimately absent"
agent_schema_exists="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'agent_runtime');")"
[ "$agent_schema_exists" = "t" ] || fail "the agent_runtime schema was not created even though reliability was legitimately absent"
echo "  confirmed: agent_runtime role and schema exist regardless of reliability's absence"

echo "=== 6. Apply the REAL Flyway migrations (reliability now genuinely exists) ==="
docker compose run --rm flyway migrate >/dev/null
schema_exists_after_migrate="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'reliability');")"
[ "$schema_exists_after_migrate" = "t" ] || fail "Flyway did not create the reliability schema -- cannot continue this test"
echo "  confirmed: reliability now exists (via Flyway, never via init-agent-runtime-db.sh)"

echo "=== 7. Rerun the SAME script -- it must now pick the REVOKEs back up ==="
rerun_output="$(./scripts/init-agent-runtime-db.sh 2>&1)" || {
  echo "$rerun_output" >&2
  fail "init-agent-runtime-db.sh failed after migrations were applied"
}
echo "$rerun_output"
echo "$rerun_output" | grep -qi "revoked agent_runtime access" || fail "expected the script to report running the REVOKEs now that reliability exists, but it did not say so"
echo "  confirmed: the script now runs (and reports running) the REVOKEs, now that reliability genuinely exists"

echo ""
echo "PASS: scripts/init-agent-runtime-db.sh succeeds on a genuinely fresh database (no reliability schema), never creates reliability itself, and correctly resumes running its REVOKEs once Flyway migrations exist -- the exact GitHub Actions run #32 regression is fixed."
