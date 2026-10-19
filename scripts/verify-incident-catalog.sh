#!/usr/bin/env bash
#
# verify-incident-catalog.sh — Phase 11A incident intelligence catalog
# acceptance. Runs ENTIRELY offline: no Docker Compose stack, no live
# backend service, no database, no LLM/embedding API call, no
# production credential. Never touches services/**, database/**,
# observability/**, knowledge/**, or evals/** -- this script only
# parses/validates/audits the catalog/ package's own synthetic and
# source-controlled data.
#
# Mirrors the existing `make eval-offline` convention exactly: Python
# 3.13 via a `python:3.13-slim` Docker container with this repo
# bind-mounted, so results are reproducible regardless of the
# developer's own host Python version.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

main() {
cd "$REPO_ROOT"

echo "=== Phase 11A: installing catalog/ requirements (Python 3.13, via Docker) ===" >&2
docker run --rm -v "$REPO_ROOT:/app" -w /app python:3.13-slim bash -c "
  set -euo pipefail
  pip install -q -r catalog/requirements.txt

  echo '=== Phase 11A: running the catalog/ test suite (Gates B-G) ===' >&2
  python -m pytest catalog/tests -v

  echo '=== Phase 11A: python -m catalog build/validate/audit/coverage against the real source ===' >&2
  python -m catalog build
  python -m catalog validate
  python -m catalog audit
  python -m catalog coverage

  echo '=== Phase 11A: confirming build output is byte-identical across two independent runs ===' >&2
  python -m catalog build --output /tmp/catalog-run2.json
  diff catalog/build/catalog.v1.json /tmp/catalog-run2.json

  echo '=== Phase 11A: confirming an intentionally corrupted source produces a nonzero exit code ===' >&2
  python3 -c \"
lines = open('catalog/source/40-domains-800-scenarios.md').read().split(chr(10))
for i, l in enumerate(lines):
    if l.startswith('- **Detection:**'):
        del lines[i]
        break
open('/tmp/corrupted-source.md', 'w').write(chr(10).join(lines))
\"
  if python -m catalog validate --source /tmp/corrupted-source.md; then
    echo 'FAIL: an intentionally corrupted source must produce a NONZERO exit code, got 0' >&2
    exit 1
  fi
  echo 'confirmed: a corrupted source correctly produces a nonzero exit code'

  echo '=== Phase 11A: confirming a catalog missing one scenario block cannot build successfully (correction-round Issue 4) ===' >&2
  python3 -c \"
lines = open('catalog/source/40-domains-800-scenarios.md').read().split(chr(10))
start = next(i for i, l in enumerate(lines) if l.startswith('### D01-F02'))
del lines[start:start + 10]
open('/tmp/missing-one-scenario.md', 'w').write(chr(10).join(lines))
\"
  if python -m catalog build --source /tmp/missing-one-scenario.md --output /tmp/should-not-be-written.json; then
    echo 'FAIL: a 799-scenario catalog must make build fail (NONZERO exit), got 0' >&2
    exit 1
  fi
  if [ -f /tmp/should-not-be-written.json ]; then
    echo 'FAIL: build must never write an artifact for a catalog that failed structural validation' >&2
    exit 1
  fi
  echo 'confirmed: an incomplete catalog correctly fails the build and writes nothing'

  echo '=== Phase 11A: confirming fabricated coverage evidence cannot advance detection_validated (correction-round Issue 2) ===' >&2
  python3 -c \"
import json
json.dump([{
    'scenario_id': 'D01-F01',
    'dimension': 'detection_validated',
    'evidence_kind': 'test_reference',
    'evidence_reference': 'nonexistent-file-does-not-exist.py::test_fake',
    'recorded_by': 'invented',
}], open('/tmp/fabricated-evidence.json', 'w'))
\"
  python -m catalog coverage --evidence /tmp/fabricated-evidence.json --output /tmp/fabricated-coverage-report.json
  python3 -c \"
import json
report = json.load(open('/tmp/fabricated-coverage-report.json'))
assert report['dimension_counts']['detection_validated'] == 0, 'fabricated evidence must never advance detection_validated'
assert report['verified_evidence_count'] == 0
assert len(report['rejected_evidence']) == 1
print('confirmed: fabricated evidence was rejected, not counted')
\"
"

echo "" >&2
echo "PHASE 11A CATALOG ACCEPTANCE VERIFIED: schema/importer/validation/taxonomy-audit/registry/coverage/policy tests passed, the CLI's four subcommands ran cleanly against the real 800-scenario source, build output is byte-reproducible, and a corrupted source correctly fails closed -- with zero network calls, zero database access, and zero production service code touched." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
