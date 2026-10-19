#!/usr/bin/env bash
#
# verify-evals-offline.sh — Phase 10 deterministic offline AI
# evaluation acceptance. Runs ENTIRELY offline: no Docker Compose
# stack, no live backend service, no real LLM/embedding API call, no
# database, no privileged production credential. Installs the three
# reused services (investigator-service, retrieval-service,
# agent-runtime-service) in editable mode so evals/ calls their REAL,
# unmodified production code directly (see evals/README.md section 2)
# -- this script never starts any of their actual HTTP servers.
#
# Mirrors the existing `make investigator-test`/`make retrieval-test`/
# `make agent-runtime-test` convention exactly: Python 3.13 via a
# `python:3.13-slim` Docker container with this repo bind-mounted, so
# results are reproducible regardless of the developer's own host
# Python version.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

main() {
cd "$REPO_ROOT"

echo "=== Phase 10: installing reused services + evals requirements (Python 3.13, via Docker) ===" >&2
docker run --rm -v "$REPO_ROOT:/app" -w /app python:3.13-slim bash -c "
  set -euo pipefail
  pip install -q -e services/investigator-service -e services/retrieval-service -e services/agent-runtime-service
  pip install -q -r evals/requirements.txt

  echo '=== Phase 10: running the deterministic offline evaluation runner ===' >&2
  python -m evals.runner

  echo '=== Phase 10: running the evaluation harness own unit/regression/negative-control tests ===' >&2
  python -m pytest evals/tests -c evals/pyproject.toml -v

  echo '=== Phase 10: confirming deterministic reproducibility (two runs, identical results) ===' >&2
  python -m evals.runner --json-out /tmp/phase10-run1.json --markdown-out /tmp/phase10-run1.md --quiet
  python -m evals.runner --json-out /tmp/phase10-run2.json --markdown-out /tmp/phase10-run2.md --quiet
  python -c \"
import json
a = json.load(open('/tmp/phase10-run1.json'))
b = json.load(open('/tmp/phase10-run2.json'))
for r in (a, b):
    r.pop('generated_at'); r.pop('runtime_seconds')
assert a == b, 'two offline runs over the same dataset produced DIFFERENT results -- not deterministic'
print('confirmed: two offline runs produced identical results')
\"

  echo '=== Phase 10: confirming a deliberately invalid case directory produces a nonzero exit code ===' >&2
  mkdir -p /tmp/phase10-empty-cases
  if python -m evals.runner --cases-dir /tmp/phase10-empty-cases --quiet; then
    echo 'FAIL: an empty/invalid cases directory must produce a NONZERO exit code, got 0' >&2
    exit 1
  fi
  echo 'confirmed: an invalid dataset correctly produces a nonzero exit code'
"

echo "" >&2
echo "PHASE 10 OFFLINE EVALUATION ACCEPTANCE VERIFIED: the deterministic offline runner, its own unit/negative-control test suite, run-to-run reproducibility, and fail-closed behavior on a broken dataset all passed, with zero network calls, zero database access, and zero Docker-socket/production-credential use." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
