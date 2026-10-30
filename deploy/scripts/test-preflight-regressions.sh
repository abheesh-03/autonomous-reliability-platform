#!/usr/bin/env bash
#
# test-preflight-regressions.sh -- Phase 17A correction round, item 2:
# real regression coverage for deploy/scripts/preflight.sh's own
# fail-closed behavior. Encodes the EXACT scenarios independent fault
# injection found broken in the prior round (an empty-hostname origin
# passing, and a malformed `docker compose config` JSON result being
# silently read as "no offenders"), plus the other failure classes
# the correction round asked for: failed commands and insecure
# settings generally.
#
# Never touches the developer's own .env or local-development stack.
# Never brings up any real container -- every case here either
# exercises preflight.sh against a disposable, hand-built
# deploy/.env.deploy copy, or against a FAKE `docker` binary placed
# first on PATH to simulate a command failure/malformed output
# without needing Docker itself to misbehave for real.
#
# Usage: ./deploy/scripts/test-preflight-regressions.sh
# Exits 0 only if every case below behaves as expected; prints a
# PASS/FAIL line per case.

set -uo pipefail

REAL_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REAL_DEPLOY_DIR="$(cd -- "$REAL_SCRIPT_DIR/.." &>/dev/null && pwd)"
REAL_REPO_ROOT="$(cd -- "$REAL_DEPLOY_DIR/.." &>/dev/null && pwd)"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# CORRECTION ROUND (third pass) -- real finding: two of the cases
# below previously mutated the REAL `deploy/docker-compose.override.yml`
# and the REAL `deploy/scripts/validate-merged-config.py` IN PLACE,
# restoring each only via an inline `teardown_*` call immediately
# after that one case ran -- never via this script's own top-level
# `EXIT` trap. A kill/crash/interruption WHILE either real file sat in
# its temporarily-broken state (between the backup and that inline
# restore) left it corrupted in the actual working tree with nothing
# to fix it. Fixed by never touching the real files at all: an
# ISOLATED COPY of the whole `deploy/` directory is built once, here,
# plus symlinks back to the real repo-root paths `docker compose
# config` needs to resolve (`docker-compose.yml`'s own build contexts
# and bind-mount sources) -- `database/`, `observability/`,
# `services/`, `scripts/`, `knowledge/` (verified directly against
# docker-compose.yml's and deploy/docker-compose.override.yml's own
# real relative-path references, not guessed). `SCRIPT_DIR`/
# `DEPLOY_DIR`/`REPO_ROOT` are then reassigned to point INTO that
# isolated tree -- every reference throughout the REST of this file
# (every `setup_*`/`build_valid_env`/`run_case` call, including the
# two cases that used to mutate real files) therefore already
# operates on the isolated copy with no further changes needed, since
# `preflight.sh`/`init-deploy-secrets.sh`/`validate-merged-config.py`
# all resolve their own paths from `${BASH_SOURCE[0]}` at the moment
# THIS script invokes them -- i.e. from inside the isolated tree, when
# this script runs the isolated COPY of them (never the real ones).
# The whole isolated tree is torn down by the SAME top-level `EXIT`
# trap that already cleans up `$WORK_DIR` -- nothing is left behind,
# interrupted or not, because nothing real was ever opened for
# writing in the first place.
ISOLATED_ROOT="$WORK_DIR/isolated-repo"
mkdir -p "$ISOLATED_ROOT"
cp -R "$REAL_DEPLOY_DIR" "$ISOLATED_ROOT/deploy"
for repo_root_path in docker-compose.yml database observability services scripts knowledge; do
  if [ -e "$REAL_REPO_ROOT/$repo_root_path" ]; then
    ln -s "$REAL_REPO_ROOT/$repo_root_path" "$ISOLATED_ROOT/$repo_root_path"
  fi
done

DEPLOY_DIR="$ISOLATED_ROOT/deploy"
SCRIPT_DIR="$DEPLOY_DIR/scripts"
REPO_ROOT="$ISOLATED_ROOT"
cd "$REPO_ROOT" || exit 1

# A pristine snapshot of the two isolated files that later cases
# mutate (docker-compose.override.yml, validate-merged-config.py),
# taken once, right after the isolated tree is built. `build_valid_env`
# (below) restores BOTH from this snapshot on every call -- not just
# resetting `.env.deploy`/`secrets/` as it always has -- so each case
# starts from the same known-good isolated baseline regardless of what
# a PRIOR case mutated. This is still entirely within the disposable
# isolated tree; the real repository is never involved.
PRISTINE_OVERRIDE="$WORK_DIR/pristine-override.yml"
PRISTINE_VALIDATOR="$WORK_DIR/pristine-validate-merged-config.py"
cp "$DEPLOY_DIR/docker-compose.override.yml" "$PRISTINE_OVERRIDE"
cp "$SCRIPT_DIR/validate-merged-config.py" "$PRISTINE_VALIDATOR"

# Resolved ONCE, before any fake `docker` is ever placed on PATH --
# every fake docker script below execs this exact absolute path
# directly for the fall-through case, never searching PATH again at
# call time (searching again while a fake docker is already shadowing
# the real one is exactly what caused a real, reproduced runaway
# recursion/hang during this file's own development).
REAL_DOCKER="$(command -v docker)"
[ -n "$REAL_DOCKER" ] || { echo "FAIL: could not resolve the real docker binary" >&2; exit 1; }
export REAL_DOCKER

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

# Builds a fully valid deploy/.env.deploy (every real secret
# generated for real) as a known-good baseline every case below
# mutates from, then restores it before the next case.
build_valid_env() {
  # Reset the two isolated files a PRIOR case may have mutated
  # (docker-compose.override.yml, validate-merged-config.py) back to
  # their pristine isolated-tree state before every case -- so case
  # ordering never matters and a mutating case never leaks into the
  # next one, without needing a per-case inline teardown at all.
  cp "$PRISTINE_OVERRIDE" "$DEPLOY_DIR/docker-compose.override.yml"
  cp "$PRISTINE_VALIDATOR" "$SCRIPT_DIR/validate-merged-config.py"
  cp "$DEPLOY_DIR/.env.deploy.example" "$DEPLOY_DIR/.env.deploy"
  sed -i.bak \
    -e 's#^DEPLOYMENT_PUBLIC_ORIGIN=.*#DEPLOYMENT_PUBLIC_ORIGIN=https://preflight-regression-test.test#' \
    -e 's#^SMTP_HOST=.*#SMTP_HOST=mailpit#' \
    -e 's#^SMTP_FROM_ADDRESS=.*#SMTP_FROM_ADDRESS=noreply@preflight-regression-test.test#' \
    -e 's#^SMTP_SECURITY=.*#SMTP_SECURITY=none#' \
    "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
  echo "ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true" >> "$DEPLOY_DIR/.env.deploy"
  # Each case gets a fresh CONTROL_PLANE_WEBHOOK_TOKEN (the .env.deploy
  # file is recreated from scratch above) -- the deployment-owned
  # webhook secret file from a PRIOR case would now correctly fail
  # init-deploy-secrets.sh's own consistency check (it does not match
  # the new token), which is correct production behavior but not what
  # this harness wants between independent cases.
  rm -f "$DEPLOY_DIR/secrets/webhook-token"
  "$SCRIPT_DIR/init-deploy-secrets.sh" > /dev/null
}

run_case() {
  # $1 = case name, $2 = expected exit (0 or 1). Dispatches to a
  # function named "setup_<name>", called indirectly below --
  # shellcheck disable=SC2329 (every setup_* function IS invoked,
  # just not by a literal call shellcheck can trace statically).
  local name="$1" expected_exit="$2"
  local actual_exit
  "setup_${name}"
  ./deploy/scripts/preflight.sh > "$WORK_DIR/${name}.out" 2>&1
  actual_exit=$?
  if [ "$actual_exit" -eq "$expected_exit" ]; then
    case_pass "$name (exit $actual_exit, expected $expected_exit)"
  else
    case_fail "$name: exit $actual_exit, expected $expected_exit -- see $WORK_DIR/${name}.out"
  fi
}

# --- Case 1: the exact independently-reproduced empty-hostname origin bug ---
setup_empty_hostname_origin() {
  build_valid_env
  sed -i.bak 's#^DEPLOYMENT_PUBLIC_ORIGIN=.*#DEPLOYMENT_PUBLIC_ORIGIN=https://#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case empty_hostname_origin 1

# --- Case 2: origin with userinfo/path/query (never valid) ---
setup_origin_with_userinfo() {
  build_valid_env
  sed -i.bak 's#^DEPLOYMENT_PUBLIC_ORIGIN=.*#DEPLOYMENT_PUBLIC_ORIGIN=https://user:pass@example.test#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case origin_with_userinfo 1

setup_origin_http_scheme() {
  build_valid_env
  sed -i.bak 's#^DEPLOYMENT_PUBLIC_ORIGIN=.*#DEPLOYMENT_PUBLIC_ORIGIN=http://example.test#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case origin_http_scheme 1

# --- Case 3: the exact independently-reproduced malformed-JSON bug,
#     via a fake `docker` on PATH (restored by case teardown below) ---
FAKE_BIN_DIR="$WORK_DIR/fakebin"
mkdir -p "$FAKE_BIN_DIR"
setup_malformed_compose_json() {
  build_valid_env
  cat > "$FAKE_BIN_DIR/docker" <<'FAKEEOF'
#!/usr/bin/env bash
if [[ "$*" == *"config --format json"* ]]; then
  echo '{not valid json!!'
  exit 0
fi
exec "${REAL_DOCKER:?}" "$@"
FAKEEOF
  chmod +x "$FAKE_BIN_DIR/docker"
}
PATH="$FAKE_BIN_DIR:$PATH" run_case malformed_compose_json 1

# --- Case 4: docker compose itself fails (nonzero exit, real stderr) ---
setup_failed_compose_command() {
  build_valid_env
  cat > "$FAKE_BIN_DIR/docker" <<'FAKEEOF'
#!/usr/bin/env bash
if [[ "$*" == *"config --format json"* ]]; then
  echo "service 'control-plane' has neither an image nor a build context specified" >&2
  exit 15
fi
exec "${REAL_DOCKER:?}" "$@"
FAKEEOF
  chmod +x "$FAKE_BIN_DIR/docker"
}
PATH="$FAKE_BIN_DIR:$PATH" run_case failed_compose_command 1

# --- Case 5: the !override capability probe itself fails (simulates
#     a too-old Compose that silently concatenates instead of
#     replacing) ---
setup_override_capability_regression() {
  build_valid_env
  cat > "$FAKE_BIN_DIR/docker" <<'FAKEEOF'
#!/usr/bin/env bash
real="${REAL_DOCKER:?}"
if [[ "$*" == *"base.yml"* && "$*" == *"override.yml"* && "$*" == *"config --format json"* ]]; then
  # Simulate the OLD (pre-2.24) concatenating merge behavior: the
  # ports list from BOTH files survives.
  echo '{"services": {"probe": {"ports": [{"published": "1"}, {"published": "2"}]}}}'
  exit 0
fi
exec "$real" "$@"
FAKEEOF
  chmod +x "$FAKE_BIN_DIR/docker"
}
PATH="$FAKE_BIN_DIR:$PATH" run_case override_capability_regression 1

# --- Case 6: insecure settings -- organization enforcement disabled ---
setup_org_enforcement_disabled() {
  build_valid_env
  sed -i.bak 's#^CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=.*#CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=false#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case org_enforcement_disabled 1

setup_insecure_cookies() {
  build_valid_env
  sed -i.bak 's#^WEB_CONSOLE_USE_SECURE_COOKIES=.*#WEB_CONSOLE_USE_SECURE_COOKIES=false#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case insecure_cookies 1

setup_relaxed_rate_limits() {
  build_valid_env
  sed -i.bak 's#^WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS=.*#WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS=true#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case relaxed_rate_limits 1

setup_wildcard_trusted_proxy() {
  build_valid_env
  sed -i.bak 's#^TRUSTED_PROXY_HOSTS=.*#TRUSTED_PROXY_HOSTS=*#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case wildcard_trusted_proxy 1

setup_negative_retention_days() {
  build_valid_env
  sed -i.bak 's#^TELEMETRY_RETENTION_DAYS=.*#TELEMETRY_RETENTION_DAYS=-5#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case negative_retention_days 1

setup_absurd_batch_size() {
  build_valid_env
  sed -i.bak 's#^TELEMETRY_RETENTION_BATCH_SIZE=.*#TELEMETRY_RETENTION_BATCH_SIZE=999999999#' "$DEPLOY_DIR/.env.deploy"
  rm -f "$DEPLOY_DIR/.env.deploy.bak"
}
run_case absurd_batch_size 1

# --- Case 7: the exact "variable correct in .env but never reaches
#     the container" class of bug -- simulated by pointing the
#     override file reference used by the merged-config check at a
#     broken, security-stripping override (never the real one). ---
setup_merged_config_catches_dropped_env_var() {
  build_valid_env
  # A deliberately broken override file that OMITS
  # CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT from web-console's own
  # environment block -- the exact real bug this round's own
  # validator was written to catch. Swapped in only for this one case.
  # CORRECTION ROUND (third pass): mutates ONLY the isolated copy
  # (`$DEPLOY_DIR` now points inside `$ISOLATED_ROOT`, never the real
  # `deploy/`) -- no backup/restore needed any more, since the whole
  # isolated tree is disposed of by this script's own top-level `EXIT`
  # trap regardless of outcome. The real `deploy/docker-compose.override.yml`
  # is never opened for writing at all.
  python3 -c "
content = open('$DEPLOY_DIR/docker-compose.override.yml').read()
marker = 'WEB_CONSOLE_TRUSTED_ORIGIN: \${DEPLOYMENT_PUBLIC_ORIGIN}'
assert content.count(marker) == 1, 'expected unique web-console marker not found -- test fixture is stale'
start = content.index(marker)
target = '      TRUSTED_PROXY_ENABLED: \${TRUSTED_PROXY_ENABLED:-true}\n      TRUSTED_PROXY_HOSTS: \${TRUSTED_PROXY_HOSTS:-caddy}\n'
pos = content.index(target, start)
broken = content[:pos] + content[pos + len(target):]
assert broken != content, 'expected substring not found after web-console marker -- test fixture is stale'
open('$DEPLOY_DIR/docker-compose.override.yml', 'w').write(broken)
"
}
setup_merged_config_catches_dropped_env_var
./deploy/scripts/preflight.sh > "$WORK_DIR/merged_config_catches_dropped_env_var.out" 2>&1
actual_exit=$?
if [ "$actual_exit" -eq 1 ] && grep -q "TRUSTED_PROXY_ENABLED" "$WORK_DIR/merged_config_catches_dropped_env_var.out"; then
  case_pass "merged_config_catches_dropped_env_var (exit 1, and named the specific missing variable)"
else
  case_fail "merged_config_catches_dropped_env_var: exit $actual_exit -- see $WORK_DIR/merged_config_catches_dropped_env_var.out"
fi

# --- Case 8: the exact independently reported false-success bug --
# validate-merged-config.py exits non-zero but prints NOTHING to
# stderr (a silent crash/unhandled exception/bare sys.exit(N)) --
# preflight.sh must still mark this a failure from the exit status
# alone, never inferring success from the absence of printed detail. ---
setup_silent_nonzero_validator() {
  build_valid_env
  # Same reasoning as the override-file case above: mutates ONLY the
  # isolated copy of validate-merged-config.py, never the real
  # `deploy/scripts/validate-merged-config.py` -- no backup/restore
  # needed, the isolated tree is disposable.
  cat > "$SCRIPT_DIR/validate-merged-config.py" <<'FAKEEOF'
#!/usr/bin/env python3
import sys
sys.exit(1)  # non-zero, but deliberately no stdout/stderr at all
FAKEEOF
}
setup_silent_nonzero_validator
./deploy/scripts/preflight.sh > "$WORK_DIR/silent_nonzero_validator.out" 2>&1
actual_exit=$?
if [ "$actual_exit" -eq 1 ] && grep -q "FAIL" "$WORK_DIR/silent_nonzero_validator.out"; then
  case_pass "silent_nonzero_validator (exit 1, marked as a real failure despite empty validator output)"
else
  case_fail "silent_nonzero_validator: exit $actual_exit -- see $WORK_DIR/silent_nonzero_validator.out"
fi

# --- Case 9: control -- a genuinely valid configuration must still pass ---
setup_fully_valid_control() {
  build_valid_env
}
run_case fully_valid_control 0

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL PREFLIGHT REGRESSION CASES PASSED"
  exit 0
else
  echo "ONE OR MORE PREFLIGHT REGRESSION CASES FAILED" >&2
  exit 1
fi
