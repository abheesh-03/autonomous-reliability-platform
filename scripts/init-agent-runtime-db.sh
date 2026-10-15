#!/usr/bin/env bash
#
# init-agent-runtime-db.sh — Phase 7 dedicated, least-privileged
# checkpoint database role/schema.
#
# agent-runtime-service requires real PostgreSQL persistence (its own
# durable LangGraph checkpoint store), but it must NEVER receive the
# broad POSTGRES_USER/POSTGRES_PASSWORD role the rest of this
# platform's application code uses. This script creates a SEPARATE,
# least-privileged role (agent_runtime) and schema (agent_runtime,
# owned by that role) on the SAME PostgreSQL server/database instance
# -- never a second database, never a second server.
#
# What this role CAN do: create/read/write objects inside its own
# `agent_runtime` schema (where LangGraph's own setup() call creates
# its checkpoint_migrations/checkpoints/checkpoint_blobs/
# checkpoint_writes tables -- framework-owned, never a Flyway
# migration, see database/migrations/'s own docstring for why).
#
# What this role explicitly CANNOT do: SELECT/INSERT/UPDATE/DELETE
# anything in the `reliability` schema (reliability.incidents,
# reliability.incident_events, reliability.retrieval_chunks, or any
# other application-owned table) -- a brand-new PostgreSQL role has NO
# privileges on another role's existing objects by default (no GRANT
# to PUBLIC was ever issued anywhere in database/migrations/). This
# boundary is PROVEN, not just asserted -- see
# services/agent-runtime-service/tests/test_db_privilege_boundary.py,
# which connects AS the agent_runtime role itself and confirms each of
# those operations is actually rejected by PostgreSQL.
#
# Phase 7 correction round (finding #7): the REVOKEs below are REAL,
# useful defense in depth against a DIRECT future GRANT to this role --
# but they are NOT, and this script no longer claims they are, a
# guarantee against a future grant to PUBLIC or to a group role this
# role might someday be made a member of. PostgreSQL privilege
# composition is additive: a role's EFFECTIVE privileges are the union
# of whatever is granted directly to it, to PUBLIC, and (if INHERIT)
# to any role it is a member of. A plain `REVOKE ... FROM agent_runtime`
# removes only a DIRECT grant to agent_runtime itself; it cannot act as
# a negative "DENY" that overrides a grant arriving through PUBLIC or
# an inherited role. The REAL, authoritative guarantee is, and remains,
# the fact that no such grant exists anywhere in database/migrations/
# today, re-proven on every run of test_db_privilege_boundary.py
# against the real database -- not these REVOKE statements. The role
# attributes below (NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/
# NOBYPASSRLS/NOINHERIT) are separate, real hardening: NOINHERIT in
# particular means that even if this role were ever (by operator
# mistake) made a member of some other role, it would NOT automatically
# gain that other role's privileges without an explicit `SET ROLE`.
#
# Idempotent and safe to rerun, same .env-is-authoritative convention
# as scripts/init-webhook-secret.sh: an existing, non-empty
# AGENT_RUNTIME_DB_PASSWORD in .env is NEVER regenerated or rotated
# (that would invalidate an already-running agent-runtime-service's
# connection) -- it is simply re-applied to the real database role
# every run (ALTER ROLE ... PASSWORD is itself idempotent). Never
# prints the password to stdout/stderr, under any code path.
#
# Safe on a fresh checkout (.env may not exist yet) and on an existing
# .env (never touches POSTGRES_*/GRAFANA_*/CONTROL_PLANE_*/RETRIEVAL_*/
# any other existing variable; only ever adds, replaces, or reads its
# own AGENT_RUNTIME_DB_USER/AGENT_RUNTIME_DB_PASSWORD lines).
#
# Requires the real `postgres` Compose service already running and
# healthy (`make db-up`) -- this script runs real SQL against it via
# `docker compose exec`, the same convention every other verify-*.sh/
# init-*.sh script in this repository already uses.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env"
DB_ROLE="agent_runtime"
DB_SCHEMA="agent_runtime"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "created $ENV_FILE from .env.example"
fi

# .env is authoritative. An existing, non-empty value here is never
# regenerated -- see the file-level comment above.
existing_password="$(grep -E '^AGENT_RUNTIME_DB_PASSWORD=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"

if [ -n "$existing_password" ]; then
  password="$existing_password"
  echo "AGENT_RUNTIME_DB_PASSWORD already set in $ENV_FILE — reusing it (value not printed)."
else
  password="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new AGENT_RUNTIME_DB_PASSWORD"
  if grep -qE '^AGENT_RUNTIME_DB_PASSWORD=' "$ENV_FILE"; then
    tmp="$(mktemp)"
    sed "s|^AGENT_RUNTIME_DB_PASSWORD=.*|AGENT_RUNTIME_DB_PASSWORD=$password|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    {
      echo ""
      echo "# --- Phase 7: dedicated, least-privileged LangGraph checkpoint DB role (local dev only) ---"
      echo "# Generated by scripts/init-agent-runtime-db.sh. This role can ONLY access its own"
      echo "# 'agent_runtime' schema -- never reliability.incidents/incident_events/retrieval_chunks."
      echo "# This line is authoritative — never rotated automatically; delete it and rerun this"
      echo "# script to force a new value (the real database role's password is reset to match on"
      echo "# every run of this script, never silently left out of sync with .env)."
      echo "AGENT_RUNTIME_DB_USER=agent_runtime"
      echo "AGENT_RUNTIME_DB_PASSWORD=$password"
    } >> "$ENV_FILE"
  fi
fi

if ! grep -qE '^AGENT_RUNTIME_DB_USER=' "$ENV_FILE"; then
  # Covers the (unlikely but possible) case where a prior partial edit
  # left AGENT_RUNTIME_DB_PASSWORD set without its paired USER line.
  echo "AGENT_RUNTIME_DB_USER=agent_runtime" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"

# Phase 7 correction round (finding #6): user=agent_runtime and
# schema=agent_runtime are an ARCHITECTURAL SECURITY CONSTANT, not a
# normal operator tuning knob -- test_db_privilege_boundary.py's real
# privilege proof always connects AS exactly this role, so the
# running service (config.py's own CheckpointDbSettings.from_env,
# which applies the identical check) and this script must never
# silently diverge from it. Reject, rather than preserve, an existing
# .env value that isn't exactly "agent_runtime" -- fail closed instead
# of quietly provisioning (or leaving behind) a broader role/schema.
existing_user="$(grep -E '^AGENT_RUNTIME_DB_USER=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [ "$existing_user" != "agent_runtime" ]; then
  fail "$ENV_FILE has AGENT_RUNTIME_DB_USER=$existing_user -- the dedicated checkpoint role MUST be exactly 'agent_runtime'. Fix or remove that line and rerun."
fi
existing_schema="$(grep -E '^AGENT_RUNTIME_DB_SCHEMA=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
if [ -n "$existing_schema" ] && [ "$existing_schema" != "agent_runtime" ]; then
  fail "$ENV_FILE has AGENT_RUNTIME_DB_SCHEMA=$existing_schema -- the dedicated checkpoint schema MUST be exactly 'agent_runtime'. Fix or remove that line and rerun."
fi

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
fi
[ -n "${POSTGRES_USER:-}" ] || fail "POSTGRES_USER is not set (checked environment and $ENV_FILE)"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set (checked environment and $ENV_FILE)"

# Bounded readiness wait: `make db-up` calls this script immediately
# after `docker compose up -d`, which returns as soon as the container
# is CREATED, not once PostgreSQL is actually accepting connections --
# a real, previously-hit race, not a hypothetical one. Never waits
# more than ~30s; fails closed with a clear message rather than
# retrying forever.
attempts=10
until docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  attempts=$((attempts - 1))
  [ "$attempts" -gt 0 ] || fail "postgres did not become ready in time (run 'make db-up' first, or check 'make db-status')"
  sleep 3
done

# --------------------------------------------------------------------
# Real SQL against the real database, as the existing bootstrap
# superuser (POSTGRES_USER) -- never as the agent_runtime role itself,
# which must never be privileged enough to grant itself anything.
#
# DB_ROLE/DB_SCHEMA are fixed constants this script itself defines
# (never user input), so they are safe to interpolate directly, the
# same way every Flyway migration in this repository already hardcodes
# its own fixed "reliability" schema name with no dynamic templating.
# The PASSWORD is the one genuinely variable value here, so it is
# passed via psql's own `-v pass=` quoted-literal substitution
# (`:'pass'` below), never raw shell-interpolated into the SQL text —
# even though this script's own generated value (hex digits only)
# could never break out of a SQL string in practice, this is the same
# "don't rely on the input happening to be safe" discipline the rest
# of this platform already follows for anything SQL-adjacent.
# --------------------------------------------------------------------
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

-- Idempotent: always re-applies the current, authoritative .env
-- password, so a role created by an earlier run (or with a stale
-- password) is repaired rather than left out of sync. Quoted-literal
-- substitution (:'pass'), never raw shell interpolation.
ALTER ROLE $DB_ROLE WITH PASSWORD :'pass';

-- Phase 7 correction round (finding #7): re-applied on every run (not
-- just at CREATE ROLE) so a role provisioned by a version of this
-- script before this hardening was added is brought into line too --
-- NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS are
-- already PostgreSQL's own defaults for a plain CREATE ROLE, made
-- explicit and auditable here rather than relied upon implicitly.
-- NOINHERIT means that even if this role were ever (by operator
-- mistake) granted membership in some other role, it would NOT
-- automatically use that other role's privileges without an explicit
-- SET ROLE -- real hardening, independent of the REVOKEs below.
ALTER ROLE $DB_ROLE WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- The role owns its own schema outright -- no broader GRANT needed
-- for it to create/manage its own tables there.
CREATE SCHEMA IF NOT EXISTS $DB_SCHEMA AUTHORIZATION $DB_ROLE;

-- LangGraph's own checkpointer.setup() creates its tables with
-- UNQUALIFIED names (confirmed directly against its real source) --
-- this is what makes them land in $DB_SCHEMA, never "public" or
-- "reliability", with zero per-query schema-qualification needed by
-- this role.
ALTER ROLE $DB_ROLE SET search_path TO $DB_SCHEMA;

-- Defense-in-depth ONLY against a future DIRECT grant to this role
-- (Phase 7 correction round, finding #7 -- see this file's own header
-- comment for exactly what this does and does NOT guarantee: it is
-- NOT a override of a hypothetical future grant to PUBLIC or to an
-- inherited role). The REAL, authoritative guarantee is that no such
-- grant exists anywhere in database/migrations/ today, re-proven by
-- test_db_privilege_boundary.py against the real database on every
-- CI run. "IF EXISTS" equivalents aren't needed: REVOKE on privileges
-- that were never granted is a harmless no-op in PostgreSQL.
REVOKE ALL ON SCHEMA reliability FROM $DB_ROLE;
REVOKE ALL ON ALL TABLES IN SCHEMA reliability FROM $DB_ROLE;
SQL
echo "agent_runtime role/schema ready in PostgreSQL (search_path=$DB_SCHEMA; reliability.* access explicitly revoked)"
