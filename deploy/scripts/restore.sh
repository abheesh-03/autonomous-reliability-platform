#!/usr/bin/env bash
#
# restore.sh -- Phase 17A item 5: restores a backup.sh artifact into
# a target PostgreSQL server.
#
# Runs every psql/pg_restore command through a DISPOSABLE
# `pgvector/pgvector:pg18` container (the same image this platform's
# own `postgres` service uses, so its bundled client tools always
# exactly match the server version) on the given Docker network --
# never assumes the host machine itself has PostgreSQL client tools
# installed, the same "everything runs through Docker" convention
# every other script in this repository already follows.
#
# FAILS CLOSED, loudly, before touching anything, if:
#   - the manifest/dump/roles files don't match their recorded
#     SHA-256 checksums (a corrupted or tampered artifact);
#   - the target already has ANY of the 4 application roles
#     (control_plane_app/retrieval_app/web_console/agent_runtime), OR
#     the target database already has any table in the reliability/
#     auth/agent_runtime schemas -- i.e. this refuses to run against
#     anything that is not OBVIOUSLY a fresh/empty instance, by real
#     introspection, never merely trusting a flag;
#   - the target PostgreSQL server does not have the `vector`
#     extension available at all (a dump taken from
#     pgvector/pgvector:pg18 embeds `CREATE EXTENSION IF NOT EXISTS
#     vector`, which requires the target image to ALSO be
#     pgvector-capable -- a vanilla `postgres` image cannot satisfy
#     this, and this script says so explicitly rather than failing
#     deep inside pg_restore's own output).
#
# Usage:
#   TARGET_PGPASSWORD=<target superuser password> \
#   ./deploy/scripts/restore.sh \
#     --manifest <path/to/manifest.json> \
#     --docker-network <network the target container is reachable on> \
#     --target-host <host-on-that-network> --target-port <port> \
#     --target-db <name> \
#     --target-superuser <user> --target-superuser-password-env TARGET_PGPASSWORD \
#     --credentials-out <path to a NEW, not-yet-existing private file>
#
# --credentials-out must name a file that does not already exist --
# this script refuses to run otherwise, rather than silently
# overwriting a previous restore's saved credentials.
#
# The target superuser's password is read from the ENVIRONMENT
# VARIABLE NAME you pass (never the value itself, so it never appears
# in `ps`/shell history).
#
# Freshly generates new, independently random passwords for all 4
# application roles -- NEVER reuses whatever the original deployment's
# passwords were (roles.sql, produced by backup.sh, never contains
# them at all). These are NEVER printed to stdout/stderr and NEVER
# passed as a process argument (CORRECTION ROUND: the previous version
# passed them via `psql -v pass=...`, a literal docker-run subprocess
# argument visible to any other local user via `ps aux` while it ran;
# fixed by sending the password only through stdin, in a script whose
# character set -- `secrets.token_hex`, hex digits only -- cannot
# break out of a single-quoted SQL literal, so no `-v`/`:'pass'`
# substitution is needed at all). They are written EXACTLY ONCE to the
# file given by --credentials-out, created with mode 600, and this
# script REFUSES to run if that file already exists (no silent
# overwrite of a previous restore's credentials).
set -euo pipefail

CLIENT_IMAGE="pgvector/pgvector:pg18"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

MANIFEST="" NETWORK="" TARGET_HOST="" TARGET_PORT="5432" TARGET_DB="" TARGET_SUPERUSER="" TARGET_PW_ENV="" CREDS_OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --manifest) MANIFEST="$2"; shift 2 ;;
    --docker-network) NETWORK="$2"; shift 2 ;;
    --target-host) TARGET_HOST="$2"; shift 2 ;;
    --target-port) TARGET_PORT="$2"; shift 2 ;;
    --target-db) TARGET_DB="$2"; shift 2 ;;
    --target-superuser) TARGET_SUPERUSER="$2"; shift 2 ;;
    --target-superuser-password-env) TARGET_PW_ENV="$2"; shift 2 ;;
    --credentials-out) CREDS_OUT="$2"; shift 2 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[ -n "$MANIFEST" ] || fail "--manifest is required"
[ -n "$NETWORK" ] || fail "--docker-network is required"
[ -n "$TARGET_HOST" ] || fail "--target-host is required"
[ -n "$TARGET_DB" ] || fail "--target-db is required"
[ -n "$TARGET_SUPERUSER" ] || fail "--target-superuser is required"
[ -n "$TARGET_PW_ENV" ] || fail "--target-superuser-password-env is required"
[ -n "$CREDS_OUT" ] || fail "--credentials-out is required -- an explicit private file path the new role passwords will be written to"
[ -f "$MANIFEST" ] || fail "manifest not found: $MANIFEST"
[ -e "$CREDS_OUT" ] && fail "--credentials-out ($CREDS_OUT) already exists -- refusing to silently overwrite a previous restore's credentials; move it aside first"
CREDS_OUT_DIR="$(cd -- "$(dirname -- "$CREDS_OUT")" &>/dev/null && pwd)" || fail "--credentials-out's parent directory does not exist"
CREDS_OUT="$CREDS_OUT_DIR/$(basename -- "$CREDS_OUT")"

TARGET_PGPASSWORD="${!TARGET_PW_ENV:-}"
[ -n "$TARGET_PGPASSWORD" ] || fail "the environment variable named by --target-superuser-password-env ($TARGET_PW_ENV) is empty or unset"

ARTIFACT_DIR="$(cd -- "$(dirname -- "$MANIFEST")" &>/dev/null && pwd)"

echo "== verifying artifact checksums against manifest =="
roles_relname="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['roles_dump_file'])")"
dump_relname="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['db_dump_file'])")"
expected_roles_sha="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['roles_dump_sha256'])")"
expected_dump_sha="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['db_dump_sha256'])")"

actual_roles_sha="$(shasum -a 256 "$ARTIFACT_DIR/$roles_relname" | awk '{print $1}')"
actual_dump_sha="$(shasum -a 256 "$ARTIFACT_DIR/$dump_relname" | awk '{print $1}')"

[ "$actual_roles_sha" = "$expected_roles_sha" ] || fail "roles.sql checksum mismatch -- expected $expected_roles_sha, got $actual_roles_sha (artifact is corrupted or tampered)"
[ "$actual_dump_sha" = "$expected_dump_sha" ] || fail "db.dump checksum mismatch -- expected $expected_dump_sha, got $actual_dump_sha (artifact is corrupted or tampered)"
echo "checksums verified OK."

# A disposable client container, with the artifact directory
# bind-mounted read-only, on the SAME Docker network as the target --
# every command below runs inside it, never on the bare host.
run_client() {
  docker run --rm -i --network "$NETWORK" \
    -e PGPASSWORD="$TARGET_PGPASSWORD" \
    -v "$ARTIFACT_DIR:/artifact:ro" \
    "$CLIENT_IMAGE" "$@"
}

psql_target() {
  run_client psql -v ON_ERROR_STOP=1 -h "$TARGET_HOST" -p "$TARGET_PORT" -U "$TARGET_SUPERUSER" "$@"
}

echo "== verifying the vector extension is available on the target =="
has_vector="$(psql_target -d postgres -t -A -c "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector');")"
[ "$(echo "$has_vector" | tr -d '[:space:]')" = "t" ] || fail "the target PostgreSQL server does not have the 'vector' extension available -- it must be a pgvector-capable image (e.g. pgvector/pgvector:pg18), not a vanilla postgres image"

echo "== verifying the target database exists and is genuinely empty of this platform's own objects =="
db_exists="$(psql_target -d postgres -t -A -c "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB');" | tr -d '[:space:]')"
if [ "$db_exists" != "t" ]; then
  psql_target -d postgres -c "CREATE DATABASE \"$TARGET_DB\";"
fi

for role in control_plane_app retrieval_app web_console agent_runtime; do
  exists="$(psql_target -d postgres -t -A -c "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role');" | tr -d '[:space:]')"
  [ "$exists" = "f" ] || fail "role '$role' already exists on the target -- refusing to restore onto a non-fresh instance"
done
for schema in reliability auth agent_runtime; do
  # CORRECTION ROUND: previously `2>/dev/null ... || echo 0` turned
  # ANY failure of this query (connection lost, auth failure, etc.)
  # into a false "0 tables found", which this script would then have
  # treated as proof the target is fresh. There is no such thing as
  # a query that legitimately fails here -- the target was already
  # proven reachable by the vector-extension/db-exists checks above --
  # so any failure now propagates via `set -e`/`pipefail`, failing
  # closed instead of being read as a benign empty result.
  table_count="$(psql_target -d "$TARGET_DB" -t -A -c "
    SELECT count(*) FROM information_schema.tables WHERE table_schema = '$schema';
  " | tr -d '[:space:]')"
  [ "$table_count" = "0" ] || fail "schema '$schema' on the target already has $table_count table(s) -- refusing to restore onto a non-fresh instance"
done
echo "target is verified fresh/empty."

echo "== recreating global roles (bootstrap role's own CREATE/ALTER lines are tolerated as already-existing) =="
roles_output_file="$(mktemp)"
set +e
run_client bash -c "psql -v ON_ERROR_STOP=0 -h '$TARGET_HOST' -p '$TARGET_PORT' -U '$TARGET_SUPERUSER' -d postgres -f /artifact/$roles_relname" \
  > "$roles_output_file" 2>&1
roles_status=$?
set -e
# CORRECTION ROUND: the previous version swallowed `run_client`'s own
# exit status unconditionally (`|| true`) and only looked for a
# narrow "error:.*(permission denied|syntax error)" pattern -- a
# docker-launch failure (wrong image, daemon unreachable, etc.) never
# matches that pattern AND the `|| true` discarded `run_client`'s own
# exit status regardless, so this would have proceeded as if the
# replay succeeded. Now: the exit status is captured explicitly, AND
# a nonzero exit is tolerated ONLY when the output is recognizable as
# this script's own psql -f run having actually executed (fail closed
# on absence of positive evidence, never on absence of a particular
# error string).
if [ "$roles_status" -ne 0 ] && ! grep -q "^ALTER ROLE\|^CREATE ROLE\|^psql:.*already exists" "$roles_output_file"; then
  cat "$roles_output_file" >&2
  rm -f "$roles_output_file"
  fail "roles.sql replay produced no recognizable psql output at all (client launch or connection failure) -- see output above"
fi
unexpected_roles_errors="$(grep -i "error" "$roles_output_file" | grep -vi "already exists" || true)"
if [ -n "$unexpected_roles_errors" ]; then
  cat "$roles_output_file" >&2
  rm -f "$roles_output_file"
  fail "roles.sql replay produced an unexpected error class (not merely 'role/role membership already exists') -- see output above"
fi
rm -f "$roles_output_file"

new_passwords=()
for role in control_plane_app retrieval_app web_console agent_runtime; do
  new_pw="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  # CORRECTION ROUND: the previous version passed the password via
  # `psql -v pass=...`, a literal argument to the `docker run`
  # subprocess this script execs -- visible to any other local user
  # via `ps aux`/`/proc` for as long as that process runs. Fixed by
  # sending the password only through stdin, interpolated directly
  # into the SQL text: safe here specifically because
  # `secrets.token_hex` can only ever produce `[0-9a-f]`, a character
  # set that cannot contain a `'` and so cannot break out of the
  # single-quoted literal -- not a general-purpose escaping strategy,
  # only correct because the input is provably from this fixed
  # alphabet.
  printf "ALTER ROLE %s WITH LOGIN PASSWORD '%s' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;\n" "$role" "$new_pw" \
    | run_client psql -v ON_ERROR_STOP=1 -h "$TARGET_HOST" -p "$TARGET_PORT" -U "$TARGET_SUPERUSER" -d postgres -f -
  new_passwords+=("$role=$new_pw")
done

# Real finding from this round's own restore-proof run: `pg_restore`
# of a SCHEMA-FILTERED dump (backup.sh's own `--schema=reliability`
# etc.) creates `reliability.retrieval_chunks.embedding vector(1536)`
# whose type (`reliability.vector`, installed INTO the reliability
# schema by database/migrations/V5's own `CREATE EXTENSION IF NOT
# EXISTS vector;`, issued with search_path=reliability) must already
# exist -- but the `reliability` schema itself is ALSO created by
# this same pg_restore run, a real chicken-and-egg ordering problem a
# bare "the extension is available" check does not catch (confirmed
# directly: `pg_restore` failed outright on every
# reliability.retrieval_chunks-related statement with "type
# reliability.vector does not exist" until this fix was added).
# Pre-creating the schemas and the extension here means every real
# table creation that follows succeeds. CORRECTION ROUND (second
# pass): pg_restore's own later `CREATE SCHEMA` statements for these
# exact three schemas are now EXCLUDED from the replay outright (see
# the TOC-filtering step below) rather than merely tolerated as
# harmless "already exists" errors -- the `CREATE EXTENSION`
# statement is left in the replay unfiltered, since `pg_dump` always
# emits extension creation as `IF NOT EXISTS` (unlike schema
# creation), so replaying it against the already-pre-created
# extension is a real, harmless no-op, not an error needing tolerance
# at all.
echo "== pre-creating schemas and the vector extension (pg_restore's own schema-creation and the table that needs the type it defines would otherwise race) =="
# CORRECTION ROUND (second pass) -- real finding from this round's
# own restore-then-live-login proof (with CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true,
# which routes every auth check through a real, authenticated
# session instead of SQL alone): these schemas were previously
# pre-created with NO `AUTHORIZATION` clause at all, so they ended up
# OWNED BY `$TARGET_SUPERUSER` (the bootstrap role) instead of the
# real owning application role. `auth`/`agent_runtime`'s OWN real
# owners are `web_console`/`agent_runtime` respectively (see
# deploy/sql/01-create-runtime-roles.sql.template's own, matching
# `CREATE SCHEMA ... AUTHORIZATION` statements -- this must stay
# consistent with that file, never drift from it). Without this, a
# role's own `search_path` pointing at a schema it merely has no
# USAGE on (because it does not own it and was never explicitly
# granted USAGE either) is silently DROPPED by Postgres from
# `current_schemas()` -- confirmed directly: `web_console` connecting
# to a restored target with a correctly-set `search_path=auth` still
# showed `current_schemas(false) = {}`, and Better Auth's own schema
# probe reported every table "missing" as a result, even though the
# tables themselves were correctly restored and fully intact.
printf "CREATE SCHEMA IF NOT EXISTS reliability;\nCREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION web_console;\nCREATE SCHEMA IF NOT EXISTS agent_runtime AUTHORIZATION agent_runtime;\nCREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA reliability;\n" \
  | run_client psql -v ON_ERROR_STOP=1 -h "$TARGET_HOST" -p "$TARGET_PORT" -U "$TARGET_SUPERUSER" -d "$TARGET_DB" -f -

echo "== restoring database content (schema + data + extensions + triggers, ownership preserved) =="
# CORRECTION ROUND (second pass) -- real finding from independent
# fault injection: a `pg_restore` killed by SIGKILL (exit 137) AFTER
# it had already emitted exactly one of the three tolerated "schema
# ... already exists" lines still passed the previous text-based
# tolerance check (recognizable pg_restore output, present, and the
# only error line matched the whitelist) -- "recognizable output plus
# absence of unexpected error TEXT" is not evidence the restore
# actually completed; it is only evidence that whatever PARTIAL output
# existed before termination happened to look clean. No text-based
# check can close this class of bug in general, because an abnormal
# termination can happen at any point, including right after a
# tolerated line and right before real data would have been lost.
#
# Redesigned to need NO tolerance at all, rather than trying to make
# the tolerance text-matching airtight: the dump's own table of
# contents is listed, the three schema-creation entries for the
# schemas this script already pre-created above (reliability/auth/
# agent_runtime) are removed from the list pg_restore is told to
# replay, and the restore then runs under `--exit-on-error` -- the
# real Postgres/pg_restore flag that aborts immediately on the FIRST
# error instead of continuing past it and tallying them. With the one
# known, expected conflict structurally excluded from the replay
# instead of merely tolerated after the fact, EVERY remaining error is
# real, and `--exit-on-error` guarantees pg_restore itself stops and
# reports non-zero on it. The success condition is now simply "exit
# 0" -- no error text to parse, nothing to whitelist, and an abnormal
# termination (137, 139, or anything else non-zero) is unconditionally
# a failure with no tolerance path that could ever mask it.
restore_work_dir="$(mktemp -d)"

toc_file="$restore_work_dir/toc.list"
# `set +e` around this call, same as every other place in this
# script that must capture a real exit status: under `set -e`, a
# plain (non-`if`/`&&`/`||`) command returning non-zero kills the
# script immediately, before `toc_status=$?` is ever reached --
# caught directly by this round's own regression suite (the
# launch_failure case expected a clean `fail()` message and exit 1,
# but got a bare, unexplained exit 125 instead).
set +e
run_client pg_restore -l "/artifact/$dump_relname" > "$toc_file"
toc_status=$?
set -e
if [ "$toc_status" -ne 0 ]; then
  rm -rf "$restore_work_dir"
  fail "pg_restore -l (listing the archive's table of contents) exited $toc_status"
fi

filtered_toc_file="$restore_work_dir/toc.filtered.list"
grep -vE '^[0-9]+; [0-9]+ [0-9]+ SCHEMA - (reliability|auth|agent_runtime) ' "$toc_file" > "$filtered_toc_file"

set +e
restore_output="$(docker run --rm -i --network "$NETWORK" \
  -e PGPASSWORD="$TARGET_PGPASSWORD" \
  -v "$ARTIFACT_DIR:/artifact:ro" \
  -v "$restore_work_dir:/restore-work:ro" \
  "$CLIENT_IMAGE" pg_restore --exit-on-error -L /restore-work/toc.filtered.list \
  -h "$TARGET_HOST" -p "$TARGET_PORT" -U "$TARGET_SUPERUSER" -d "$TARGET_DB" "/artifact/$dump_relname" 2>&1)"
restore_status=$?
set -e
rm -rf "$restore_work_dir"
echo "$restore_output"
[ "$restore_status" -eq 0 ] || fail "pg_restore (strict --exit-on-error, pre-created-schema entries excluded from the replay) exited $restore_status -- see output above"

echo ""
# CORRECTION ROUND (second pass) -- real finding: "RESTORE COMPLETE"
# was previously printed HERE, before the credentials file below was
# even created -- if writing it failed afterward (disk full,
# permission error, directory removed mid-run), this script would
# already have told the operator the restore was complete, despite
# the newly-generated role passwords never having been persisted
# anywhere retrievable. The completion marker is now the LAST thing
# this script ever prints, after every remaining operation --
# including the credential-file write -- has actually succeeded.
#
# Previously printed the passwords to stdout directly -- plain-text
# passwords in terminal scrollback/CI logs. Now written exactly once
# to the operator-chosen --credentials-out path, created with mode
# 600 before any content is written (never world/group readable even
# for the instant between creation and the chmod that used to follow
# it), and never echoed anywhere else.
( umask 177 && : > "$CREDS_OUT" )
for entry in "${new_passwords[@]}"; do
  echo "$entry" >> "$CREDS_OUT"
done
echo "new role passwords written to $CREDS_OUT (mode 600) -- this is the only copy; move/secure it immediately."
echo ""
echo "RESTORE COMPLETE into $TARGET_HOST:$TARGET_PORT/$TARGET_DB."
