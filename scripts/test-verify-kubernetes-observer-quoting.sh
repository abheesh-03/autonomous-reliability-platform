#!/usr/bin/env bash
#
# test-verify-kubernetes-observer-quoting.sh — correction round (Issue
# 5) regression test: proves scripts/verify-kubernetes-observer-real-stack.sh
# no longer interpolates KUBE_CONTEXT/KUBE_NAMESPACE directly into the
# text of its generated `bash -c` script (a shell-injection
# vulnerability: an embedded single quote in either value could break
# out of that quoting and run arbitrary shell syntax inside a
# container with --network host and a read-write mount of this whole
# repository).
#
# Two checks, no Docker and no real cluster required:
#   1. STATIC: the real script's source no longer contains the
#      vulnerable pattern (a bare `'$KUBE_CONTEXT'`/`'$KUBE_NAMESPACE'`
#      interpolation inside a double-quoted `bash -c "..."` string),
#      and does pass both values via `-e` (container environment).
#   2. DYNAMIC: the EXACT quoting mechanism the fixed script now uses
#      (`-e VAR=value` + a single-quoted inner script referencing
#      `"$VAR"`) is reproduced here with `env` standing in for
#      `docker run -e` (same semantics: an environment variable,
#      expanded by the inner shell from its own environment, never
#      re-parsed as shell syntax) and a harmless `echo` standing in for
#      `python -m detectors analyze`. Adversarial values containing a
#      single quote, a semicolon, a command substitution, and a
#      newline are proven to reach the command as ONE inert literal
#      argument -- never executed.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
TARGET="$REPO_ROOT/scripts/verify-kubernetes-observer-real-stack.sh"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

[ -f "$TARGET" ] || fail "$TARGET does not exist"

echo "=== STATIC: confirming the vulnerable interpolation pattern is gone ===" >&2
if grep -nE "'\\\$KUBE_CONTEXT'|'\\\$KUBE_NAMESPACE'" "$TARGET" >/dev/null; then
  fail "$TARGET still interpolates \$KUBE_CONTEXT/\$KUBE_NAMESPACE directly inside single-quoted shell text (the Issue 5 vulnerability)"
fi
grep -q -- '-e KUBE_CONTEXT=' "$TARGET" || fail "$TARGET no longer passes KUBE_CONTEXT as a container environment variable (-e KUBE_CONTEXT=...)"
grep -q -- '-e KUBE_NAMESPACE=' "$TARGET" || fail "$TARGET no longer passes KUBE_NAMESPACE as a container environment variable (-e KUBE_NAMESPACE=...)"
echo "confirmed: no direct \$KUBE_CONTEXT/\$KUBE_NAMESPACE interpolation; both are passed via -e"

echo "=== DYNAMIC: reproducing the fixed quoting mechanism with adversarial values ===" >&2

MARKER="$(mktemp -d)/pwned"

run_with_payload() {
  local payload="$1"
  # Mirrors the real script's fixed form exactly: values arrive as
  # environment variables (env ~ docker run -e), and the inner script
  # is single-quoted, referencing them only as "$KUBE_CONTEXT"/
  # "$KUBE_NAMESPACE" -- never outer-shell-interpolated.
  env KUBE_CONTEXT="$payload" KUBE_NAMESPACE="harmless-namespace" bash -c '
    set -euo pipefail
    # Stand-in for: python -m detectors analyze --kube-context "$KUBE_CONTEXT" ...
    printf "ARG:%s\n" "$KUBE_CONTEXT"
  '
}

adversarial_values=(
  "kind-reliability-lab'; touch ${MARKER}-semicolon; echo '"
  "kind-reliability-lab' \$(touch ${MARKER}-subst) '"
  "kind-reliability-lab'
touch ${MARKER}-newline
echo '"
  "plain-value-with-no-special-characters"
)

for payload in "${adversarial_values[@]}"; do
  output="$(run_with_payload "$payload")"
  [ "$output" = "ARG:$payload" ] || fail "adversarial payload was not passed through as one inert literal argument: got $(printf '%q' "$output"), expected $(printf '%q' "ARG:$payload")"
done

if [ -e "${MARKER}-semicolon" ] || [ -e "${MARKER}-subst" ] || [ -e "${MARKER}-newline" ]; then
  fail "an adversarial KUBE_CONTEXT value executed injected shell syntax -- marker file was created"
fi
rm -rf "$(dirname "$MARKER")"

echo "confirmed: single-quote, semicolon, command-substitution, and newline payloads all reached the command as one inert literal argument -- none executed"
echo "PASS: scripts/verify-kubernetes-observer-real-stack.sh's KUBE_CONTEXT/KUBE_NAMESPACE handling is not shell-injectable"
