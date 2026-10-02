#!/usr/bin/env bash
#
# init-webhook-secret.sh — control-plane local secret setup
# (Phase 3C webhook token, extended Phase 3D with a second, separate
# lifecycle token).
#
# Manages TWO independent, never-interchangeable Bearer tokens:
#
#   1. CONTROL_PLANE_WEBHOOK_TOKEN (Phase 3C) — generated and written
#      to the two places it needs to reach:
#        a. .env (read by docker-compose.yml's control-plane service
#           environment block). This is the AUTHORITATIVE copy.
#        b. observability/alertmanager/secrets/webhook-token
#           (gitignored via the repo's existing blanket "secrets/"
#           rule) — bind-mounted read-only, as a single FILE (not its
#           parent directory — see docker-compose.yml's alertmanager
#           service for why), into the alertmanager container, and
#           referenced by its http_config.authorization.credentials_file
#           (see observability/alertmanager/alertmanager.yml).
#   2. CONTROL_PLANE_LIFECYCLE_TOKEN (Phase 3D) — generated and written
#      ONLY to .env. Never mirrored into any file, never given to
#      Alertmanager in any way — it authenticates the separate
#      human/operator PATCH /api/v1/incidents/{id}/status endpoint,
#      which Alertmanager must never be able to invoke. Deliberately
#      independent randomness from the webhook token, not derived from
#      it.
#
# This is local-development security, not a production secrets
# framework: shared Bearer tokens in plaintext, generated and
# distributed by a shell script. No external secrets service, no
# rotation automation, no per-client credentials.
#
# Permissions: the pinned prom/alertmanager:v0.34.1 image runs as a
# real non-root user ("nobody", uid/gid 65534 — confirmed via `docker
# inspect prom/alertmanager:v0.34.1 --format '{{.Config.User}}'`), not
# root, and this script does not run as that uid either (nor does it
# attempt to chown to it, which would require privileges this script
# shouldn't need). So: the secrets/ DIRECTORY is kept owner-only
# (0700) — no other host user can list or traverse into it — while the
# webhook-token FILE itself is 0644 (owner read/write, everyone else
# read-only), the minimum permission that reliably lets an arbitrary
# non-root container UID read its content without knowing or matching
# that UID in advance. The file being 0644 does not expose it more
# broadly than the directory already allows: reaching it by path still
# requires traversing the 0700 directory, which only this file's owner
# can do.
#
# Idempotent and safe to rerun: .env's CONTROL_PLANE_WEBHOOK_TOKEN is
# authoritative. If it already holds a value, that value is NEVER
# regenerated or overwritten — this deliberately avoids rotating the
# secret out from under already-running containers (control-plane
# only reads it once, at its own process startup). What IS checked on
# every run is whether the Alertmanager-side file's actual content
# still matches .env's value; if it has drifted (e.g. a stale copy
# from before a manual .env edit, or a missing/corrupted file), it is
# repaired in place from the authoritative .env value — never the
# other way around. Never prints the secret value to stdout/stderr.
#
# Safe on a fresh checkout (.env itself, and the secrets/ directory,
# may not exist yet — e.g. a brand-new GitHub Actions runner) and on a
# pre-existing local .env (never touches POSTGRES_*/GRAFANA_*/any other
# existing variable; only ever adds, replaces, or reads its own
# CONTROL_PLANE_WEBHOOK_TOKEN= line).
#
# Ends with a real preflight: confirms, using the actual pinned
# Alertmanager image and its actual non-root user, that the token file
# is readable — not merely that the host-side chmod "looks right".
# Never prints the file's contents, only whether it was readable.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env"
SECRET_DIR="observability/alertmanager/secrets"
SECRET_FILE="$SECRET_DIR/webhook-token"
ALERTMANAGER_IMAGE="prom/alertmanager:v0.34.1"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "created $ENV_FILE from .env.example"
fi

mkdir -p "$SECRET_DIR"
chmod 700 "$SECRET_DIR"

# .env is authoritative. An existing, non-empty value here is never
# regenerated.
existing_token="$(grep -E '^CONTROL_PLANE_WEBHOOK_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"

if [ -n "$existing_token" ]; then
  token="$existing_token"
  current_secret_file_content=""
  if [ -f "$SECRET_FILE" ]; then
    current_secret_file_content="$(cat "$SECRET_FILE")"
  fi
  if [ "$current_secret_file_content" = "$token" ]; then
    echo "CONTROL_PLANE_WEBHOOK_TOKEN already set in $ENV_FILE and $SECRET_FILE is in sync with it — leaving both unchanged."
  else
    # .env is authoritative: repair the Alertmanager-side copy to
    # match it. Written in place (truncate-and-rewrite the existing
    # inode, never delete-and-replace), so a container that already
    # has this file bind-mounted sees the correction without a
    # restart.
    printf '%s' "$token" > "$SECRET_FILE"
    echo "repaired a stale/missing $SECRET_FILE from the existing, authoritative $ENV_FILE value (value not printed; .env was NOT changed)"
  fi
else
  token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new CONTROL_PLANE_WEBHOOK_TOKEN"
  if grep -qE '^CONTROL_PLANE_WEBHOOK_TOKEN=' "$ENV_FILE"; then
    # Present but empty — replace just that one line, nothing else.
    tmp="$(mktemp)"
    sed "s|^CONTROL_PLANE_WEBHOOK_TOKEN=.*|CONTROL_PLANE_WEBHOOK_TOKEN=$token|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    {
      echo ""
      echo "# --- Phase 3C: Alertmanager -> control-plane webhook (local dev only) ---"
      echo "# Generated by scripts/init-webhook-secret.sh; the identical value is"
      echo "# also mirrored into observability/alertmanager/secrets/webhook-token"
      echo "# (gitignored). This line is authoritative — never rotated automatically"
      echo "# by that script; delete it and rerun the script to force a new value."
      echo "CONTROL_PLANE_WEBHOOK_TOKEN=$token"
    } >> "$ENV_FILE"
  fi
  printf '%s' "$token" > "$SECRET_FILE"
fi

chmod 600 "$ENV_FILE"
# 0644, not 0600: see the file-level comment above for why the
# container's non-root "nobody" user needs "other"-read here, and why
# that doesn't widen real exposure given the 0700 containing directory.
chmod 644 "$SECRET_FILE"

# --------------------------------------------------------------------
# Phase 3D: CONTROL_PLANE_LIFECYCLE_TOKEN — the separate human/operator
# lifecycle-endpoint secret. Simpler than the webhook token above:
# nothing to mirror into a second file, since nothing other than this
# control-plane process itself ever needs to read it — it reaches the
# container purely as an environment variable, so there is no
# container-user-permission problem to solve and no preflight to run.
# Same idempotent, .env-is-authoritative, never-silently-rotated
# pattern as the webhook token.
# --------------------------------------------------------------------
existing_lifecycle_token="$(grep -E '^CONTROL_PLANE_LIFECYCLE_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"

if [ -n "$existing_lifecycle_token" ]; then
  lifecycle_token="$existing_lifecycle_token"
  echo "CONTROL_PLANE_LIFECYCLE_TOKEN already set in $ENV_FILE — leaving it unchanged."
else
  lifecycle_token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new CONTROL_PLANE_LIFECYCLE_TOKEN"
  if grep -qE '^CONTROL_PLANE_LIFECYCLE_TOKEN=' "$ENV_FILE"; then
    tmp="$(mktemp)"
    sed "s|^CONTROL_PLANE_LIFECYCLE_TOKEN=.*|CONTROL_PLANE_LIFECYCLE_TOKEN=$lifecycle_token|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    {
      echo ""
      echo "# --- Phase 3D: human/operator incident lifecycle endpoint (local dev only) ---"
      echo "# Generated by scripts/init-webhook-secret.sh. Deliberately a DIFFERENT,"
      echo "# independently-random value from CONTROL_PLANE_WEBHOOK_TOKEN above —"
      echo "# Alertmanager is never given this one, so it cannot invoke"
      echo "# PATCH /api/v1/incidents/{id}/status. Never mirrored into any file."
      echo "# This line is authoritative — never rotated automatically; delete it"
      echo "# and rerun this script to force a new value."
      echo "CONTROL_PLANE_LIFECYCLE_TOKEN=$lifecycle_token"
    } >> "$ENV_FILE"
  fi
fi

chmod 600 "$ENV_FILE"

# --------------------------------------------------------------------
# Post-review correction: the whole point of two separate tokens is
# that Alertmanager must never be able to invoke the human/operator
# lifecycle endpoint, and vice versa. That guarantee is silently
# defeated if they end up holding the SAME value — whether from an
# astronomically unlikely collision between two independently
# generated 256-bit values, or (the real, plausible risk) an operator
# hand-editing .env and pasting the same value into both lines. Fail
# closed here, before declaring either secret "ready", rather than
# silently rotating either existing value to fix it ourselves — this
# script does not know which of the two (if either) the operator
# actually intended to be correct. core/config.py's
# resolve_write_tokens() is a second, independent, application-level
# guard against this same misconfiguration, for the case where this
# initializer is bypassed entirely (e.g. tokens set directly via some
# other deployment mechanism) — see its own docstring.
# --------------------------------------------------------------------
if [ "$token" = "$lifecycle_token" ]; then
  fail "CONTROL_PLANE_WEBHOOK_TOKEN and CONTROL_PLANE_LIFECYCLE_TOKEN are identical. These authenticate two separate, non-interchangeable write paths (Alertmanager vs. a human/operator) and must never share a value. Edit .env by hand to give one of them a different value, or delete both lines and rerun this script to generate two fresh, independently random tokens. (values not shown)"
fi

echo "webhook secret ready: $ENV_FILE (CONTROL_PLANE_WEBHOOK_TOKEN) and $SECRET_FILE both set (value not printed)."
echo "lifecycle secret ready: $ENV_FILE (CONTROL_PLANE_LIFECYCLE_TOKEN) set (value not printed)."

# --------------------------------------------------------------------
# Preflight: confirm the ACTUAL pinned Alertmanager image, running as
# its ACTUAL non-root user, can read the webhook-token file. Checks
# readability only (`test -r` / `test -s`) — never cats or echoes the
# file's content, so the token itself never reaches any log. Only the
# webhook token has a file to check; the lifecycle token has none.
# --------------------------------------------------------------------
if docker run --rm --entrypoint sh \
    -v "$REPO_ROOT/$SECRET_FILE:/check/webhook-token:ro" \
    "$ALERTMANAGER_IMAGE" \
    -c 'test -r /check/webhook-token && test -s /check/webhook-token' >/dev/null 2>&1
then
  echo "preflight OK: $SECRET_FILE is readable (and non-empty) by the real $ALERTMANAGER_IMAGE image's actual non-root user"
else
  fail "$SECRET_FILE is NOT readable by $ALERTMANAGER_IMAGE's actual non-root user — check host file/directory permissions (expected: $SECRET_DIR 0700, $SECRET_FILE 0644)"
fi
