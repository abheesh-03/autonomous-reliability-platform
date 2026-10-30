#!/usr/bin/env bash
#
# init-deploy-secrets.sh -- Phase 17A deployment secrets bootstrap.
#
# Mirrors the EXACT idempotent conventions the repository root's
# scripts/init-*.sh family already established (generate_secret_if_
# absent / ensure_token): an existing, non-empty value in
# deploy/.env.deploy is NEVER regenerated or overwritten; a missing
# one gets a fresh, independently random value. Never prints a secret
# value. chmod 600 on the env file. Never touches the repository
# root's own .env -- this script only ever reads/writes
# deploy/.env.deploy.
#
# Usage: ./deploy/scripts/init-deploy-secrets.sh
#
# Safe to rerun at any time, including after a partial failure.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE="$DEPLOY_DIR/.env.deploy"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if [ ! -f "$ENV_FILE" ]; then
  cp "$DEPLOY_DIR/.env.deploy.example" "$ENV_FILE"
  echo "created $ENV_FILE from .env.deploy.example"
fi
chmod 600 "$ENV_FILE"

# generate_secret_if_absent NAME -- identical semantics to the
# repository root's own scripts/init-web-console-db.sh helper of the
# same name, operating on $ENV_FILE instead.
generate_secret_if_absent() {
  local var_name="$1" existing
  existing="$(grep -E "^${var_name}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  if [ -n "$existing" ]; then
    echo "$existing"
    return
  fi
  local value
  value="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new $var_name" >&2
  if grep -qE "^${var_name}=" "$ENV_FILE"; then
    tmp="$(mktemp)"
    sed "s|^${var_name}=.*|${var_name}=${value}|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    echo "${var_name}=${value}" >> "$ENV_FILE"
  fi
  echo "$value"
}

bootstrap_password="$(generate_secret_if_absent POSTGRES_BOOTSTRAP_PASSWORD)"
grafana_admin_password="$(generate_secret_if_absent GRAFANA_ADMIN_PASSWORD)"
control_plane_app_password="$(generate_secret_if_absent CONTROL_PLANE_APP_DB_PASSWORD)"
retrieval_app_password="$(generate_secret_if_absent RETRIEVAL_APP_DB_PASSWORD)"
web_console_db_password="$(generate_secret_if_absent WEB_CONSOLE_DB_PASSWORD)"
agent_runtime_db_password="$(generate_secret_if_absent AGENT_RUNTIME_DB_PASSWORD)"
better_auth_secret="$(generate_secret_if_absent BETTER_AUTH_SECRET)"
service_assertion_secret="$(generate_secret_if_absent SERVICE_ASSERTION_SIGNING_SECRET)"
webhook_token="$(generate_secret_if_absent CONTROL_PLANE_WEBHOOK_TOKEN)"
lifecycle_token="$(generate_secret_if_absent CONTROL_PLANE_LIFECYCLE_TOKEN)"
remediation_proposal_token="$(generate_secret_if_absent CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN)"
remediation_approver_token="$(generate_secret_if_absent CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN)"
remediation_executor_token="$(generate_secret_if_absent CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN)"
tool_gateway_token="$(generate_secret_if_absent TOOL_GATEWAY_EXECUTION_TOKEN)"
read_token_art="$(generate_secret_if_absent CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME)"
read_token_inv="$(generate_secret_if_absent CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR)"
read_token_tg="$(generate_secret_if_absent CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY)"
inv_read_token_art="$(generate_secret_if_absent INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME)"
ret_read_token_inv="$(generate_secret_if_absent RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR)"
payment_fault_token="$(generate_secret_if_absent PAYMENT_FAULT_INJECTION_TOKEN)"
payment_remediation_token="$(generate_secret_if_absent PAYMENT_REMEDIATION_TOKEN)"

# Cross-token distinctness (fail closed) -- same guard the repository
# root's scripts/init-remediation-secrets.sh already applies to its
# own token set, extended with this deployment's new DB-role passwords
# (a password accidentally equal to a Bearer token is still a real
# credential-reuse risk worth catching).
all_names=(
  POSTGRES_BOOTSTRAP_PASSWORD GRAFANA_ADMIN_PASSWORD CONTROL_PLANE_APP_DB_PASSWORD RETRIEVAL_APP_DB_PASSWORD
  WEB_CONSOLE_DB_PASSWORD AGENT_RUNTIME_DB_PASSWORD BETTER_AUTH_SECRET
  SERVICE_ASSERTION_SIGNING_SECRET CONTROL_PLANE_WEBHOOK_TOKEN CONTROL_PLANE_LIFECYCLE_TOKEN
  CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
  CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN TOOL_GATEWAY_EXECUTION_TOKEN
  CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR
  CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME
  RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR PAYMENT_FAULT_INJECTION_TOKEN PAYMENT_REMEDIATION_TOKEN
)
all_values=(
  "$bootstrap_password" "$grafana_admin_password" "$control_plane_app_password" "$retrieval_app_password"
  "$web_console_db_password" "$agent_runtime_db_password" "$better_auth_secret"
  "$service_assertion_secret" "$webhook_token" "$lifecycle_token"
  "$remediation_proposal_token" "$remediation_approver_token"
  "$remediation_executor_token" "$tool_gateway_token"
  "$read_token_art" "$read_token_inv" "$read_token_tg" "$inv_read_token_art"
  "$ret_read_token_inv" "$payment_fault_token" "$payment_remediation_token"
)
count=${#all_names[@]}
i=0
while [ "$i" -lt "$count" ]; do
  j=$((i + 1))
  while [ "$j" -lt "$count" ]; do
    if [ "${all_values[$i]}" = "${all_values[$j]}" ]; then
      fail "${all_names[$i]} and ${all_names[$j]} are configured identically (values not shown). These must be pairwise distinct. Delete one line in $ENV_FILE and rerun this script."
    fi
    j=$((j + 1))
  done
  i=$((i + 1))
done

chmod 600 "$ENV_FILE"
echo "deployment secrets ready in $ENV_FILE (values not printed)."

# ----------------------------------------------------------------
# Correction round: Alertmanager's webhook credential file.
#
# The base docker-compose.yml bind-mounts
# ./observability/alertmanager/secrets/webhook-token (the DEVELOPER'S
# OWN gitignored local-dev secret, generated by
# scripts/init-webhook-secret.sh from the repository root's own .env)
# straight into Alertmanager. On a clean checkout that file does not
# exist at all; on an existing checkout it holds the DEV token, which
# is independently generated from -- and may legitimately differ
# from -- this deployment's own CONTROL_PLANE_WEBHOOK_TOKEN. Either
# way, using it here would be wrong: either Alertmanager starts with
# no credential, or it authenticates with a token control-plane (in
# this deployment) was never given.
#
# This writes a SEPARATE, deployment-owned file
# (deploy/secrets/webhook-token, gitignored -- see deploy/.gitignore)
# derived from deploy/.env.deploy's own CONTROL_PLANE_WEBHOOK_TOKEN,
# and deploy/docker-compose.override.yml mounts THAT instead (see its
# own alertmanager block). The repository root's own
# observability/alertmanager/secrets/webhook-token is NEVER read or
# written by this script.
#
# Idempotent: regenerating with the SAME token is a no-op. Fails
# closed on a genuine inconsistency -- an existing deploy/secrets/
# webhook-token whose content does NOT match the current
# CONTROL_PLANE_WEBHOOK_TOKEN is never silently overwritten (that
# could paper over a real misconfiguration, e.g. a stale file left
# over from a differently-configured prior deployment); the operator
# must delete it explicitly and rerun.
# ----------------------------------------------------------------
deploy_secrets_dir="$DEPLOY_DIR/secrets"
deploy_webhook_file="$deploy_secrets_dir/webhook-token"
mkdir -p "$deploy_secrets_dir"
chmod 700 "$deploy_secrets_dir"

current_webhook_token="$(grep -E '^CONTROL_PLANE_WEBHOOK_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
[ -n "$current_webhook_token" ] || fail "CONTROL_PLANE_WEBHOOK_TOKEN is unexpectedly empty in $ENV_FILE"

if [ -f "$deploy_webhook_file" ]; then
  existing_webhook_file_content="$(cat "$deploy_webhook_file")"
  if [ "$existing_webhook_file_content" != "$current_webhook_token" ]; then
    fail "$deploy_webhook_file already exists but does not match the current CONTROL_PLANE_WEBHOOK_TOKEN in $ENV_FILE (values not shown) -- refusing to silently overwrite a possibly-intentional mismatch. Delete $deploy_webhook_file and rerun this script to regenerate it from the current token."
  fi
  echo "$deploy_webhook_file already matches the current CONTROL_PLANE_WEBHOOK_TOKEN -- left unchanged."
else
  printf '%s' "$current_webhook_token" > "$deploy_webhook_file"
  # 644, not 600 -- matches scripts/init-webhook-secret.sh's own,
  # already-reviewed reasoning exactly: Alertmanager's own image runs
  # as a real non-root user ("nobody", uid 65534), which does not own
  # this host file, so a mode that denies non-owner read would make
  # the bind-mounted file unreadable inside the container. The
  # CONTAINING directory stays 0700 (owner-only traversal); only the
  # file's own mode governs in-container readability.
  chmod 644 "$deploy_webhook_file"
  echo "wrote $deploy_webhook_file from the current CONTROL_PLANE_WEBHOOK_TOKEN (value not printed)."
fi

# ----------------------------------------------------------------
# Apply the runtime-role SQL template (idempotent: CREATE ROLE is
# IF-NOT-EXISTS-guarded, ALTER ROLE/GRANT are safe to repeat) --
# requires the deployment's postgres container to already be up and
# Flyway to have already applied V1-V17 (reliability.* must exist).
# Never run against the developer's own local-development database --
# this connects via THIS deployment's own `postgres` service (the
# SAME root-plus-override Compose invocation every other deploy/
# scripts/*.sh file uses -- deploy/docker-compose.yml does not exist;
# a prior version of this line referenced it directly and failed
# outright on every real invocation, confirmed on a clean checkout),
# under COMPOSE_PROJECT_NAME, never the root docker-compose.yml's own
# default project.
# ----------------------------------------------------------------
if [ "${1:-}" = "--apply-roles" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  [ -n "${POSTGRES_BOOTSTRAP_USER:-}" ] || fail "POSTGRES_BOOTSTRAP_USER is not set in $ENV_FILE"
  [ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is not set in $ENV_FILE"

  tmp_sql="$(mktemp)"
  trap 'rm -f "$tmp_sql"' EXIT
  sed \
    -e "s|CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER|${control_plane_app_password}|g" \
    -e "s|RETRIEVAL_APP_PASSWORD_PLACEHOLDER|${retrieval_app_password}|g" \
    -e "s|WEB_CONSOLE_PASSWORD_PLACEHOLDER|${web_console_db_password}|g" \
    -e "s|AGENT_RUNTIME_PASSWORD_PLACEHOLDER|${agent_runtime_db_password}|g" \
    "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" > "$tmp_sql"

  docker compose --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" \
    --env-file "$ENV_FILE" -f "$REPO_ROOT/docker-compose.yml" -f "$DEPLOY_DIR/docker-compose.override.yml" \
    exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_BOOTSTRAP_USER" -d "$POSTGRES_DB" \
    < "$tmp_sql"
  rm -f "$tmp_sql"
  trap - EXIT
  echo "control_plane_app / retrieval_app runtime roles ready (passwords not printed)."
fi

echo "Next: ./deploy/scripts/deploy-up.sh (brings the deployment stack up, applies migrations, then runs this script again with --apply-roles)."
