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
# Idempotent: if the `user` table already exists in the `auth` schema,
# this is a no-op (Better Auth's own tables are presumed already
# applied). To apply a FUTURE schema change (e.g. a new better-auth
# plugin/field added to lib/auth/auth.ts), regenerate schema.sql with
# `npx @better-auth/cli generate` against a running dev stack, review
# the diff like any other schema change, and apply the DELTA manually
# or via `npx @better-auth/cli migrate` -- this script only ever
# bootstraps the FIRST application of the schema, it is not a
# general-purpose migration runner.
#
# Must run AFTER scripts/init-web-console-db.sh (needs the web_console
# role/auth schema to already exist) and AFTER `postgres` is healthy.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

SCHEMA_FILE="services/web-console/auth-schema/schema.sql"
ENV_FILE=".env"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$SCHEMA_FILE" ] || fail "$SCHEMA_FILE not found -- run scripts/init-web-console-db.sh first and regenerate it if missing"

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
  # shellcheck disable=SC1090
  source <(grep -E '^(POSTGRES_USER|POSTGRES_DB)=' "$ENV_FILE")
fi
[ -n "${POSTGRES_USER:-}" ] || fail "POSTGRES_USER is not set in $ENV_FILE"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"

already_applied="$(docker compose exec -T postgres psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'user');" | tr -d '[:space:]')"

if [ "$already_applied" = "t" ]; then
  echo "auth.user already exists -- Better Auth's schema is already applied; this script is a no-op."
  echo "For a FUTURE schema change, see this script's own header comment."
  exit 0
fi

echo "applying $SCHEMA_FILE to the auth schema..."
{ echo "SET search_path TO auth;"; cat "$SCHEMA_FILE"; } | \
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -

echo "Better Auth's schema has been applied to the auth schema."