#!/usr/bin/env bash
# test-email-flows.sh -- Phase 17A item 4: runs the real email
# verification/invitation/password-reset proof
# (deploy/scripts/test-email-flows.py) against the already-running
# deployment stack plus the disposable mailpit test receiver
# (deploy/docker-compose.test-smtp.yml). Does NOT bring the stack up
# itself -- run ./deploy/scripts/deploy-up.sh first, then
#   docker compose --project-name arp-deploy --env-file deploy/.env.deploy \
#     -f docker-compose.yml -f deploy/docker-compose.override.yml \
#     -f deploy/docker-compose.test-smtp.yml up -d mailpit web-console
# before invoking this script.
#
# CORRECTION ROUND: the Python script previously hardcoded its own
# origin/CA-cert-path/mailpit-API defaults, which only ever matched
# THIS script's own undocumented assumption of a purely local manual
# run -- CI actually uses a different origin (arp-deploy-ci.test) and
# CA cert path (/tmp/caddy_root.crt). Those are now real,
# explicit command-line flags; this wrapper passes them from the
# environment, defaulting to the exact values deploy/README.md's own
# documented local manual workflow already uses, so a plain
# `./deploy/scripts/test-email-flows.sh` with no environment overrides
# behaves identically to before.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

python3 -c "import requests" 2>/dev/null || pip install --quiet requests

TEST_EMAIL_FLOWS_ORIGIN="${TEST_EMAIL_FLOWS_ORIGIN:-${DEPLOYMENT_PUBLIC_ORIGIN:-https://arp-deploy.test}}"
TEST_EMAIL_FLOWS_CA_CERT="${TEST_EMAIL_FLOWS_CA_CERT:-deploy/caddy_root.crt}"
TEST_EMAIL_FLOWS_MAILPIT_API="${TEST_EMAIL_FLOWS_MAILPIT_API:-http://127.0.0.1:18025/api/v1}"

# CORRECTION ROUND (second pass): real proof that the generated
# tokens never reach Caddy's own captured logs (see
# deploy/caddy/Caddyfile's log-redaction filter) -- not merely that
# the filter's Caddyfile syntax looks right. The python script writes
# every token it actually generates to a private, mode-600 file
# (never printed anywhere); this wrapper then scans Caddy's own
# logs, scoped to this run's own time window, for each exact value.
TOKEN_SCAN_DIR="$(mktemp -d)"
trap 'rm -rf "$TOKEN_SCAN_DIR"' EXIT
TOKEN_SCAN_FILE="$TOKEN_SCAN_DIR/tokens"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-arp-deploy}"
COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file deploy/.env.deploy -f docker-compose.yml -f deploy/docker-compose.override.yml)
run_started="$(date -u +%Y-%m-%dT%H:%M:%S)"

set +e
python3 deploy/scripts/test-email-flows.py \
  --origin "$TEST_EMAIL_FLOWS_ORIGIN" \
  --ca-cert "$TEST_EMAIL_FLOWS_CA_CERT" \
  --mailpit-api "$TEST_EMAIL_FLOWS_MAILPIT_API" \
  --token-scan-file "$TOKEN_SCAN_FILE"
flows_status=$?
set -e

leak_found=0
if [ ! -s "$TOKEN_SCAN_FILE" ]; then
  # CORRECTION ROUND (third pass) -- real finding: an EMPTY token
  # file (the email-flows run never actually captured any real
  # verification/reset token at all -- a prerequisite step silently
  # failing to generate one, a mailpit/SMTP hiccup, etc.) previously
  # skipped this entire proof via this same `if` guard, falling
  # through to pass or fail based ONLY on `flows_status` -- a run
  # that generated and leaked zero evidence about redaction could
  # still report overall success. A missing token is now itself a
  # hard failure, not something that silently waives the proof.
  echo "FAIL: no real tokens were captured for scanning at all -- this run never generated the expected verification/reset tokens, so it proves nothing about log redaction" >&2
  leak_found=1
else
  # CORRECTION ROUND (third pass) -- real finding: `|| true` on the
  # log-fetch command meant a FAILED fetch (wrong project, caddy
  # container missing, a transient compose/docker error) was silently
  # converted into an empty/error-text string, which the token-absence
  # grep below then read as "no tokens found" -- a false PASS that
  # proves nothing, since no real log content was ever scanned. Three
  # independent conditions must now ALL hold before this step is
  # allowed to pass: (1) the fetch itself must succeed (its own exit
  # status captured explicitly, never swallowed); (2) the fetched
  # output must contain real evidence of the actual requests this run
  # just made (`verify-email`/`reset-password`) -- an empty or
  # unrelated capture must not be read as "nothing to find"; only
  # once both hold does (3) the real per-token absence check mean
  # anything at all.
  set +e
  caddy_logs="$("${COMPOSE[@]}" logs --no-color --since "$run_started" caddy 2>&1)"
  logs_status=$?
  set -e
  if [ "$logs_status" -ne 0 ]; then
    echo "FAIL: could not fetch Caddy's own logs (docker compose logs exited $logs_status) -- a failed fetch is never valid proof of redaction" >&2
    leak_found=1
  elif ! echo "$caddy_logs" | grep -qi "verify-email\|reset-password"; then
    echo "FAIL: Caddy's captured logs contain no record of the real verify-email/reset-password requests this run just made -- an empty or unrelated log capture is never valid proof of redaction" >&2
    leak_found=1
  else
    while IFS= read -r token; do
      [ -n "$token" ] || continue
      if echo "$caddy_logs" | grep -qF -- "$token"; then
        # Never echo the leaked value itself, or even a prefix of
        # it, into this script's own diagnostic output -- that would
        # just relocate the same leak from Caddy's logs to this
        # script's own.
        echo "FAIL: a real generated token was found verbatim in Caddy's own captured logs -- log redaction did not hold" >&2
        leak_found=1
      fi
    done < "$TOKEN_SCAN_FILE"
    if [ "$leak_found" -eq 0 ]; then
      echo "PASS: scanned Caddy's logs for every real token this run generated (log capture confirmed to contain the real verify-email/reset-password requests) -- none found"
    fi
  fi
fi

if [ "$flows_status" -ne 0 ] || [ "$leak_found" -ne 0 ]; then
  exit 1
fi
