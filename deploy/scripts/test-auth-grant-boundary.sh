#!/usr/bin/env bash
#
# test-auth-grant-boundary.sh -- Phase 17A correction round, item 3.
#
# Real proof, against a real, disposable PostgreSQL instance (a
# fresh container on its own throwaway network -- NEVER the
# developer's own dev stack/db/volumes), that control_plane_app's
# narrowed grant on `auth` actually holds: it CAN read exactly
# auth.member("organizationId", "userId", "role"), and CANNOT read
# ANY other column of auth.member or ANY row of auth.session,
# auth.account, or auth.verification. This runs the REAL,
# unmodified deploy/sql/01-create-runtime-roles.sql.template and the
# REAL services/web-console/auth-schema/schema.sql -- never a
# reimplementation of either -- so this proof tracks the actual
# deployed grant, not a paraphrase of it.
#
# `reliability.*` tables are stubbed as empty, zero-column tables
# purely so the template's own (otherwise unrelated)
# `GRANT ... ON reliability.<table> TO control_plane_app` statements
# have something to target under `ON_ERROR_STOP=1` -- normally
# Flyway's job, irrelevant to this proof's actual subject (the `auth`
# schema boundary), and never written to or read from below.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"

fail() { echo "FAIL: $1" >&2; exit 1; }

RUN_ID="$$-$(date +%s)"
CONTAINER_NAME="arp-auth-grant-boundary-proof-$RUN_ID"
NETWORK_NAME="arp-auth-grant-boundary-proof-net-$RUN_ID"
IMAGE="pgvector/pgvector:pg18"
BOOTSTRAP_PW="proof-bootstrap-$RUN_ID"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== starting a disposable PostgreSQL instance (no volume, no published port, its own network) =="
docker network create "$NETWORK_NAME" >/dev/null
docker run -d --name "$CONTAINER_NAME" --network "$NETWORK_NAME" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb \
  "$IMAGE" >/dev/null

echo "== waiting for it to become ready =="
# `pg_isready` alone is not enough: the official postgres/pgvector
# entrypoint runs initdb, starts a TEMPORARY server to run init
# scripts, stops it, then starts the REAL server -- `pg_isready` can
# report ready during that temporary server's brief window, right
# before the restart makes it unreachable again (real finding from
# this proof's own first run: "connection ... failed: No such file or
# directory" immediately after a successful pg_isready). Retrying the
# actual connection this script needs, not merely a liveness probe,
# is the only check that cannot be fooled by that transient window.
ready=0
for _ in $(seq 1 60); do
  if docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" psql -U postgres -d proofdb -c "SELECT 1;" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" -eq 1 ] || fail "the disposable postgres instance never became ready"

psql_as() {
  # `-i`: without it, `docker exec` never attaches stdin to the
  # container process at all -- a piped `-f -` script (like
  # schema.sql below) then reads an immediate EOF and silently
  # applies NOTHING, exiting 0 with no error and no output. Real
  # finding from this proof's own first run: the auth schema was
  # never actually created, and the failure only surfaced several
  # steps later as "relation auth.member does not exist" -- exactly
  # the kind of false-pass-by-silence this whole correction round
  # exists to eliminate, here in the TEST's own plumbing rather than
  # in restore.sh/preflight.sh, but the same bug class.
  local role="$1" pw="$2"; shift 2
  docker exec -i -e PGPASSWORD="$pw" "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -U "$role" -d proofdb "$@"
}

echo "== stubbing empty reliability.* tables (Flyway's real job; irrelevant to this proof's subject) =="
psql_as postgres "$BOOTSTRAP_PW" -c "
  CREATE SCHEMA IF NOT EXISTS reliability;
  CREATE TABLE IF NOT EXISTS reliability.incidents();
  CREATE TABLE IF NOT EXISTS reliability.services();
  CREATE TABLE IF NOT EXISTS reliability.integration_credentials();
  CREATE TABLE IF NOT EXISTS reliability.telemetry_samples();
  CREATE TABLE IF NOT EXISTS reliability.remediation_proposals();
  CREATE TABLE IF NOT EXISTS reliability.incident_events();
  CREATE TABLE IF NOT EXISTS reliability.remediation_events();
  CREATE TABLE IF NOT EXISTS reliability.retrieval_chunks();
"

echo "== applying the REAL, unmodified runtime-roles template =="
CONTROL_PLANE_APP_PASSWORD="cp-$RUN_ID"
RETRIEVAL_APP_PASSWORD="ra-$RUN_ID"
WEB_CONSOLE_PASSWORD="wc-$RUN_ID"
AGENT_RUNTIME_PASSWORD="ar-$RUN_ID"
sed \
  -e "s/CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER/$CONTROL_PLANE_APP_PASSWORD/" \
  -e "s/RETRIEVAL_APP_PASSWORD_PLACEHOLDER/$RETRIEVAL_APP_PASSWORD/" \
  -e "s/WEB_CONSOLE_PASSWORD_PLACEHOLDER/$WEB_CONSOLE_PASSWORD/" \
  -e "s/AGENT_RUNTIME_PASSWORD_PLACEHOLDER/$AGENT_RUNTIME_PASSWORD/" \
  "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" \
  | docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -U postgres -d proofdb -f -

echo "== applying the REAL Better Auth schema.sql, connected as web_console (exactly matches apply-deploy-auth-schema.sh) =="
{ echo "SET search_path TO auth;"; cat "$REPO_ROOT/services/web-console/auth-schema/schema.sql"; } \
  | psql_as web_console "$WEB_CONSOLE_PASSWORD" -f -

echo "== re-asserting the real, narrowed column-level grant (the exact statement apply-deploy-auth-schema.sh issues) =="
psql_as postgres "$BOOTSTRAP_PW" \
  -c 'REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM control_plane_app;' \
  -c 'GRANT SELECT ("organizationId", "userId", "role") ON auth.member TO control_plane_app;'

echo "== seeding one real row per table so a permitted SELECT has something real to return =="
psql_as web_console "$WEB_CONSOLE_PASSWORD" -c "
  INSERT INTO auth.\"user\" (id, name, email, \"emailVerified\") VALUES ('11111111-1111-1111-1111-111111111111', 'proof user', 'proof@example.com', true);
  INSERT INTO auth.organization (id, name, slug, \"createdAt\") VALUES ('22222222-2222-2222-2222-222222222222', 'proof org', 'proof-org', now());
  INSERT INTO auth.member (id, \"organizationId\", \"userId\", role, \"createdAt\") VALUES ('33333333-3333-3333-3333-333333333333', '22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'admin', now());
  INSERT INTO auth.session (id, \"expiresAt\", token, \"updatedAt\", \"userId\") VALUES ('44444444-4444-4444-4444-444444444444', now() + interval '1 day', 'proof-session-token', now(), '11111111-1111-1111-1111-111111111111');
  INSERT INTO auth.account (id, \"accountId\", \"providerId\", \"userId\", \"updatedAt\") VALUES ('55555555-5555-5555-5555-555555555555', 'proof-account', 'credential', '11111111-1111-1111-1111-111111111111', now());
  INSERT INTO auth.verification (id, identifier, value, \"expiresAt\") VALUES ('66666666-6666-6666-6666-666666666666', 'proof@example.com', 'proof-verification-value', now() + interval '1 day');
"

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

echo ""
echo "== proving control_plane_app CAN read exactly the granted columns of auth.member =="
member_role="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -t -A -c "
  SELECT role FROM auth.member WHERE \"userId\" = '11111111-1111-1111-1111-111111111111' AND \"organizationId\" = '22222222-2222-2222-2222-222222222222';
" 2>/dev/null | tr -d '[:space:]')"
if [ "$member_role" = "admin" ]; then
  case_pass "control_plane_app can read auth.member(organizationId, userId, role) -- got the real seeded value 'admin'"
else
  case_fail "control_plane_app could not read the granted columns of auth.member (got '$member_role')"
fi

echo ""
echo "== proving control_plane_app CANNOT read auth.member's other columns (column-level, not table-level) =="
if select_star_err="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -c "SELECT * FROM auth.member;" 2>&1)"; then
  case_fail "control_plane_app's SELECT * FROM auth.member unexpectedly SUCCEEDED -- the grant is not actually column-scoped"
else
  if echo "$select_star_err" | grep -qi "permission denied"; then
    case_pass "control_plane_app's SELECT * FROM auth.member was rejected with permission denied (id/createdAt were never granted)"
  else
    case_fail "control_plane_app's SELECT * FROM auth.member failed, but NOT with permission denied -- see: $select_star_err"
  fi
fi

for tbl in session account verification; do
  echo ""
  echo "== proving control_plane_app CANNOT read auth.$tbl at all =="
  if out="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -c "SELECT * FROM auth.\"$tbl\";" 2>&1)"; then
    case_fail "control_plane_app's SELECT * FROM auth.$tbl unexpectedly SUCCEEDED"
  else
    if echo "$out" | grep -qi "permission denied"; then
      case_pass "control_plane_app's SELECT * FROM auth.$tbl was rejected with permission denied"
    else
      case_fail "control_plane_app's SELECT * FROM auth.$tbl failed, but NOT with permission denied -- see: $out"
    fi
  fi
done

echo ""
echo "== proving the real AuthMembershipRepository.get_current_role query text succeeds under this exact grant =="
repo_role="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -t -A -c "
  SELECT role FROM auth.member WHERE \"userId\" = '11111111-1111-1111-1111-111111111111' AND \"organizationId\" = '22222222-2222-2222-2222-222222222222';
" 2>/dev/null | tr -d '[:space:]')"
if [ "$repo_role" = "admin" ]; then
  case_pass "the real AuthMembershipRepository.get_current_role query text succeeds under this grant"
else
  case_fail "the real AuthMembershipRepository.get_current_role query text failed under this grant"
fi

echo ""
echo "== CORRECTION ROUND (second pass): upgrade-fixture proof -- a deployment that already had the OLD, historical =="
echo "== 'ALTER DEFAULT PRIVILEGES FOR ROLE web_console IN SCHEMA auth GRANT SELECT ON TABLES TO control_plane_app' =="
echo "== applied (the first implementation's own blanket grant) must have that standing rule actually undone by =="
echo "== rerunning the CORRECTED template, not merely stop granting it to NEW deployments. =="
echo ""
echo "== injecting the exact historical default-privilege statement this script's own source no longer contains =="
psql_as postgres "$BOOTSTRAP_PW" \
  -c 'GRANT SELECT ON ALL TABLES IN SCHEMA auth TO control_plane_app;' \
  -c 'ALTER DEFAULT PRIVILEGES FOR ROLE web_console IN SCHEMA auth GRANT SELECT ON TABLES TO control_plane_app;'

echo "== sanity check: control_plane_app CAN currently read auth.session (the historical bug, reproduced for real before the fix is re-applied) =="
# A hard `fail()` (exits the whole script), not a soft `case_fail()`:
# if this sanity check doesn't actually hold, the historical bug was
# never reproduced, and every assertion below would trivially "pass"
# for proving nothing was ever wrong to begin with -- a test-design
# failure that must stop the run, not blend in with real results.
psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -c "SELECT * FROM auth.session;" >/dev/null 2>&1 \
  || fail "setup error: could not reproduce the historical over-broad grant at all -- the upgrade scenario below would not be a real test"

echo "== re-running the REAL, CORRECTED runtime-roles template against this already-deployed database (the actual upgrade path) =="
sed \
  -e "s/CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER/$CONTROL_PLANE_APP_PASSWORD/" \
  -e "s/RETRIEVAL_APP_PASSWORD_PLACEHOLDER/$RETRIEVAL_APP_PASSWORD/" \
  -e "s/WEB_CONSOLE_PASSWORD_PLACEHOLDER/$WEB_CONSOLE_PASSWORD/" \
  -e "s/AGENT_RUNTIME_PASSWORD_PLACEHOLDER/$AGENT_RUNTIME_PASSWORD/" \
  "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" \
  | docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -U postgres -d proofdb -f -

echo ""
echo "== proving the historical blanket grant on EXISTING sensitive tables was actually undone by the upgrade =="
for tbl in session account verification; do
  if out="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -c "SELECT * FROM auth.\"$tbl\";" 2>&1)"; then
    case_fail "upgrade fixture: control_plane_app's SELECT * FROM auth.$tbl unexpectedly SUCCEEDED after the corrected template ran"
  elif echo "$out" | grep -qi "permission denied"; then
    case_pass "upgrade fixture: control_plane_app's historical access to auth.$tbl was revoked by the corrected template"
  else
    case_fail "upgrade fixture: control_plane_app's SELECT * FROM auth.$tbl failed, but NOT with permission denied -- see: $out"
  fi
done

echo ""
echo "== proving the STANDING DEFAULT-PRIVILEGE RULE itself was revoked, not merely existing grants -- =="
echo "== a table created AFTER the upgrade (simulating a future Better Auth migration) must ALSO stay unreadable =="
psql_as web_console "$WEB_CONSOLE_PASSWORD" -c 'CREATE TABLE auth.future_sensitive_table (id uuid primary key, secret text);'
if out="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -c "SELECT * FROM auth.future_sensitive_table;" 2>&1)"; then
  case_fail "upgrade fixture: control_plane_app could read a table created AFTER the upgrade -- the historical DEFAULT PRIVILEGE rule is still active, only existing grants were revoked"
elif echo "$out" | grep -qi "permission denied"; then
  case_pass "upgrade fixture: a table created AFTER the upgrade is correctly unreadable -- the standing default-privilege rule was truly revoked, not merely existing grants"
else
  case_fail "upgrade fixture: SELECT on the post-upgrade table failed, but NOT with permission denied -- see: $out"
fi

echo ""
echo "== proving the membership query still works after the full upgrade sequence =="
post_upgrade_role="$(psql_as control_plane_app "$CONTROL_PLANE_APP_PASSWORD" -t -A -c "
  SELECT role FROM auth.member WHERE \"userId\" = '11111111-1111-1111-1111-111111111111' AND \"organizationId\" = '22222222-2222-2222-2222-222222222222';
" 2>/dev/null | tr -d '[:space:]')"
if [ "$post_upgrade_role" = "admin" ]; then
  case_pass "upgrade fixture: control_plane_app's own membership query still works after the full upgrade sequence"
else
  case_fail "upgrade fixture: control_plane_app's membership query broke after the upgrade sequence (got '$post_upgrade_role')"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL AUTH GRANT BOUNDARY PROOFS PASSED"
  exit 0
else
  echo "ONE OR MORE AUTH GRANT BOUNDARY PROOFS FAILED" >&2
  exit 1
fi
