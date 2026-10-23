#!/usr/bin/env bash
#
# apply-web-console-auth-schema.sh — Phase 14: applies Better Auth's
# own, reviewed, committed schema snapshot
# (services/web-console/auth-schema/schema.sql) to the dedicated `auth`
# schema scripts/init-web-console-db.sh created.
#
# Why this isn't a Flyway migration: Better Auth owns this schema's
# evolution, not this platform's own Flyway-managed migrations (Gate 2:
# "Keep auth persistence clearly separated from existing Flyway-owned
# reliability data"). schema.sql is a real, reviewed snapshot --
# generated once via `npx @better-auth/cli generate` against a live,
# empty database and committed for review -- never auto-generated and
# silently applied on every container startup (Gate 2: "never auto-sync
# or destructively migrate production schemas on startup").
#
# Post-commit fix (CI preflight, Gate 2 -- independently reproduced):
# this script used to apply schema.sql connected as $POSTGRES_USER, the
# SHARED, broad role every other Flyway-owned table in this platform
# uses. Owning the `auth` SCHEMA (scripts/init-web-console-db.sh's own
# `CREATE SCHEMA auth AUTHORIZATION web_console`) does NOT grant any
# privilege on a TABLE a DIFFERENT role creates inside it -- PostgreSQL
# privileges are per-object, not inherited from the containing schema.
# $POSTGRES_USER's own Docker-image bootstrap role is typically a
# genuine superuser, which silently bypasses every privilege check and
# lets `CREATE TABLE` succeed anyway -- so this previously produced
# every one of Better Auth's own tables OWNED BY $POSTGRES_USER, with
# `web_console` (the role Better Auth's real Pool connection, and
# control-plane's own Blocker-4 AuthMembershipRepository cross-schema
# read, both actually use) holding NO select/insert/update/delete
# privilege on any of them at all -- confirmed directly, independent of
# this fix, on a disposable instance: `permission denied for table
# user` on both a plain SELECT and an INSERT, connected as web_console.
# Every one of this platform's own real sign-up/sign-in/organization-
# creation/Blocker-4-membership-recheck database operations would fail
# outright the moment either was genuinely attempted against a
# database whose auth tables were created this way.
#
# FIXED: this script now connects AS web_console itself to apply the
# schema -- `web_console` already OWNS the `auth` schema, so it
# inherently has CREATE privilege there, and every table it creates is
# therefore owned by it FROM THE MOMENT OF CREATION (preferred over a
# broad, after-the-fact GRANT, which would have to be kept in lockstep
# with Better Auth's own schema.sql by hand forever). This also makes
# scripts/init-web-console-db.sh's own `ALTER DEFAULT PRIVILEGES FOR
# ROLE web_console IN SCHEMA auth GRANT SELECT ON TABLES TO
# $POSTGRES_USER` (Blocker 4's control-plane read grant) finally take
# effect as originally intended -- it was always keyed to tables
# CREATED BY web_console, which never happened before this fix.
#
# REPAIR PATH: if this schema was already applied by the OLD, buggy
# version of this script (auth.user exists, but is NOT owned by
# web_console), this script now detects that and safely reassigns
# ownership of every existing auth.* table to web_console via `ALTER
# TABLE ... OWNER TO` -- metadata-only, preserves every existing row,
# never drops or recreates anything, and is itself idempotent (a
# repeated run is a no-op once ownership is already correct).
#
# Idempotent either way: if every `auth.*` table already exists AND is
# already owned by web_console, this is a genuine no-op. To apply a
# FUTURE schema change (e.g. a new better-auth plugin/field added to
# lib/auth/auth.ts), regenerate schema.sql with `npx @better-auth/cli
# generate` against a running dev stack, review the diff like any
# other schema change, and apply the DELTA manually or via `npx
# @better-auth/cli migrate` (connected as web_console) -- this script
# only ever bootstraps the FIRST application of the schema (or repairs
# a wrongly-owned one), it is not a general-purpose migration runner.
#
# Must run AFTER scripts/init-web-console-db.sh (needs the web_console
# role/auth schema, and its own generated WEB_CONSOLE_DB_PASSWORD, to
# already exist) and AFTER `postgres` is healthy.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

SCHEMA_FILE="services/web-console/auth-schema/schema.sql"
ENV_FILE=".env"
DB_ROLE="web_console"

# The seven tables services/web-console/auth-schema/schema.sql itself
# creates -- kept as an explicit, reviewed list (never introspected
# generically from information_schema) so a repair run only ever
# touches exactly these known, expected objects, never anything this
# script wasn't specifically written to own.
AUTH_TABLES=(user session account verification organization member invitation)

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$SCHEMA_FILE" ] || fail "$SCHEMA_FILE not found -- run scripts/init-web-console-db.sh first and regenerate it if missing"

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ] || [ -z "${WEB_CONSOLE_DB_PASSWORD:-}" ]; then
  # Plain dot-sourcing of the real file -- matches
  # scripts/init-agent-runtime-db.sh's own proven precedent. A prior
  # `source <(grep ... "$ENV_FILE")` (process substitution) relied on
  # /dev/fd, which is not reliably available in every shell/`make`
  # recipe invocation context (confirmed failing when this script runs
  # as a `make db-up` recipe line) -- sourcing the file directly has no
  # such dependency.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
[ -n "${POSTGRES_USER:-}" ] || fail "POSTGRES_USER is not set in $ENV_FILE"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"
[ -n "${WEB_CONSOLE_DB_PASSWORD:-}" ] || fail "WEB_CONSOLE_DB_PASSWORD is not set in $ENV_FILE -- run scripts/init-web-console-db.sh first"

# Never logged, never printed -- passed to `docker compose exec` ONLY
# via its own environment (-e), never as a command-line argument that
# would appear in `docker compose ps`/shell history/process listings.
psql_as_web_console() {
  docker compose exec -T -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" postgres \
    psql -v ON_ERROR_STOP=1 -U "$DB_ROLE" -d "$POSTGRES_DB" "$@"
}

already_applied="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'user');" | tr -d '[:space:]')"

if [ "$already_applied" = "t" ]; then
  wrongly_owned="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT count(*) FROM pg_tables WHERE schemaname = 'auth' AND tableowner <> '$DB_ROLE';
  " | tr -d '[:space:]')"

  if [ "$wrongly_owned" = "0" ]; then
    echo "auth.user already exists and every auth.* table is already owned by $DB_ROLE -- this script is a no-op."
    echo "For a FUTURE schema change, see this script's own header comment."
    exit 0
  fi

  echo "auth.user already exists, but $wrongly_owned auth.* table(s) are NOT owned by $DB_ROLE (the pre-fix script's own bug) -- repairing ownership in place (metadata-only; no row is read, written, or dropped)..."
  for table in "${AUTH_TABLES[@]}"; do
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -c "ALTER TABLE auth.\"$table\" OWNER TO $DB_ROLE;"
  done
  echo "ownership repaired: every auth.* table is now owned by $DB_ROLE."
  exit 0
fi

echo "applying $SCHEMA_FILE to the auth schema, connected as $DB_ROLE (so every table it creates is owned by $DB_ROLE from the start)..."
{ echo "SET search_path TO auth;"; cat "$SCHEMA_FILE"; } | psql_as_web_console -f -

echo "Better Auth's schema has been applied to the auth schema, owned by $DB_ROLE."