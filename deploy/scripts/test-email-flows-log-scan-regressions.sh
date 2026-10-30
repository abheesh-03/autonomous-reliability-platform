#!/usr/bin/env bash
#
# test-email-flows-log-scan-regressions.sh -- Phase 17A correction
# round (third pass), item 1.
#
# Real fault-injection regression coverage for
# deploy/scripts/test-email-flows.sh's own log-scanning logic: the
# exact independently reported bug ("fetching logs currently uses
# '|| true', so a failed fetch can produce PASS") plus the two other
# failure classes the correction explicitly calls out -- missing
# tokens, and a successful-but-irrelevant log capture.
#
# Fakes `python3` (so the real network-touching
# deploy/scripts/test-email-flows.py is never actually invoked) and
# `docker` (so `docker compose logs ... caddy` behaves however this
# case needs) on PATH, matching this repository's established
# fault-injection convention (see test-preflight-regressions.sh/
# test-restore-regressions.sh). Never touches the developer's own
# dev stack, never requires a real Caddy/mailpit/web-console.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT" || exit 1

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

REAL_DOCKER="$(command -v docker)"
REAL_PYTHON3="$(command -v python3)"
[ -n "$REAL_DOCKER" ] && [ -n "$REAL_PYTHON3" ] || { echo "FAIL: could not resolve real docker/python3" >&2; exit 1; }
export REAL_DOCKER REAL_PYTHON3

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

REAL_TOKEN="real-leak-token-$$-$(date +%s)"

write_fake_bin() {
  local bin_dir="$1" mode="$2" token_mode="$3"
  cat > "$bin_dir/python3" <<FAKEPYEOF
#!/usr/bin/env bash
set -euo pipefail
args="\$*"
if [[ "\$args" == *"import requests"* ]]; then
  exit 0
fi
if [[ "\$args" == *"test-email-flows.py"* ]]; then
  # Extract the --token-scan-file value the real wrapper always
  # passes, and write it exactly as this case's token_mode dictates --
  # never actually touching the network, mailpit, or a real stack.
  scan_file=""
  prev=""
  for a in "\$@"; do
    if [ "\$prev" = "--token-scan-file" ]; then
      scan_file="\$a"
    fi
    prev="\$a"
  done
  case "$token_mode" in
    no_tokens)
      : > "\$scan_file"
      ;;
    one_real_token)
      echo "$REAL_TOKEN" > "\$scan_file"
      ;;
  esac
  exit 0
fi
exec "\${REAL_PYTHON3:?}" "\$@"
FAKEPYEOF
  chmod +x "$bin_dir/python3"

  cat > "$bin_dir/docker" <<FAKEDOCKEREOF
#!/usr/bin/env bash
set -euo pipefail
args="\$*"
if [[ "\$args" != *"logs"* ]]; then
  exec "\${REAL_DOCKER:?}" "\$@"
fi
case "$mode" in
  log_fetch_failure)
    echo "error response from daemon: no such service: caddy" >&2
    exit 1
    ;;
  missing_relevant_records)
    echo '{"msg":"handled request","request":{"uri":"/unrelated/path"}}'
    exit 0
    ;;
  token_leaked)
    echo '{"msg":"handled request","request":{"uri":"/api/auth/verify-email?token='"$REAL_TOKEN"'"}}'
    exit 0
    ;;
  clean_success)
    echo '{"msg":"handled request","request":{"uri":"/api/auth/verify-email?token=REDACTED"}}'
    echo '{"msg":"handled request","request":{"uri":"/api/auth/reset-password/REDACTED"}}'
    exit 0
    ;;
esac
FAKEDOCKEREOF
  chmod +x "$bin_dir/docker"
}

run_case() {
  local name="$1" docker_mode="$2" token_mode="$3" expect_exit="$4"
  local bin_dir out actual_exit
  bin_dir="$(mktemp -d)"
  write_fake_bin "$bin_dir" "$docker_mode" "$token_mode"
  out="$WORK_DIR/$name.out"
  set +e
  (
    export PATH="$bin_dir:$PATH"
    export DEPLOYMENT_PUBLIC_ORIGIN="https://email-flows-log-scan-test.test"
    export COMPOSE_PROJECT_NAME="arp-email-flows-log-scan-test"
    # The real wrapper does `cd "$REPO_ROOT"` itself; `deploy/.env.deploy`
    # is read only by the real email-flows.py invocation (faked above),
    # never by this wrapper directly, so no real secrets file is needed.
    bash "$SCRIPT_DIR/test-email-flows.sh" > "$out" 2>&1
  )
  actual_exit=$?
  set -e
  rm -rf "$bin_dir"
  if [ "$actual_exit" -eq "$expect_exit" ]; then
    case_pass "$name (exit $actual_exit, expected $expect_exit)"
  else
    case_fail "$name: exit $actual_exit, expected $expect_exit -- see $out"
  fi
}

# --- Case 1: the exact independently reported bug -- the log fetch
# itself fails outright. Must fail, never pass by accident. ---
run_case log_fetch_failure log_fetch_failure one_real_token 1

# --- Case 2: the fetch succeeds but captures something with no
# relevant request record at all (wrong --since window, wrong
# container, an unrelated log line). Must fail -- an irrelevant
# capture is not valid proof of anything. ---
run_case missing_relevant_records missing_relevant_records one_real_token 1

# --- Case 3: no tokens were ever captured to scan for in the first
# place. Must fail -- a vacuous proof is not a passing one. ---
run_case missing_tokens clean_success no_tokens 1

# --- Case 4: a real leak -- the fetch succeeds, the record is
# relevant, and the exact token appears verbatim. Must fail. ---
run_case real_leak_detected token_leaked one_real_token 1

# --- Case 5: control -- fetch succeeds, relevant records present,
# no token leaked. Must pass. ---
run_case fully_clean clean_success one_real_token 0

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL EMAIL-FLOWS LOG-SCAN REGRESSION CASES PASSED"
  exit 0
else
  echo "ONE OR MORE EMAIL-FLOWS LOG-SCAN REGRESSION CASES FAILED" >&2
  exit 1
fi
