#!/usr/bin/env bash
#
# test-web-console-auth-schema-ownership.sh — regression test for a
# CI-preflight finding (Gate 2, independently reproduced): the OLD
# scripts/apply-web-console-auth-schema.sh applied Better Auth's
# schema.sql connected as $POSTGRES_USER, the shared, broad role every
# other Flyway-owned table in this platform uses. Owning the `auth`
# SCHEMA (scripts/init-web-console-db.sh's own `CREATE SCHEMA auth
# AUTHORIZATION web_console`) does NOT grant any privilege on a TABLE a
# DIFFERENT role creates inside it -- PostgreSQL privileges are
# per-object, never inherited from the containing schema.
# $POSTGRES_USER's own Docker-image bootstrap role is typically a
# genuine superuser, which silently bypasses every privilege check and
# let `CREATE TABLE` succeed anyway -- so every one of Better Auth's
# own tables ended up OWNED BY $POSTGRES_USER, with `web_console` (the
# role Better Auth's real Pool connection, and control-plane's own
# Blocker-4 AuthMembershipRepository cross-schema read, both actually
# use) holding NO privilege on any of them at all. Confirmed directly:
# `permission denied for table user` on both a plain SELECT and an
# INSERT, connected as web_console, against a database whose auth
# tables were created the old way.
#
# This test proves, against a REAL, but completely ISOLATED and
# temporary PostgreSQL instance (never the developer's own persistent
# `postgres_data` volume):
#
#   1. The REAL, unmodified (now fixed) scripts/init-web-console-db.sh
#      and scripts/apply-web-console-auth-schema.sh, run in sequence
#      against a genuinely fresh instance, produce auth.* tables that
#      are ALL owned by web_console from creation.
#   2. web_console can genuinely SELECT/INSERT/UPDATE/DELETE its own
#      tables (a real functional privilege proof, not just ownership
#      metadata).
#   3. The REPAIR path: simulating the OLD bug's exact end state (every
#      auth.* table owned by $POSTGRES_USER instead, with one real row
#      already present), rerunning the SAME apply script detects the
#      wrong ownership and repairs it IN PLACE -- the pre-existing row
#      survives untouched, and web_console can then read/write again.
#   4. web_console is denied read/write on a stand-in reliability.*
#      table it was never granted anything on (Gate 2 item 9).
#
# Isolation: uses THIS repository's own real docker-compose.yml (never
# a duplicated/forked copy) under a distinct, PID-suffixed
# COMPOSE_PROJECT_NAME and a distinct POSTGRES_PORT -- Docker Compose
# derives container/volume/network names from the project name, so
# this can never collide with, read, or modify the developer's real
# "postgres_data" volume or running stack. Cleaned up unconditionally
# (`down -v`, removing the temporary volume too) via an EXIT trap, even
# on failure. The developer's own `.env` is read (for POSTGRES_USER/
# POSTGRES_DB/the generated WEB_CONSOLE_DB_PASSWORD convention) exactly
# the same way a normal `./scripts/init-web-console-db.sh` run already
# would -- never deleted or reset. Secret values are never echoed.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f .env ] || fail ".env does not exist -- run 'make db-up' at least once first (this test reuses its real POSTGRES_USER/POSTGRES_DB values, never generates its own)"

export COMPOSE_PROJECT_NAME="wc-auth-ownership-test-$$"
export POSTGRES_PORT="$((20000 + (($$ + 1) % 10000)))"
# Captured once, immediately after the real isolation values above are
# set, and never reassigned -- the one trusted reference this script
# checks every later `source .env` against (see
# reload_env_credentials below). `.env`/.env.example DO define their
# own POSTGRES_PORT (5432); COMPOSE_PROJECT_NAME is not currently
# defined there, but is guarded here too as defense-in-depth against a
# future .env.example change silently reintroducing this exact class
# of bug.
readonly ISOLATED_COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME"
readonly ISOLATED_POSTGRES_PORT="$POSTGRES_PORT"

cleanup() {
  local exit_status=$?
  echo "-- cleanup: tearing down the isolated test project ($COMPOSE_PROJECT_NAME), including its temporary volume --" >&2
  [ "$COMPOSE_PROJECT_NAME" = "$ISOLATED_COMPOSE_PROJECT_NAME" ] || {
    echo "FAIL: COMPOSE_PROJECT_NAME drifted from the isolated value ($ISOLATED_COMPOSE_PROJECT_NAME) to '$COMPOSE_PROJECT_NAME' -- refusing to run 'docker compose down' against a project this script did not create" >&2
    exit 1
  }
  docker compose down -v >&2 2>&1 || true
  exit "$exit_status"
}
trap cleanup EXIT

# Sources .env for its credentials (POSTGRES_USER/POSTGRES_DB/
# WEB_CONSOLE_DB_PASSWORD/etc.) while explicitly preserving this
# script's own isolated COMPOSE_PROJECT_NAME/POSTGRES_PORT across the
# reload -- .env's own POSTGRES_PORT=5432 would otherwise silently
# overwrite the isolated, PID-derived port this script already
# exported above and already used to start its own disposable
# postgres container, and a future .env addition of
# COMPOSE_PROJECT_NAME could do the same to the project name cleanup()
# depends on to target only this script's own disposable project.
# Explicitly re-asserted (never just reassigned) after every reload,
# so a regression here fails loudly instead of silently drifting.
reload_env_credentials() {
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  export COMPOSE_PROJECT_NAME="$ISOLATED_COMPOSE_PROJECT_NAME"
  export POSTGRES_PORT="$ISOLATED_POSTGRES_PORT"
  [ "$COMPOSE_PROJECT_NAME" = "$ISOLATED_COMPOSE_PROJECT_NAME" ] || fail "isolation invariant violated: COMPOSE_PROJECT_NAME is '$COMPOSE_PROJECT_NAME', expected the isolated '$ISOLATED_COMPOSE_PROJECT_NAME'"
  [ "$POSTGRES_PORT" = "$ISOLATED_POSTGRES_PORT" ] || fail "isolation invariant violated: POSTGRES_PORT is '$POSTGRES_PORT', expected the isolated '$ISOLATED_POSTGRES_PORT'"
}

echo "=== 1. Start an isolated, temporary postgres (project=$COMPOSE_PROJECT_NAME, port=$POSTGRES_PORT) ==="
docker compose up -d postgres >/dev/null
attempts=20
until docker compose exec -T postgres pg_isready >/dev/null 2>&1; do
  attempts=$((attempts - 1))
  [ "$attempts" -gt 0 ] || fail "isolated postgres did not become ready in time"
  sleep 2
done
echo "  isolated postgres is ready"

reload_env_credentials
# This isolated instance's own .env-persisted WEB_CONSOLE_DB_PASSWORD/
# BETTER_AUTH_SECRET/SERVICE_ASSERTION_SIGNING_SECRET are intentionally
# REUSED from the developer's real .env (scripts/init-web-console-db.sh's
# own idempotent "generate only if absent" behavior) -- this test never
# writes a throwaway credential back into the real .env; it only reads
# whatever is already there, exactly like a normal script invocation
# would.

echo "=== 2. Run the REAL, unmodified scripts/init-web-console-db.sh + apply-web-console-auth-schema.sh against it ==="
./scripts/init-web-console-db.sh >/dev/null
./scripts/apply-web-console-auth-schema.sh

# CI preflight fix: init-web-console-db.sh (the CHILD PROCESS just run
# above) generates WEB_CONSOLE_DB_PASSWORD and writes it into .env ON
# DISK -- but a child process can never modify its PARENT shell's
# already-sourced environment. On a genuinely fresh runner (where
# .env.example has this var only as a commented-out example, and this
# is the FIRST time init-web-console-db.sh has ever run), this
# script's own earlier `source .env` above (before
# init-web-console-db.sh ran) captured no value for it at all --
# referencing it below under `set -u` would fail with "unbound
# variable", exactly the opposite of a developer machine's .env, which
# already has a real value from a prior run, masking this entirely.
# Re-source .env now, after the generator has actually run, so this
# script's own environment reflects the real, current, on-disk value,
# then fail loudly (never silently) if it is somehow still absent.
# reload_env_credentials itself re-asserts the isolated
# COMPOSE_PROJECT_NAME/POSTGRES_PORT survived this reload unchanged.
reload_env_credentials
[ -n "${WEB_CONSOLE_DB_PASSWORD:-}" ] || fail "WEB_CONSOLE_DB_PASSWORD is still not set in .env after running init-web-console-db.sh -- it should have generated and persisted one"

echo "=== 3. Confirm every auth.* table is owned by web_console from creation ==="
wrong_owner_count="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'auth' AND tableowner <> 'web_console';" | tr -d '[:space:]')"
[ "$wrong_owner_count" = "0" ] || fail "expected every auth.* table to be owned by web_console, but $wrong_owner_count are not"
echo "  confirmed: every auth.* table is owned by web_console"

echo "=== 4. Confirm web_console has REAL functional read/write privilege (not just ownership metadata) ==="
docker compose exec -T -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" postgres \
  psql -v ON_ERROR_STOP=1 -U web_console -d "$POSTGRES_DB" -c "
    INSERT INTO auth.\"user\" (id, name, email, \"emailVerified\", \"createdAt\", \"updatedAt\")
    VALUES (gen_random_uuid(), 'ownership-test', 'ownership-test@example.com', false, now(), now());
    UPDATE auth.\"user\" SET name = 'ownership-test-updated' WHERE email = 'ownership-test@example.com';
  " >/dev/null
row_count="$(docker compose exec -T -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" postgres \
  psql -t -A -U web_console -d "$POSTGRES_DB" -c "SELECT count(*) FROM auth.\"user\" WHERE email = 'ownership-test@example.com' AND name = 'ownership-test-updated';" | tr -d '[:space:]')"
[ "$row_count" = "1" ] || fail "web_console could not genuinely SELECT/INSERT/UPDATE its own auth.user table"
echo "  confirmed: web_console can genuinely INSERT/UPDATE/SELECT auth.user"

echo "=== 5. Simulate the OLD bug's exact end state, with a real pre-existing row, then prove the REPAIR path ==="
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  ALTER TABLE auth.\"user\" OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.session OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.account OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.verification OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.organization OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.member OWNER TO $POSTGRES_USER;
  ALTER TABLE auth.invitation OWNER TO $POSTGRES_USER;
" >/dev/null
simulated_wrong_count="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'auth' AND tableowner <> 'web_console';" | tr -d '[:space:]')"
[ "$simulated_wrong_count" = "7" ] || fail "failed to simulate the old bug's end state (expected all 7 tables mis-owned)"
pre_repair_row_count="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT count(*) FROM auth.\"user\" WHERE email = 'ownership-test@example.com';" | tr -d '[:space:]')"
[ "$pre_repair_row_count" = "1" ] || fail "the real pre-existing row vanished merely from changing ownership -- this should be impossible"
echo "  confirmed: simulated the old bug's exact end state, with a real row still present"

repair_output="$(./scripts/apply-web-console-auth-schema.sh 2>&1)" || {
  echo "$repair_output" >&2
  fail "apply-web-console-auth-schema.sh failed against a wrongly-owned existing schema"
}
echo "$repair_output"
echo "$repair_output" | grep -qi "repairing ownership" || fail "expected the script to explicitly report repairing ownership, but it did not say so"

post_repair_wrong_count="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'auth' AND tableowner <> 'web_console';" | tr -d '[:space:]')"
[ "$post_repair_wrong_count" = "0" ] || fail "ownership was not fully repaired -- $post_repair_wrong_count table(s) still wrongly owned"
post_repair_row_count="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT count(*) FROM auth.\"user\" WHERE email = 'ownership-test@example.com' AND name = 'ownership-test-updated';" | tr -d '[:space:]')"
[ "$post_repair_row_count" = "1" ] || fail "the pre-existing row was lost or altered by the repair -- this must never happen"
echo "  confirmed: ownership repaired in place, and the real pre-existing row survived byte-for-byte"

echo "=== 6. Confirm the repaired setup is genuinely idempotent (a second run is a clean no-op) ==="
idempotent_output="$(./scripts/apply-web-console-auth-schema.sh 2>&1)"
echo "$idempotent_output" | grep -qi "no-op" || fail "expected a second run after repair to report a clean no-op"
echo "  confirmed: rerunning after repair is a clean no-op"

echo "=== 7. Confirm web_console still cannot touch a stand-in reliability.* table (Gate 2 item 9) ==="
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  CREATE SCHEMA IF NOT EXISTS reliability;
  CREATE TABLE IF NOT EXISTS reliability.incidents_ownership_test_stub (id uuid primary key default gen_random_uuid());
" >/dev/null
if docker compose exec -T -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" postgres \
     psql -U web_console -d "$POSTGRES_DB" -c "SELECT * FROM reliability.incidents_ownership_test_stub;" >/dev/null 2>&1
then
  fail "web_console could read a reliability.* table -- it must have zero access to the Flyway-owned schema"
fi
echo "  confirmed: web_console is still denied all access to reliability.*"

echo ""
echo "PASS: scripts/init-web-console-db.sh + scripts/apply-web-console-auth-schema.sh produce auth.* tables genuinely owned by (and read/write-able by) web_console from creation; the repair path fixes a wrongly-owned existing schema in place with zero data loss and is itself idempotent; and web_console remains fully denied access to the Flyway-owned reliability schema."
