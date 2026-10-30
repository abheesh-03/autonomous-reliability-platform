#!/usr/bin/env bash
#
# apply-deploy-auth-schema.sh -- Phase 17A deployment-mode counterpart
# of scripts/apply-web-console-auth-schema.sh.
#
# Reuses the EXACT SAME, reviewed, committed schema snapshot
# (services/web-console/auth-schema/schema.sql) and the exact same
# "connect AS web_console so every table it creates is owned by
# web_console from the start" fix that script's own header comment
# documents -- the only difference is which env file/Compose
# project this script reads (deploy/.env.deploy / the deployment's own
# project), so it can never touch the developer's own root .env.
#
# Must run AFTER deploy/scripts/init-deploy-secrets.sh --apply-roles
# (needs the web_console role/auth schema to already exist) and after
# `postgres` is healthy.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE="$DEPLOY_DIR/.env.deploy"
SCHEMA_FILE="services/web-console/auth-schema/schema.sql"
DB_ROLE="web_console"
AUTH_TABLES=(user session account verification organization member invitation)

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$SCHEMA_FILE" ] || fail "$SCHEMA_FILE not found"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found -- run ./deploy/scripts/init-deploy-secrets.sh first"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ -n "${POSTGRES_BOOTSTRAP_USER:-}" ] || fail "POSTGRES_BOOTSTRAP_USER is not set in $ENV_FILE"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"
[ -n "${WEB_CONSOLE_DB_PASSWORD:-}" ] || fail "WEB_CONSOLE_DB_PASSWORD is not set in $ENV_FILE"

COMPOSE=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

psql_as_web_console() {
  "${COMPOSE[@]}" exec -T -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" postgres \
    psql -v ON_ERROR_STOP=1 -U "$DB_ROLE" -d "$POSTGRES_DB" "$@"
}

already_applied="$("${COMPOSE[@]}" exec -T postgres psql -t -A -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" \
  -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'user');" | tr -d '[:space:]')"

if [ "$already_applied" = "t" ]; then
  wrongly_owned="$("${COMPOSE[@]}" exec -T postgres psql -t -A -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" -c "
    SELECT count(*) FROM pg_tables WHERE schemaname = 'auth' AND tableowner <> '$DB_ROLE';
  " | tr -d '[:space:]')"
  if [ "$wrongly_owned" = "0" ]; then
    echo "auth.user already exists and every auth.* table is already owned by $DB_ROLE -- no-op."
    exit 0
  fi
  echo "repairing ownership of $wrongly_owned auth.* table(s) to $DB_ROLE (metadata-only)..."
  for table in "${AUTH_TABLES[@]}"; do
    "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" \
      -c "ALTER TABLE auth.\"$table\" OWNER TO $DB_ROLE;"
  done
  echo "ownership repaired."
  exit 0
fi

echo "applying $SCHEMA_FILE to the auth schema, connected as $DB_ROLE..."
{ echo "SET search_path TO auth;"; cat "$SCHEMA_FILE"; } | psql_as_web_console -f -

# CORRECTION ROUND: narrowed from a blanket "GRANT SELECT ON ALL
# TABLES IN SCHEMA auth" to EXACTLY the three columns of EXACTLY the
# one table control-plane's own AuthMembershipRepository actually
# reads (see deploy/sql/01-create-runtime-roles.sql.template's own,
# matching comment for the full audit). This is a real, column-level
# Postgres GRANT, re-asserted here because that template's own grant
# only takes effect if auth.member ALREADY existed when it ran; this
# repeats the identical statement now that schema.sql has just
# created it, covering the opposite run order.
#
# CORRECTION ROUND (second pass): the matching `ALTER DEFAULT
# PRIVILEGES ... REVOKE` is re-asserted here too, for the identical
# reason -- a prior run of the OLD, blanket-granting script could
# have applied its `ALTER DEFAULT PRIVILEGES FOR ROLE web_console IN
# SCHEMA auth GRANT SELECT ON TABLES TO control_plane_app` AFTER
# schema.sql last ran (e.g. a deployment upgraded through an
# intermediate bad version), and that standing default-privilege rule
# would otherwise still apply to the table this script's OWN
# `schema.sql` application two lines above JUST created, undoing the
# narrowed grant immediately below for every table EXCEPT the one
# this script explicitly re-narrows.
echo "re-asserting control_plane_app's own column-level SELECT grant on auth.member (organizationId, userId, role only), and revoking the historical default-privilege grant..."
"${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" \
  -c 'ALTER DEFAULT PRIVILEGES FOR ROLE web_console IN SCHEMA auth REVOKE SELECT ON TABLES FROM control_plane_app;' \
  -c 'REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM control_plane_app;' \
  -c 'GRANT SELECT ("organizationId", "userId", "role") ON auth.member TO control_plane_app;'

echo "Better Auth's schema has been applied to the auth schema, owned by $DB_ROLE."
