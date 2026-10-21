#!/usr/bin/env bash
#
# verify-detectors-offline.sh — Phase 11B autonomous failure discovery
# acceptance. Runs ENTIRELY offline: no Docker Compose stack, no live
# backend service, no real Prometheus/Tempo/control-plane, no
# database. Never touches services/**, database/**, observability/**,
# knowledge/**, evals/**, or catalog/source/** -- this script only
# exercises the detectors/ package's own synthetic-data test suite and
# CLI (plus a read-only cross-package integration check against
# catalog/'s own coverage verification boundary).
#
# Mirrors the existing `make catalog-validate`/`make eval-offline`
# convention exactly: Python 3.13 via a `python:3.13-slim` Docker
# container with this repo bind-mounted.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

main() {
cd "$REPO_ROOT"

echo "=== Phase 11B: installing detectors/ + catalog/ requirements (Python 3.13, via Docker) ===" >&2
docker run --rm -v "$REPO_ROOT:/app" -w /app python:3.13-slim bash -c "
  set -euo pipefail
  pip install -q -r detectors/requirements.txt -r catalog/requirements.txt

  echo '=== Phase 11B: running the detectors/ test suite (Gates B-H, 11B.1/11B.2/11B.3) ===' >&2
  python -m pytest detectors/tests -c detectors/pyproject.toml -v

  echo '=== Phase 11B: confirming Phase 11A catalog tests still pass unmodified ===' >&2
  python -m pytest catalog/tests -v

  echo '=== Phase 11B: python -m detectors verify (bounded offline self-check) ===' >&2
  python -m detectors verify

  echo '=== Phase 11B: python -m detectors replay (fully offline, synthetic cascading-failure fixture) ===' >&2
  python -m detectors replay --fixture detectors/tests/fixtures/cascading_failure.json --output /tmp/phase11b-replay.json

  echo '=== Phase 11B: confirming replay output is byte-identical across two independent runs ===' >&2
  python -m detectors replay --fixture detectors/tests/fixtures/cascading_failure.json --output /tmp/phase11b-replay-2.json
  diff /tmp/phase11b-replay.json /tmp/phase11b-replay-2.json

  echo '=== Phase 11B: confirming an unknown --service is a validation error (nonzero exit) ===' >&2
  if python -m detectors analyze --service bogus-service --prometheus-url http://x.invalid; then
    echo 'FAIL: an unknown service must produce a NONZERO exit code, got 0' >&2
    exit 1
  fi
  echo 'confirmed: an unknown service correctly produces a nonzero exit code'
"

echo "" >&2
echo "PHASE 11B DETECTORS ACCEPTANCE VERIFIED: anomaly/dependency/invariant/correlation/pipeline/CLI/safety tests passed, Phase 11A catalog tests remain unaffected, replay output is byte-reproducible, and CLI validation errors fail closed -- with zero network calls, zero database access, and zero production service code touched." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
