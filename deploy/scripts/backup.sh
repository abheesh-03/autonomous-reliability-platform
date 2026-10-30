#!/usr/bin/env bash
#
# backup.sh -- Phase 17A item 5: a real, explicit backup of this
# deployment's PostgreSQL state.
#
# Covers, in ONE run:
#   1. Global role definitions (pg_dumpall --roles-only) for every
#      role this deployment creates: the bootstrap/owner role,
#      control_plane_app, retrieval_app, web_console, agent_runtime --
#      WITHOUT their password hashes (stripped below; see the
#      rationale comment at that step). A restore regenerates fresh,
#      independently random passwords for every role instead of ever
#      replaying an old one.
#   2. The real database content -- `reliability.*` (including pgvector
#      embeddings in reliability.retrieval_chunks, and
#      flyway_schema_history, which lives INSIDE the reliability
#      schema and therefore needs no separate handling), `auth.*`
#      (Better Auth's own tables), `agent_runtime.*` (LangGraph's own
#      checkpoint tables) -- via `pg_dump -Fc` (custom format: the
#      only format `pg_restore` can selectively/efficiently restore
#      from, and the one that preserves object OWNERSHIP metadata, so
#      a restore that recreates the same role names first reproduces
#      the exact same per-table ownership this deployment relies on).
#      Schema + data + extensions (`vector`) + triggers (the
#      append-only audit triggers on incident_events/remediation_events
#      are schema objects, not data -- `pg_dump` captures them as part
#      of the normal schema dump, same as any other trigger) are all
#      included; nothing is excluded.
#
# Fails on ANY error (`set -euo pipefail`; every external command's
# exit status is checked). A partial/corrupt dump is never reported
# as a success -- the final "BACKUP COMPLETE" line is the ONLY
# success signal this script ever prints, and it is printed exactly
# once, after every step (including the checksum step) has already
# succeeded.
#
# Output: $BACKUP_OUTPUT_DIR/<timestamp>/{roles.sql, db.dump,
# manifest.json}, chmod 700 on the directory and 600 on every file in
# it. No credential value ever appears in a filename, a command-line
# argument (checked via `docker compose exec -e PGPASSWORD=...`, the
# same established pattern scripts/apply-web-console-auth-schema.sh
# already uses -- never a bare psql/pg_dump argument), or any line
# this script prints.
#
# Off-host delivery of this output (S3/rclone/etc., encrypted in
# transit and at rest) is a REQUIRED Phase 17B operational step this
# script does NOT perform -- a local backup file does not protect
# against loss of the host it lives on. See deploy/README.md.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.deploy"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found -- run ./deploy/scripts/init-deploy-secrets.sh first"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ -n "${POSTGRES_BOOTSTRAP_USER:-}" ] || fail "POSTGRES_BOOTSTRAP_USER is not set in $ENV_FILE"
[ -n "${POSTGRES_BOOTSTRAP_PASSWORD:-}" ] || fail "POSTGRES_BOOTSTRAP_PASSWORD is not set in $ENV_FILE"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"

cd "$REPO_ROOT"
COMPOSE=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.override.yml)

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="${BACKUP_OUTPUT_DIR:-./deploy/backups}/$timestamp"
mkdir -p "$out_dir"
chmod 700 "$(dirname "$out_dir")" 2>/dev/null || true
chmod 700 "$out_dir"

echo "== dumping global role definitions (passwords stripped) =="
"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_BOOTSTRAP_PASSWORD" postgres \
  pg_dumpall -U "$POSTGRES_BOOTSTRAP_USER" --roles-only \
  | grep -v -iE "PASSWORD\s+'(md5|scram-sha-256)" \
  > "$out_dir/roles.sql"
[ -s "$out_dir/roles.sql" ] || fail "roles.sql is empty -- pg_dumpall produced no output"

echo "== dumping database content (reliability + auth + agent_runtime, custom format) =="
"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_BOOTSTRAP_PASSWORD" postgres \
  pg_dump -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" -Fc \
  --schema=reliability --schema=auth --schema=agent_runtime \
  > "$out_dir/db.dump"
[ -s "$out_dir/db.dump" ] || fail "db.dump is empty -- pg_dump produced no output"

echo "== computing checksums =="
roles_sha="$(shasum -a 256 "$out_dir/roles.sql" | awk '{print $1}')"
dump_sha="$(shasum -a 256 "$out_dir/db.dump" | awk '{print $1}')"

cat > "$out_dir/manifest.json" <<EOF
{
  "created_at_utc": "$timestamp",
  "postgres_db": "$POSTGRES_DB",
  "compose_project_name": "${COMPOSE_PROJECT_NAME:-arp-deploy}",
  "schemas_included": ["reliability", "auth", "agent_runtime"],
  "roles_dump_file": "roles.sql",
  "roles_dump_sha256": "$roles_sha",
  "roles_dump_note": "password hashes stripped -- restore.sh generates fresh, independently random passwords for every role",
  "db_dump_file": "db.dump",
  "db_dump_sha256": "$dump_sha",
  "db_dump_format": "pg_dump custom format (-Fc)",
  "off_host_copy_made": false,
  "off_host_copy_note": "shipping this directory off-host (encrypted) is a required Phase 17B step not performed by this script"
}
EOF

chmod 600 "$out_dir"/*.json "$out_dir"/*.sql "$out_dir"/*.dump

echo ""
echo "BACKUP COMPLETE: $out_dir"
echo "  roles.sql  sha256=$roles_sha"
echo "  db.dump    sha256=$dump_sha"
echo "Remember: this is a LOCAL file only. Copy it off this host (encrypted) before relying on it -- see deploy/README.md."
