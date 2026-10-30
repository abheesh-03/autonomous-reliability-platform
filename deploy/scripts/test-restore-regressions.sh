#!/usr/bin/env bash
#
# test-restore-regressions.sh -- Phase 17A correction round.
#
# Fault-injection regression coverage for deploy/scripts/restore.sh,
# proving the exact false-success bug independent review reported
# (a `docker run` client-launch failure, exit 125, still produced
# "RESTORE COMPLETE") is now fixed, and that it stays fixed. Uses the
# SAME fake-docker-on-PATH technique as
# deploy/scripts/test-preflight-regressions.sh: a fake `docker`
# binary shadows the real one so every case runs in well under a
# second with no real target database or network needed, except
# where a case's own point is that an EARLIER, real check (checksum
# verification) must reject it before any docker call happens.
#
# Never touches the developer's own Postgres/.env/volumes -- this
# constructs its own throwaway artifact directory and never reads
# deploy/.env.deploy at all (restore.sh itself takes no env-file
# argument; it only takes --manifest/--docker-network/--target-*).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
RESTORE_SH="$SCRIPT_DIR/restore.sh"
cd "$REPO_ROOT"

REAL_DOCKER="$(command -v docker)"
[ -n "$REAL_DOCKER" ] || { echo "FAIL: could not resolve the real docker binary" >&2; exit 1; }
export REAL_DOCKER

WORK_DIR="$(mktemp -d)"
if [ -z "${KEEP_WORK_DIR:-}" ]; then
  trap 'rm -rf "$WORK_DIR"' EXIT
else
  echo "KEEP_WORK_DIR set -- leaving $WORK_DIR in place for inspection" >&2
fi

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

# A small, valid artifact directory with correct checksums -- every
# case starts from a fresh copy of this so one case's tampering never
# leaks into another's.
ARTIFACT_SRC="$WORK_DIR/artifact-src"
mkdir -p "$ARTIFACT_SRC"
echo "-- fake roles dump" > "$ARTIFACT_SRC/roles.sql"
echo "-- fake db dump (not a real pg_dump archive; no case here ever lets pg_restore actually parse it)" > "$ARTIFACT_SRC/db.dump"
roles_sha="$(shasum -a 256 "$ARTIFACT_SRC/roles.sql" | awk '{print $1}')"
dump_sha="$(shasum -a 256 "$ARTIFACT_SRC/db.dump" | awk '{print $1}')"
cat > "$ARTIFACT_SRC/manifest.json" <<EOF
{
  "roles_dump_file": "roles.sql",
  "roles_dump_sha256": "$roles_sha",
  "db_dump_file": "db.dump",
  "db_dump_sha256": "$dump_sha"
}
EOF

fresh_artifact_dir() {
  local dir="$WORK_DIR/artifact-$1"
  cp -R "$ARTIFACT_SRC" "$dir"
  echo "$dir"
}

# Common restore.sh invocation. $1 = artifact dir, $2 = output-capture
# file, $3 = creds-out path. Always targets a network/host that is
# never actually dialed in the cases that fail before pg_restore's own
# call, and is intercepted by the fake docker in the ones that reach
# it.
run_restore() {
  local artifact_dir="$1" out_file="$2" creds_out="$3"
  # `< /dev/null`: restore.sh issues some `docker run -i` calls that
  # do not themselves pipe anything in (e.g. the roles.sql replay
  # step) -- those otherwise inherit THIS script's own stdin, which
  # could be a terminal and hang the fake docker's `cat >/dev/null`
  # drain indefinitely. Forcing /dev/null here makes every case
  # deterministic regardless of how this test script itself was
  # invoked.
  TARGET_PGPASSWORD=unused-in-every-fake-case \
    "$RESTORE_SH" \
    --manifest "$artifact_dir/manifest.json" \
    --docker-network test-net \
    --target-host test-target --target-port 5432 \
    --target-db testdb \
    --target-superuser postgres --target-superuser-password-env TARGET_PGPASSWORD \
    --credentials-out "$creds_out" \
    > "$out_file" 2>&1 < /dev/null
}

assert_no_completion_marker() {
  local out_file="$1" label="$2"
  if grep -q "RESTORE COMPLETE" "$out_file"; then
    case_fail "$label: printed RESTORE COMPLETE despite failing -- see $out_file"
    return 1
  fi
  return 0
}

# --- Case 1: corrupt artifact -- checksum mismatch must reject before
# any docker call at all (real `docker` stays on PATH; it must never
# even be invoked in this case). ---
run_case_corrupt_artifact() {
  local dir out creds
  dir="$(fresh_artifact_dir corrupt)"
  echo "TAMPERED" >> "$dir/db.dump"
  out="$WORK_DIR/corrupt_artifact.out"
  creds="$WORK_DIR/corrupt_artifact.creds"
  if run_restore "$dir" "$out" "$creds"; then
    case_fail "corrupt_artifact: exited 0, expected nonzero"
    return
  fi
  if ! grep -q "checksum mismatch" "$out"; then
    case_fail "corrupt_artifact: did not report a checksum mismatch -- see $out"
    return
  fi
  [ -e "$creds" ] && { case_fail "corrupt_artifact: credentials file was created despite failure"; return; }
  assert_no_completion_marker "$out" "corrupt_artifact" && case_pass "corrupt_artifact (rejected before touching docker)"
}

# Fake docker factory: every case below needs the EARLY checks
# (vector extension / db-exists / role-exists / schema-empty /
# roles.sql replay / password ALTERs / pre-create) to succeed so
# execution reaches the ONE call this case cares about -- pg_restore
# itself. FAULT_MODE selects that call's behavior; everything else is
# answered with a fixed, minimal, correct canned response.
write_fake_docker() {
  local bin_dir="$1"
  cat > "$bin_dir/docker" <<'FAKEEOF'
#!/usr/bin/env bash
set -euo pipefail
args="$*"

if [[ "$args" != *"run"* ]]; then
  exec "${REAL_DOCKER:?}" "$@"
fi

# Drain stdin for every call that pipes a script in, matching real
# docker's own behavior of consuming it even when the canned response
# is unconditional.
drain_stdin() { cat >/dev/null 2>&1 || true; }

case "$args" in
  *pg_available_extensions*)
    drain_stdin; echo "t"; exit 0 ;;
  *"pg_database WHERE datname"*)
    drain_stdin; echo "t"; exit 0 ;;
  *"pg_roles WHERE rolname"*)
    drain_stdin; echo "f"; exit 0 ;;
  *"information_schema.tables WHERE table_schema"*)
    drain_stdin; echo "0"; exit 0 ;;
  *roles.sql*)
    drain_stdin; echo "ALTER ROLE"; exit 0 ;;
  *"-d postgres -f -"*)
    # The per-role password ALTER step: its SQL text (containing
    # "LOGIN PASSWORD") is sent over STDIN, not as a CLI argument, so
    # it never appears in argv/"$args" at all -- matching on the
    # distinguishing `-d postgres -f -` argv shape instead is both
    # correct (that is genuinely this call's own signature) and, not
    # incidentally, exactly the property the real fix relies on (the
    # password truly is absent from argv).
    drain_stdin; exit 0 ;;
  *"-d testdb -f -"*)
    drain_stdin; exit 0 ;;
  *"pg_restore -l"*)
    # The archive-listing step: pure local file read, never connects
    # to the target database at all (no -h/-p/-U/-d passed) -- only a
    # docker-launch-level failure can plausibly affect it; every other
    # fault mode below is specific to the MAIN restore replay and
    # must not make this earlier step fail too.
    drain_stdin
    case "${FAULT_MODE:-success}" in
      launch_failure)
        echo "docker: Error response from daemon: network test-net not found" >&2
        exit 125 ;;
      *)
        echo "7; 2615 16385 SCHEMA - reliability postgres"
        echo "222; 1259 16715 TABLE reliability incidents postgres"
        exit 0 ;;
    esac
    ;;
  *pg_restore*)
    drain_stdin
    case "${FAULT_MODE:-success}" in
      launch_failure)
        echo "docker: Error response from daemon: network test-net not found" >&2
        exit 125 ;;
      connection_failure)
        echo "pg_restore: error: connection to server at \"test-target\" (10.0.0.9), port 5432 failed: Connection refused" >&2
        exit 1 ;;
      unexpected_error)
        echo 'pg_restore: error: could not execute query: ERROR:  permission denied for table reliability.incidents' >&2
        exit 1 ;;
      abnormal_termination)
        # The exact independently reported bug: killed by SIGKILL
        # (137) partway through, AFTER already emitting output that
        # -- under the OLD, text-based tolerance logic -- would have
        # looked like a fully successful, tolerated restore. With
        # --exit-on-error and the schema-creation entries excluded
        # from the replay, there is no "schema already exists" line
        # to emit at all any more; this simulates the termination
        # happening after a real table has already started restoring.
        echo 'pg_restore: creating TABLE "reliability.incidents"'
        exit 137 ;;
      success)
        exit 0 ;;
    esac
    ;;
  *)
    drain_stdin
    echo "FAKE DOCKER: unrecognized call: $args" >&2
    exit 99 ;;
esac
FAKEEOF
  chmod +x "$bin_dir/docker"
}

run_pg_restore_case() {
  local name="$1" fault_mode="$2" expect_exit="$3"
  local bin_dir dir out creds actual_exit
  bin_dir="$(mktemp -d)"
  write_fake_docker "$bin_dir"
  dir="$(fresh_artifact_dir "$name")"
  out="$WORK_DIR/$name.out"
  creds="$WORK_DIR/$name.creds"
  set +e
  ( export PATH="$bin_dir:$PATH" FAULT_MODE="$fault_mode"; run_restore "$dir" "$out" "$creds" )
  actual_exit=$?
  set -e
  rm -rf "$bin_dir"
  if [ "$actual_exit" -ne "$expect_exit" ]; then
    case_fail "$name: exit $actual_exit, expected $expect_exit -- see $out"
    return
  fi
  if [ "$expect_exit" -ne 0 ]; then
    assert_no_completion_marker "$out" "$name" && case_pass "$name (exit $actual_exit, expected $expect_exit, no false completion marker)"
  else
    if ! grep -q "RESTORE COMPLETE" "$out"; then
      case_fail "$name: expected RESTORE COMPLETE on a genuinely successful run -- see $out"
      return
    fi
    if [ ! -s "$creds" ]; then
      case_fail "$name: expected --credentials-out to contain the new passwords on success"
      return
    fi
    # CORRECTION ROUND (second pass) -- real finding: BSD/macOS `stat`
    # and GNU/Linux `stat` give `-f` opposite meanings (BSD: a custom
    # format string; GNU: filesystem status instead of file status,
    # a completely different mode). On Linux, `stat -f "%Lp" "$creds"`
    # doesn't cleanly fail the way the old `||` fallback assumed -- it
    # can print real (wrong) filesystem-status output to STDOUT before
    # erroring, and since only stderr was redirected, that stray
    # output landed in `creds_perm` right alongside the fallback
    # `stat -c` call's own output, corrupting the value this
    # comparison depends on. Python's `os.stat` has no such dialect
    # ambiguity and is already a hard dependency of this script's own
    # artifact-manifest parsing elsewhere.
    creds_perm="$(python3 -c "import os,sys; print(oct(os.stat(sys.argv[1]).st_mode)[-3:])" "$creds")"
    [ "$creds_perm" = "600" ] || case_fail "$name: credentials file mode is $creds_perm, expected 600"
    if grep -qE "[0-9a-f]{48}" "$out"; then
      case_fail "$name: a generated password appeared in stdout/stderr, not only in --credentials-out"
      return
    fi
    case_pass "$name (exit 0, RESTORE COMPLETE, credentials written to a mode-600 file, never printed)"
  fi
}

run_case_corrupt_artifact

# --- Case 2: client-launch failure -- the exact independently
# reported bug: `docker run` itself fails (exit 125) before
# pg_restore ever starts. Must fail, never print RESTORE COMPLETE. ---
run_pg_restore_case launch_failure launch_failure 1

# --- Case 3: connection failure -- pg_restore launches but cannot
# reach the target. Must fail. ---
run_pg_restore_case connection_failure connection_failure 1

# --- Case 4: unexpected SQL error -- pg_restore runs and reports a
# real error that is NOT one of the three tolerated "schema already
# exists" lines. Must fail. ---
run_pg_restore_case unexpected_sql_error unexpected_error 1

# --- Case 5: the exact independently reported false-success bug --
# pg_restore is killed by SIGKILL (exit 137) after already emitting
# some real, in-progress output. Must fail -- an abnormal termination
# is never tolerated regardless of how clean the partial output looks
# (there is no more text-based tolerance at all to be fooled by: the
# pre-created schemas are excluded from the replay and the restore
# runs under --exit-on-error, so success now means exit 0, full stop). ---
run_pg_restore_case abnormal_termination_after_partial_output abnormal_termination 1

# --- Case 6: control (fully clean) -- pg_restore exits 0 outright.
# Must succeed, write credentials to the file, and never print them. ---
run_pg_restore_case fully_clean_success success 0

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL RESTORE REGRESSION CASES PASSED"
  exit 0
else
  echo "ONE OR MORE RESTORE REGRESSION CASES FAILED" >&2
  exit 1
fi
