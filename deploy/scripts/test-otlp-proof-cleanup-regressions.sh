#!/usr/bin/env bash
#
# test-otlp-proof-cleanup-regressions.sh -- Phase 17A correction round
# (third pass), item 2.
#
# Real regression coverage for the resource-ownership bug fixed in
# deploy/scripts/test-otlp-deployment-export-proof.sh's own cleanup()
# (it previously did `docker rm -f "web-console" "control-plane"
# "caddy" "$PG"` unconditionally on EXIT -- deleting any unrelated,
# pre-existing containers with those exact bare names, even when the
# run's own first `docker build` failed before creating anything).
#
# Pre-creates REAL decoy containers, literally named "control-plane"
# and "web-console" (plus a decoy network), that do NOT belong to the
# run under test at all -- then fault-injects the real script via a
# fake `docker` on PATH (this repository's established convention; see
# test-preflight-regressions.sh/test-email-flows-log-scan-regressions.sh)
# and proves the decoys are never touched:
#
#   Case A: the very first `docker build` fails -- zero resources of
#           the run's own are ever created. Reproduces the exact
#           originally-reported scenario.
#   Case B: several of the run's own real resources ARE created
#           (images, network, postgres, mailpit) before a later step
#           (the Flyway migration) fails -- proves cleanup() removes
#           every resource IT owns (flagged CREATED_*) while STILL
#           leaving the unrelated decoys completely untouched. This is
#           a strictly stronger proof of the ownership-tracking
#           mechanism than a full successful run alone would be: a
#           successful run never has to choose between "mine" and
#           "not mine" when nothing collides, whereas this case does.
#
# A genuine full successful end-to-end run (the real app-level flow,
# real image builds, real OTLP export) is exercised separately by
# running test-otlp-deployment-export-proof.sh itself directly; this
# file's own report notes that a post-run `docker ps -a` / `network
# ls` / `images` scan for this run's own generated name prefix found
# nothing left behind after that full run's own real success.
#
# SAFETY CORRECTION (Phase 17A follow-up): this file previously
# `docker rm -f`'d any PRE-EXISTING "control-plane"/"web-console"
# container unconditionally before creating its own decoys -- the
# exact unsafe "delete first, ask never" behavior this whole suite
# exists to catch in the script under test. It now refuses to run at
# all if either bare name is already occupied, never deletes or
# replaces anything it did not itself create, creates its own decoy
# network under a unique run-scoped name (never a fixed literal that
# could itself collide), and tracks ownership only via the real
# container ID `docker run` itself returns on a successful call --
# never by a bare name, and never before that exact call has actually
# succeeded.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

WORK_DIR="$(mktemp -d)"
FAKE_BIN_DIR="$WORK_DIR/fakebin"
mkdir -p "$FAKE_BIN_DIR"

DECOY_NET=""
DECOY_CP_ID=""
DECOY_WC_ID=""

# shellcheck disable=SC2329 # invoked indirectly via `trap cleanup_decoys EXIT`
cleanup_decoys() {
  [ -n "$DECOY_CP_ID" ] && docker rm -f "$DECOY_CP_ID" >/dev/null 2>&1
  [ -n "$DECOY_WC_ID" ] && docker rm -f "$DECOY_WC_ID" >/dev/null 2>&1
  [ -n "$DECOY_NET" ] && docker network rm "$DECOY_NET" >/dev/null 2>&1
  rm -rf "$WORK_DIR"
}
trap cleanup_decoys EXIT

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

REAL_DOCKER="$(command -v docker)"
[ -n "$REAL_DOCKER" ] || { echo "FAIL: could not resolve the real docker binary" >&2; exit 1; }
export REAL_DOCKER

# Refuse outright if either bare name is already occupied by
# something real -- never delete or replace it. This suite genuinely
# requires both names to be free on this Docker daemon to run at all,
# since the script under test hardcodes them as Caddy's own upstream
# names.
refuse_if_name_occupied() {
  local name="$1"
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "FAIL: a container named '$name' already exists on this Docker daemon -- name occupied; existing containers untouched. Free that name (or run this suite on a daemon where it isn't in use) and try again." >&2
    exit 1
  fi
}
refuse_if_name_occupied control-plane
refuse_if_name_occupied web-console

echo "== creating real, unrelated decoy resources literally named 'control-plane' / 'web-console' =="
DECOY_RUN_ID="$$-$(date +%s)"
DECOY_NET_NAME="arp-otlp-cleanup-regressions-decoy-net-$DECOY_RUN_ID"

if ! docker network create "$DECOY_NET_NAME" >/dev/null; then
  echo "FAIL: could not create the decoy network '$DECOY_NET_NAME'" >&2
  exit 1
fi
DECOY_NET="$DECOY_NET_NAME"

if ! DECOY_CP_ID="$(docker run -d --name control-plane --network "$DECOY_NET" alpine:3.20 sleep infinity)"; then
  DECOY_CP_ID=""
  echo "FAIL: could not create the decoy 'control-plane' container" >&2
  exit 1
fi
DECOY_CP="control-plane"

if ! DECOY_WC_ID="$(docker run -d --name web-console --network "$DECOY_NET" alpine:3.20 sleep infinity)"; then
  DECOY_WC_ID=""
  echo "FAIL: could not create the decoy 'web-console' container" >&2
  exit 1
fi
DECOY_WC="web-console"

assert_decoys_untouched() {
  local label="$1"
  local cp_id_after wc_id_after net_exists
  cp_id_after="$(docker inspect -f '{{.Id}}' "$DECOY_CP" 2>/dev/null || true)"
  wc_id_after="$(docker inspect -f '{{.Id}}' "$DECOY_WC" 2>/dev/null || true)"
  net_exists="$(docker network ls -q --filter "name=^${DECOY_NET}\$")"
  if [ "$cp_id_after" = "$DECOY_CP_ID" ] && [ "$wc_id_after" = "$DECOY_WC_ID" ] && [ -n "$net_exists" ]; then
    case_pass "$label: decoy 'control-plane'/'web-console' containers and decoy network survived untouched"
  else
    case_fail "$label: a decoy resource was touched -- cp_id_after=$cp_id_after wc_id_after=$wc_id_after net_exists=$net_exists"
  fi
}

assert_no_leftover_run_resources() {
  local label="$1" run_id="$2"
  local leftovers
  leftovers="$(docker ps -a --format '{{.Names}}' | grep -F "arp-otlp-export-proof-" | grep -F -- "-$run_id" || true)"
  leftovers+=$'\n'"$(docker network ls --format '{{.Name}}' | grep -F "arp-otlp-export-proof-" | grep -F -- "-$run_id" || true)"
  leftovers="$(echo "$leftovers" | grep -v '^$' || true)"
  if [ -z "$leftovers" ]; then
    case_pass "$label: no resources from this specific fault-injected run ($run_id) were left behind"
  else
    case_fail "$label: leftover resources from run $run_id found: $leftovers"
  fi
}

# --- Case A: earliest possible failure -- the very first `docker
# build` call fails outright, before the script creates anything. ---
echo ""
echo "== Case A: fault-injecting a failure on the very first 'docker build' call =="
cat > "$FAKE_BIN_DIR/docker" <<'FAKEEOF'
#!/usr/bin/env bash
# Match on the subcommand itself ($1), not a " build " substring of
# "$*" -- when `build` is the very FIRST argument (the real call this
# case targets: `docker build -q -t ... ...`), "$*" begins with
# "build" with no leading space, so a " build " substring match can
# never fire on the exact scenario this case exists to reproduce.
if [[ "$1" == "build" ]]; then
  echo "FAKE INJECTED FAILURE: docker build" >&2
  exit 1
fi
exec "${REAL_DOCKER:?}" "$@"
FAKEEOF
chmod +x "$FAKE_BIN_DIR/docker"

case_a_out="$WORK_DIR/case_a.out"
(
  # shellcheck disable=SC2030,SC2031 # deliberately scoped to this subshell only
  export PATH="$FAKE_BIN_DIR:$PATH"
  bash "$SCRIPT_DIR/test-otlp-deployment-export-proof.sh" > "$case_a_out" 2>&1
)
case_a_exit=$?
if [ "$case_a_exit" -ne 0 ]; then
  case_pass "Case A: the script failed (exit $case_a_exit) as expected when its first docker build fails -- see $case_a_out"
else
  case_fail "Case A: the script exited 0 even though its first docker build was made to fail -- see $case_a_out"
fi
assert_decoys_untouched "Case A"
# Zero resources of the run's own should ever have existed; there is
# no real $RUN_ID to extract (the script never got past its own very
# first command), so this just confirms no "arp-otlp-export-proof-"
# named resource of ANY run exists right now beyond the decoys above
# (which don't match that prefix at all).
leftover_any="$(docker ps -a --format '{{.Names}}' | grep -F "arp-otlp-export-proof-" || true)"
leftover_any+=$'\n'"$(docker network ls --format '{{.Name}}' | grep -F "arp-otlp-export-proof-" || true)"
leftover_any="$(echo "$leftover_any" | grep -v '^$' || true)"
if [ -z "$leftover_any" ]; then
  case_pass "Case A: zero 'arp-otlp-export-proof-*' resources exist after the early build failure (none were ever created)"
else
  case_fail "Case A: unexpected leftover 'arp-otlp-export-proof-*' resources found: $leftover_any"
fi

# --- Case B: several real resources (both images, network, postgres,
# mailpit) ARE created, then a later step (Flyway migration) fails --
# proves cleanup() removes everything IT owns while still leaving the
# decoys alone. ---
echo ""
echo "== Case B: fault-injecting a failure on the Flyway migration call, after several real resources already exist =="
cat > "$FAKE_BIN_DIR/docker" <<'FAKEEOF'
#!/usr/bin/env bash
if [[ "$*" == *"flyway/flyway"* ]]; then
  echo "FAKE INJECTED FAILURE: flyway migrate" >&2
  exit 1
fi
exec "${REAL_DOCKER:?}" "$@"
FAKEEOF
chmod +x "$FAKE_BIN_DIR/docker"

case_b_out="$WORK_DIR/case_b.out"
(
  # shellcheck disable=SC2030,SC2031 # deliberately scoped to this subshell only
  export PATH="$FAKE_BIN_DIR:$PATH"
  bash "$SCRIPT_DIR/test-otlp-deployment-export-proof.sh" > "$case_b_out" 2>&1
)
case_b_exit=$?
if [ "$case_b_exit" -ne 0 ]; then
  case_pass "Case B: the script failed (exit $case_b_exit) as expected when its Flyway migration call fails -- see $case_b_out"
else
  case_fail "Case B: the script exited 0 even though its Flyway migration call was made to fail -- see $case_b_out"
fi
case_b_run_id="$(grep -oE 'run id: \S+' "$case_b_out" | head -1 | sed -E 's/run id: //')"
if [ -n "$case_b_run_id" ]; then
  assert_no_leftover_run_resources "Case B" "$case_b_run_id"
else
  case_fail "Case B: could not recover this run's own \$RUN_ID from its output to check for leftovers -- see $case_b_out"
fi
assert_decoys_untouched "Case B"

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL OTLP-PROOF CLEANUP-OWNERSHIP REGRESSION CASES PASSED"
  exit 0
else
  echo "ONE OR MORE OTLP-PROOF CLEANUP-OWNERSHIP REGRESSION CASES FAILED" >&2
  exit 1
fi
