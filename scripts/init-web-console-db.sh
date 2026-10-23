#!/usr/bin/env bash
#
# init-web-console-db.sh — Phase 14 dedicated, least-privileged
# authentication database role/schema, plus the two signing secrets
# web-console needs (BETTER_AUTH_SECRET, SERVICE_ASSERTION_SIGNING_SECRET).
#
# Mirrors scripts/init-agent-runtime-db.sh's EXACT precedent: a
# brand-new PostgreSQL role (web_console) that owns its own schema
# (auth) on the SAME database/server -- never a second database, never
# the shared POSTGRES_USER/POSTGRES_PASSWORD role control-plane/
# retrieval-service use. Better Auth's own tables (user, session,
# account, verification, organization, member, invitation --
# services/web-console/auth-schema/schema.sql) land in this `auth`
# schema because the role's own search_path is set to it at the ROLE
# level below -- the same mechanism that makes LangGraph's checkpoint
# tables land in agent_runtime's own schema, never a per-query
# schema-qualification the application code has to get right.
#
# What this role explicitly CANNOT do: SELECT/INSERT/UPDATE/DELETE
# anything in the `reliability` schema -- a brand-new role has no
# privileges on another role's existing objects by default, and this
# script's defense-in-depth REVOKEs (conditional on that schema
# existing yet, same fresh-database handling as
# init-agent-runtime-db.sh) make that explicit.
#
# Generated secrets (.env is authoritative, never rotated once set --
# same convention as every other secret-generating script in this
# repository):
#   - WEB_CONSOLE_DB_PASSWORD: this role's real database password.
#   - BETTER_AUTH_SECRET: Better Auth's own session/cookie signing key.
#   - SERVICE_ASSERTION_SIGNING_SECRET: the HS256 key web-console uses
#     to sign the short-lived service assertion control-plane/
#     agent-runtime-service verify (Gate 5) -- shared across exactly
#     those three services, never exposed to a browser.
#
# Idempotent and safe to rerun. Never prints a secret value.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env"
DB_ROLE="web_console"
DB_SCHEMA="auth"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "created $ENV_FILE from .env.example"
fi

generate_secret_if_absent() {
  # $1 = env var name, $2 = human-readable label for the log line
  local var_name="$1" label="$2" existing
  existing="$(grep -E "^${var_name}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  if [ -n "$existing" ]; then
    echo "$existing"
    echo "$var_name already set in $ENV_FILE — reusing it (value not printed)." >&2
    return
  fi
  local value
  value="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new $label" >&2
  if grep -qE "^${var_name}=" "$ENV_FILE"; then
    tmp="$(mktemp)"
    sed "s|^${var_name}=.*|${var_name}=${value}|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    {
      echo ""
      echo "${var_name}=${value}"
    } >> "$ENV_FILE"
  fi
  echo "$value"
}

password="$(generate_secret_if_absent WEB_CONSOLE_DB_PASSWORD "WEB_CONSOLE_DB_PASSWORD")"
better_auth_secret="$(generate_secret_if_absent BETTER_AUTH_SECRET "BETTER_AUTH_SECRET")"
assertion_secret="$(generate_secret_if_absent SERVICE_ASSERTION_SIGNING_SECRET "SERVICE_ASSERTION_SIGNING_SECRET")"

if ! grep -qE '^WEB_CONSOLE_DB_USER=' "$ENV_FILE"; then
  echo "WEB_CONSOLE_DB_USER=web_console" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
  # shellcheck disable=SC1090
  source <(grep -E '^(POSTGRES_USER|POSTGRES_DB)=' "$ENV_FILE")
fi
[ -n "${POSTGRES_USER:-}" ] || fail "POSTGRES_USER is not set in $ENV_FILE"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v pass="$password" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$DB_ROLE') THEN
    CREATE ROLE $DB_ROLE LOGIN
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
END
\$\$;

ALTER ROLE $DB_ROLE WITH PASSWORD :'pass';
ALTER ROLE $DB_ROLE WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- The role owns its own schema outright -- logically separate from
-- the Flyway-owned "reliability" schema (see
-- docs/architecture/phase-14-security-multitenancy.md's "schema
-- separation" note for why there is no literal cross-schema FK).
CREATE SCHEMA IF NOT EXISTS $DB_SCHEMA AUTHORIZATION $DB_ROLE;
ALTER ROLE $DB_ROLE SET search_path TO $DB_SCHEMA;

-- Phase 14 correction round, BLOCKER 4: control-plane's own
-- POSTGRES_USER role needs real, read-only, cross-schema access to
-- EXACTLY two Better Auth tables ($DB_SCHEMA.member, $DB_SCHEMA."user")
-- so it can independently re-check a decision-time actor's CURRENT
-- membership/role -- never trusting a signed assertion's claims alone
-- as proof of present-day membership (core/authz.py's own
-- AuthMembershipRepository is the only thing that ever uses this
-- grant; it issues SELECT-only queries, never INSERT/UPDATE/DELETE).
-- GRANT SELECT covers tables that already exist (idempotent re-run);
-- ALTER DEFAULT PRIVILEGES covers tables $DB_ROLE creates LATER (this
-- script runs BEFORE scripts/apply-web-console-auth-schema.sh ever
-- creates them) -- both are needed, neither alone is sufficient.
GRANT USAGE ON SCHEMA $DB_SCHEMA TO $POSTGRES_USER;
GRANT SELECT ON ALL TABLES IN SCHEMA $DB_SCHEMA TO $POSTGRES_USER;
ALTER DEFAULT PRIVILEGES FOR ROLE $DB_ROLE IN SCHEMA $DB_SCHEMA GRANT SELECT ON TABLES TO $POSTGRES_USER;

-- Defense-in-depth ONLY against a future DIRECT grant to this role --
-- see scripts/init-agent-runtime-db.sh's own header comment for
-- exactly what this does and does not guarantee. The authoritative
-- proof that this role cannot read/write reliability.* is that no
-- grant to it (or to PUBLIC) exists anywhere in database/migrations/.
SELECT EXISTS (
  SELECT 1 FROM pg_namespace WHERE nspname = 'reliability'
) AS reliability_schema_exists \gset
\if :reliability_schema_exists
REVOKE ALL ON SCHEMA reliability FROM $DB_ROLE;
REVOKE ALL ON ALL TABLES IN SCHEMA reliability FROM $DB_ROLE;
\echo 'reliability schema exists -- revoked web_console access from it (defense in depth)'
\else
\echo 'reliability schema does not exist yet -- skipping the REVOKEs; default PostgreSQL privileges already grant web_console no access to it'
\endif
SQL

echo "web_console role/schema ready in PostgreSQL (search_path=$DB_SCHEMA)."
echo "Next: run ./scripts/apply-web-console-auth-schema.sh to create Better Auth's own tables in that schema."