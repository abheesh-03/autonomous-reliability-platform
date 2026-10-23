#!/usr/bin/env bash
#
# test-db-up-order.sh — Phase 7 correction round (finding #1): a
# static, no-Docker regression test proving the Makefile's `db-up`
# target provisions agent-runtime-service's real checkpoint-database
# credential (AGENT_RUNTIME_DB_PASSWORD, via
# scripts/init-agent-runtime-db.sh) BEFORE the full `docker compose up
# -d` that actually CREATES the agent-runtime-service container --
# never after. A regression here (e.g. someone "simplifying" db-up
# back to a single `docker compose up -d`) would silently reintroduce
# the fresh-checkout race this correction fixed; this test makes that
# regression fail loudly and immediately, with no Compose stack
# needed.
#
# Phase 8 extends this same check to
# scripts/init-remediation-secrets.sh: those six tokens must likewise
# exist in .env before the full 'docker compose up -d' that actually
# CREATES control-plane/agent-runtime-service/tool-gateway/
# payment-service -- otherwise those containers resolve
# ${CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN:-} etc. to empty at
# creation time and never pick up the real value without being
# manually recreated, exactly the fresh-checkout race Phase 7 already
# learned to avoid for the checkpoint DB credential.
#
# Pure text/ordering check against the real Makefile -- never executes
# `make db-up` itself (that would need a real Docker stack; see
# scripts/verify-agent-runtime.sh for the real, running-stack proof).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
MAKEFILE="$REPO_ROOT/Makefile"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$MAKEFILE" ] || fail "$MAKEFILE does not exist"

# Extract the db-up recipe: every line from "db-up:" up to (but not
# including) the next top-level target definition.
recipe="$(awk '
  /^db-up:/ { capture=1; next }
  capture && /^[A-Za-z0-9_.-]+:/ { exit }
  capture { print }
' "$MAKEFILE")"

[ -n "$recipe" ] || fail "could not find a 'db-up:' target with a non-empty recipe in $MAKEFILE"

# Locate each required step's line number WITHIN the recipe (1-indexed,
# in order of first appearance). A missing step reports its own clear
# failure rather than a confusing arithmetic error below.
line_of() {
  local pattern="$1" label="$2"
  local n
  n="$(echo "$recipe" | grep -nF "$pattern" | head -1 | cut -d: -f1 || true)"
  [ -n "$n" ] || fail "db-up's recipe does not contain a line matching $label ($pattern)"
  echo "$n"
}

webhook_line="$(line_of "init-webhook-secret.sh" "the webhook/lifecycle secret init step")"
remediation_secrets_line="$(line_of "init-remediation-secrets.sh" "the Phase 8 remediation secret init step")"
postgres_only_line="$(line_of "docker compose up -d postgres" "'docker compose up -d postgres' (postgres-only, BEFORE the agent-runtime DB init)")"
agent_db_init_line="$(line_of "init-agent-runtime-db.sh" "the agent-runtime checkpoint DB init step")"
# CI preflight fix: Phase 14 gave web-console the EXACT same
# fail-fast-on-bad-credential precedent agent-runtime-service already
# has (docker-compose.yml's own web-console service comment says so
# explicitly) -- an empty/stale WEB_CONSOLE_DB_PASSWORD baked into its
# container at creation time would reproduce the identical
# fresh-checkout race Phase 7 finding #1 already fixed for
# AGENT_RUNTIME_DB_PASSWORD, just for a different credential.
web_console_db_init_line="$(line_of "init-web-console-db.sh" "the web-console auth DB init step")"

# The final, full "docker compose up -d" (no extra service argument) --
# matched as an EXACT recipe line (ignoring leading tab/whitespace) so
# it can never accidentally match "docker compose up -d postgres"
# above.
full_up_line="$(echo "$recipe" | grep -nE '^\s*docker compose up -d\s*$' | head -1 | cut -d: -f1 || true)"
[ -n "$full_up_line" ] || fail "db-up's recipe does not contain a final, full 'docker compose up -d' (no service argument) step"

[ "$webhook_line" -lt "$postgres_only_line" ] || fail "init-webhook-secret.sh must run BEFORE 'docker compose up -d postgres'"
[ "$remediation_secrets_line" -lt "$postgres_only_line" ] || fail "init-remediation-secrets.sh must run BEFORE 'docker compose up -d postgres' -- it does not need PostgreSQL at all, and the six tokens it writes must exist in .env before the full 'docker compose up -d' below creates every container that reads one of them"
[ "$postgres_only_line" -lt "$agent_db_init_line" ] || fail "'docker compose up -d postgres' must run BEFORE init-agent-runtime-db.sh (postgres must exist for that script's own pg_isready wait to make sense)"
[ "$agent_db_init_line" -lt "$full_up_line" ] || fail "init-agent-runtime-db.sh (which writes AGENT_RUNTIME_DB_PASSWORD into .env) must run BEFORE the full 'docker compose up -d' that actually CREATES agent-runtime-service -- otherwise that container is created with an empty/stale password"
[ "$remediation_secrets_line" -lt "$full_up_line" ] || fail "init-remediation-secrets.sh must run BEFORE the full 'docker compose up -d' that actually CREATES control-plane/agent-runtime-service/tool-gateway/payment-service -- otherwise those containers are created with empty/stale remediation tokens"
[ "$postgres_only_line" -lt "$web_console_db_init_line" ] || fail "'docker compose up -d postgres' must run BEFORE init-web-console-db.sh (postgres must exist for that script's own role/schema creation to make sense)"
[ "$web_console_db_init_line" -lt "$full_up_line" ] || fail "init-web-console-db.sh (which writes WEB_CONSOLE_DB_PASSWORD into .env) must run BEFORE the full 'docker compose up -d' that actually CREATES web-console -- otherwise that container is created with an empty/stale password"

echo "PASS: db-up's recipe order is: webhook/lifecycle secrets -> Phase 8 remediation secrets -> 'docker compose up -d postgres' -> init-agent-runtime-db.sh -> init-web-console-db.sh -> full 'docker compose up -d'"
