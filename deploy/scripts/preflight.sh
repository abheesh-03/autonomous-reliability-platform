#!/usr/bin/env bash
#
# preflight.sh -- Phase 17A item 2 (correction round): fails closed
# before this deployment is ever brought up.
#
# CORRECTION ROUND: the prior version of this file had two real,
# independently-reproduced false-pass bugs:
#   1. `DEPLOYMENT_PUBLIC_ORIGIN=https://` (an empty hostname) passed
#      a bare shell glob check (`https://*` matches ANY string
#      starting with those 8 characters). Fixed by
#      deploy/scripts/validate-origin.py, a real URL parser.
#   2. A malformed/unexpected `docker compose config` JSON result
#      produced a Python `JSONDecodeError`; because the calling shell
#      never checked python's own exit code (only whether its stdout
#      happened to be empty), an exception that printed nothing
#      before crashing was silently read as "no offenders found" and
#      reported PASS. Fixed throughout this file: every external
#      command's output is written to a real file and its exit
#      status is checked EXPLICITLY and IMMEDIATELY, never inferred
#      from whether a string happens to be empty.
#
# Never prints a secret VALUE -- every check reports only PASS/FAIL
# and a human-readable reason; the merged `docker compose config`
# output (which DOES contain every secret-bearing environment value in
# plaintext) is written only to a private (0600), temporary file this
# script itself deletes, and is parsed programmatically
# (deploy/scripts/validate-merged-config.py) -- never printed.
#
# Usage: ./deploy/scripts/preflight.sh
# Exit 0 only if every check below passes (collects and reports ALL
# failures in one run, not just the first).

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.deploy"

FAILED=0
fail() {
  echo "FAIL: $1" >&2
  FAILED=1
}
pass() {
  echo "PASS: $1"
}

if [ ! -f "$ENV_FILE" ]; then
  fail "$ENV_FILE does not exist -- run ./deploy/scripts/init-deploy-secrets.sh first"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# --------------------------------------------------------------
# 0. Functional !override capability probe -- NOT a version-string
#    comparison (a vendor/distro build could report a version number
#    without actually implementing the tag correctly, or vice versa).
#    Requires Docker Compose >= v2.24.4, the first release confirmed
#    to apply `!override` correctly for a published-port list in this
#    exact shape -- re-verified functionally, every run, rather than
#    merely documented.
# --------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  fail "docker is not available on PATH"
else
  probe_dir="$(mktemp -d)"
  cat > "$probe_dir/base.yml" <<'EOF'
services:
  probe:
    image: busybox
    ports: ["127.0.0.1:1:1"]
EOF
  cat > "$probe_dir/override.yml" <<'EOF'
services:
  probe:
    ports: !override []
EOF
  docker compose -f "$probe_dir/base.yml" -f "$probe_dir/override.yml" \
    config --format json > "$probe_dir/result.json" 2> "$probe_dir/result.err"
  probe_status=$?
  if [ "$probe_status" -ne 0 ]; then
    fail "the docker compose !override capability probe failed to run (exit $probe_status): $(cat "$probe_dir/result.err")"
  else
    python3 -c "
import json, sys
with open('$probe_dir/result.json') as f:
    cfg = json.load(f)
ports = cfg.get('services', {}).get('probe', {}).get('ports')
sys.exit(0 if not ports else 2)
"
    probe_parse_status=$?
    if [ "$probe_parse_status" -eq 0 ]; then
      pass "docker compose !override correctly replaces (not concatenates) a published-port list on this installed Compose version"
    else
      fail "docker compose !override did NOT replace the ports list (probe exit $probe_parse_status) -- this Compose version is too old or does not support this merge tag correctly; Docker Compose >= v2.24.4 is required"
    fi
  fi
  rm -rf "$probe_dir"
fi

# --------------------------------------------------------------
# 1. Public origin: a REAL https:// URL -- validated structurally
#    (hostname, port, no userinfo/path/query/fragment), not a shell
#    glob. See deploy/scripts/validate-origin.py.
# --------------------------------------------------------------
case "${DEPLOYMENT_PUBLIC_ORIGIN:-}" in
  "")
    fail "DEPLOYMENT_PUBLIC_ORIGIN is not set"
    ;;
  *CHANGE_ME*)
    fail "DEPLOYMENT_PUBLIC_ORIGIN is still the placeholder value -- set it to this deployment's real origin"
    ;;
  *)
    origin_validation="$(python3 "$SCRIPT_DIR/validate-origin.py" "$DEPLOYMENT_PUBLIC_ORIGIN" 2>&1)"
    origin_status=$?
    if [ "$origin_status" -eq 0 ]; then
      pass "DEPLOYMENT_PUBLIC_ORIGIN is a real, structurally valid https:// origin (${origin_validation#VALID: })"
    else
      fail "DEPLOYMENT_PUBLIC_ORIGIN failed structural validation: ${origin_validation#INVALID: }"
    fi
    ;;
esac

# --------------------------------------------------------------
# 2. Fail-closed posture flags -- exact values required, not
#    merely "truthy". (Re-verified against the ACTUAL merged Compose
#    configuration in step 5 below, not only against this file's own
#    .env values -- a value correct here that never reaches the
#    container is still a real gap.)
# --------------------------------------------------------------
if [ "${CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT:-}" = "true" ]; then
  pass "CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true (organization enforcement active)"
else
  fail "CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT must be exactly \"true\" for a deployment (disabled organization enforcement)"
fi

if [ "${WEB_CONSOLE_USE_SECURE_COOKIES:-}" = "true" ]; then
  pass "WEB_CONSOLE_USE_SECURE_COOKIES=true (Secure session cookies)"
else
  fail "WEB_CONSOLE_USE_SECURE_COOKIES must be exactly \"true\" for a deployment (insecure production cookies)"
fi

if [ "${WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS:-false}" = "false" ]; then
  pass "WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS=false (normal auth rate limits active)"
else
  fail "WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS must be \"false\" for a deployment (relaxed test-only auth limits left enabled)"
fi

case "${CONTROL_PLANE_ALLOW_LEGACY_INGESTION:-}" in
  true|false)
    pass "CONTROL_PLANE_ALLOW_LEGACY_INGESTION is explicitly set (${CONTROL_PLANE_ALLOW_LEGACY_INGESTION}) -- see deploy/README.md's \"legacy ingestion boundary\" section for why \"true\" is the tested default (network-isolated demo path, never a public multi-tenant ingestion claim)"
    ;;
  *)
    fail "CONTROL_PLANE_ALLOW_LEGACY_INGESTION must be explicitly \"true\" or \"false\" (unsafe/ambiguous legacy ingestion setting)"
    ;;
esac

if [ "${TRUSTED_PROXY_ENABLED:-}" = "true" ]; then
  if [ -z "${TRUSTED_PROXY_HOSTS:-}" ]; then
    fail "TRUSTED_PROXY_ENABLED=true but TRUSTED_PROXY_HOSTS is empty (no proxy would ever be trusted, header never usable)"
  elif [ "${TRUSTED_PROXY_HOSTS}" = "*" ]; then
    fail "TRUSTED_PROXY_HOSTS must never be a wildcard (\"*\") -- that trusts every caller's forwarded header"
  else
    pass "TRUSTED_PROXY_ENABLED=true with an explicit, non-wildcard TRUSTED_PROXY_HOSTS (${TRUSTED_PROXY_HOSTS})"
  fi
else
  fail "TRUSTED_PROXY_ENABLED must be \"true\" for a deployment behind Caddy (rate limits would otherwise collapse every client onto the proxy's own address)"
fi

# --------------------------------------------------------------
# 3. SMTP: a real mail configuration is required for sign-in to
#    work in deployment mode (item 4) -- "none" security mode is
#    accepted ONLY when explicitly opted into for the documented
#    local test receiver, never silently in a real deployment.
# --------------------------------------------------------------
if [ -z "${SMTP_HOST:-}" ] || [ -z "${SMTP_FROM_ADDRESS:-}" ]; then
  fail "SMTP_HOST/SMTP_FROM_ADDRESS must both be set -- sign-in requires email verification in deployment mode, which requires real mail delivery"
else
  pass "SMTP_HOST/SMTP_FROM_ADDRESS are both set"
fi
case "${SMTP_SECURITY:-}" in
  starttls|tls) pass "SMTP_SECURITY=${SMTP_SECURITY}" ;;
  none)
    if [ "${ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF:-false}" = "true" ]; then
      pass "SMTP_SECURITY=none accepted (ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true -- local test-receiver proof only)"
    else
      fail "SMTP_SECURITY=none is only accepted with ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true (the documented local-test-SMTP-receiver proof path) -- a real deployment must use starttls or tls"
    fi
    ;;
  *) fail "SMTP_SECURITY must be one of: starttls, tls, none (got '${SMTP_SECURITY:-}')" ;;
esac

# --------------------------------------------------------------
# 4. Credential placeholders -- every secret-bearing variable must
#    be non-empty AND not still the literal example-file value. No
#    value is ever printed; only the variable NAME is reported.
# --------------------------------------------------------------
secret_vars=(
  POSTGRES_BOOTSTRAP_PASSWORD GRAFANA_ADMIN_PASSWORD CONTROL_PLANE_APP_DB_PASSWORD RETRIEVAL_APP_DB_PASSWORD
  WEB_CONSOLE_DB_PASSWORD AGENT_RUNTIME_DB_PASSWORD BETTER_AUTH_SECRET
  SERVICE_ASSERTION_SIGNING_SECRET CONTROL_PLANE_WEBHOOK_TOKEN CONTROL_PLANE_LIFECYCLE_TOKEN
  CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN
  CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN TOOL_GATEWAY_EXECUTION_TOKEN
  CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME CONTROL_PLANE_INTERNAL_READ_TOKEN_INVESTIGATOR
  CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME
  RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR
)
missing_or_placeholder=()
for var_name in "${secret_vars[@]}"; do
  value="${!var_name:-}"
  case "$value" in
    ""|*local_dev_only_change_me*|*CHANGE_ME*|*changeme*)
      missing_or_placeholder+=("$var_name")
      ;;
  esac
done
if [ "${#missing_or_placeholder[@]}" -eq 0 ]; then
  pass "all ${#secret_vars[@]} required secrets are set and non-placeholder (values not shown)"
else
  fail "the following secrets are missing or still placeholder values (run ./deploy/scripts/init-deploy-secrets.sh): ${missing_or_placeholder[*]}"
fi

# --------------------------------------------------------------
# 4b. Retention parameters -- bounded, positive integers. Never a
#     secret, but a malformed value here could otherwise either do
#     nothing silently (e.g. a non-numeric day count) or run
#     unboundedly (e.g. an absurd batch size).
# --------------------------------------------------------------
validate_positive_int() {
  local name="$1" value="$2" max="${3:-}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ]; then
    fail "$name must be a positive integer (got '${value}')"
    return
  fi
  if [ -n "$max" ] && [ "$value" -gt "$max" ]; then
    fail "$name=$value exceeds the sane upper bound ($max)"
    return
  fi
  pass "$name=$value is a valid, bounded positive integer"
}
validate_positive_int "TELEMETRY_RETENTION_DAYS" "${TELEMETRY_RETENTION_DAYS:-}" 3650
validate_positive_int "TELEMETRY_RETENTION_BATCH_SIZE" "${TELEMETRY_RETENTION_BATCH_SIZE:-}" 100000
validate_positive_int "TELEMETRY_RETENTION_INTERVAL_HOURS" "${TELEMETRY_RETENTION_INTERVAL_HOURS:-}" 8760
case "${TELEMETRY_RETENTION_DRY_RUN:-}" in
  true|false) pass "TELEMETRY_RETENTION_DRY_RUN is explicitly set (${TELEMETRY_RETENTION_DRY_RUN})" ;;
  *) fail "TELEMETRY_RETENTION_DRY_RUN must be explicitly \"true\" or \"false\" (got '${TELEMETRY_RETENTION_DRY_RUN:-}')" ;;
esac

# --------------------------------------------------------------
# 5. Fully merged Compose configuration: structurally valid JSON,
#    every expected service present, ONLY `caddy` publishes a port,
#    the ACTUAL merged security-relevant environment values are
#    correct, and no service is over-replicated. Written to a
#    private (0600), temporary file this script deletes -- never
#    piped through a substitution whose exit status could be lost,
#    and never printed (it contains every secret value in plaintext).
# --------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  fail "docker is not available on PATH"
else
  config_file="$(mktemp)"
  chmod 600 "$config_file"
  (cd "$REPO_ROOT" && docker compose \
    --project-name "${COMPOSE_PROJECT_NAME:-arp-deploy}" \
    --env-file "$ENV_FILE" \
    -f docker-compose.yml -f deploy/docker-compose.override.yml \
    config --format json) > "$config_file" 2> "${config_file}.err"
  compose_status=$?
  if [ "$compose_status" -ne 0 ]; then
    fail "docker compose config exited $compose_status: $(cat "${config_file}.err")"
  else
    validate_out="$(mktemp)"
    validate_err="$(mktemp)"
    python3 "$SCRIPT_DIR/validate-merged-config.py" "$config_file" 1>"$validate_out" 2>"$validate_err"
    validate_status=$?
    if [ "$validate_status" -eq 0 ]; then
      pass "$(cat "$validate_out")"
    else
      # CORRECTION ROUND (second pass) -- real finding: if the
      # validator exits non-zero with EMPTY stderr (a silent crash,
      # an unhandled exception swallowed elsewhere, `sys.exit(N)`
      # with no message), the `while read` loop below ran ZERO
      # iterations and `fail()` was NEVER called -- `$FAILED` stayed
      # 0 and this script printed "all checks passed" despite a real
      # validation failure. The exit status itself, not the
      # PRESENCE of stderr output, is what marks this failed; the
      # loop only ever adds detail lines on top of that.
      fail "validate-merged-config.py exited $validate_status"
      while IFS= read -r line; do
        fail "$line"
      done < "$validate_err"
    fi
    rm -f "$validate_out" "$validate_err"
  fi
  rm -f "$config_file" "${config_file}.err"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "PREFLIGHT: all checks passed. Safe to run ./deploy/scripts/deploy-up.sh."
  exit 0
else
  echo "PREFLIGHT: FAILED -- fix the FAIL lines above before deploying." >&2
  exit 1
fi
