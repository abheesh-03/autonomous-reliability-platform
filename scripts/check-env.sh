#!/usr/bin/env bash
#
# check-env.sh — Verify local developer tooling for the Autonomous
# Production Reliability Platform.
#
# This script only inspects the machine; it never installs or modifies
# anything. It exits non-zero only if a Phase 0.1 requirement is missing.

set -u

PHASE01_MISSING=0

print_header() {
  echo ""
  echo "== $1 =="
}

# check_tool <label> <command> <version_args...>
check_tool() {
  local label="$1"
  local cmd="$2"
  shift 2

  if command -v "$cmd" >/dev/null 2>&1; then
    local version
    version="$("$cmd" "$@" 2>&1 | head -n 1)"
    printf "  [OK]      %-16s found  (%s)\n" "$label" "$version"
    return 0
  else
    printf "  [MISSING] %-16s not found on PATH\n" "$label"
    return 1
  fi
}

echo "Autonomous Production Reliability Platform — Environment Check"
echo "Platform: $(uname -s) $(uname -r)"

print_header "REQUIRED FOR PHASE 0.1"

check_tool "git" git --version || PHASE01_MISSING=1
check_tool "docker" docker --version || PHASE01_MISSING=1

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  version="$(docker compose version 2>&1 | head -n 1)"
  printf "  [OK]      %-16s found  (%s)\n" "docker compose" "$version"
else
  printf "  [MISSING] %-16s not found (requires 'docker compose', the plugin form)\n" "docker compose"
  PHASE01_MISSING=1
fi

check_tool "claude" claude --version || PHASE01_MISSING=1

print_header "REQUIRED IN LATER PHASES (not required now)"

check_tool "python3" python3 --version
check_tool "node" node --version
check_tool "go" go version
check_tool "java" java -version

print_header "SUMMARY"

if [ "$PHASE01_MISSING" -eq 1 ]; then
  echo "  One or more Phase 0.1 requirements are missing. See [MISSING] above."
  echo "  This script does not install anything — install the missing tool(s) manually."
  exit 1
else
  echo "  All Phase 0.1 requirements are present."
  echo "  Any [MISSING] later-phase tools above are informational only and do not fail this check."
  exit 0
fi
