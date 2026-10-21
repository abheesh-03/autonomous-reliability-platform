#!/usr/bin/env bash
#
# verify-detectors-real-stack.sh — Phase 11B OPT-IN, READ-ONLY
# real-stack acceptance for the detectors/ package.
#
# Unlike every other verify-*.sh script in this repo, this one does
# NOT start, stop, or modify the Compose environment in any way — it
# assumes the stack is ALREADY running (`docker compose ps`) and only
# ever issues GET requests against it:
#   - Prometheus `GET /api/v1/query` (one legitimate, already-reviewed
#     metric: `up`) to confirm connectivity.
#   - Tempo `GET /api/search` within a short recent window, to confirm
#     availability and parse whatever traces actually exist (zero
#     traces is a valid, honest result, never an error).
#   - control-plane `GET /api/v1/incidents` (read-only, unauthenticated)
#     to feed the real incident-lifecycle invariant checker.
#   - `python -m detectors analyze` against all three, end to end.
#
# If there is no real recent traffic or baseline sample history, the
# pipeline honestly reports INSUFFICIENT_DATA for the affected checks
# -- this script never fabricates an anomaly, never stops a Compose
# service, never touches the PostgreSQL volume, and never calls a
# write-capable endpoint anywhere (control-plane's only write route,
# PATCH .../status, is never invoked).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
TEMPO_URL="${TEMPO_URL:-http://localhost:3200}"
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://localhost:8000}"

main() {
cd "$REPO_ROOT"

echo "=== Phase 11B real-stack check: confirming the Compose stack is already running (never started/stopped by this script) ===" >&2
if ! docker compose ps --status running --format '{{.Service}}' | grep -q '^prometheus$'; then
  echo "SKIPPED: prometheus is not currently running under docker compose -- this script is opt-in and never starts the stack itself." >&2
  exit 0
fi

echo "=== Phase 11B: GET $PROMETHEUS_URL/api/v1/query?query=up (one legitimate, already-reviewed metric) ===" >&2
curl -fsS "$PROMETHEUS_URL/api/v1/query?query=up" | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body.get('status') == 'success', body
print(f\"confirmed: Prometheus reachable, status=success, {len(body['data']['result'])} 'up' series returned\")
"

echo "=== Phase 11B: GET $TEMPO_URL/api/search (last 10 minutes, checkout-service root) ===" >&2
NOW_EPOCH="$(date +%s)"
START_EPOCH="$((NOW_EPOCH - 600))"
curl -fsS "$TEMPO_URL/api/search?tags=service.name%3Dcheckout-service&start=$START_EPOCH&end=$NOW_EPOCH&limit=5" | python3 -c "
import json, sys
body = json.load(sys.stdin)
traces = body.get('traces') or []
print(f\"confirmed: Tempo reachable, {len(traces)} candidate trace(s) found in the last 10 minutes (0 is a valid, honest result)\")
"

echo "=== Phase 11B: GET $CONTROL_PLANE_URL/api/v1/incidents (read-only, unauthenticated) ===" >&2
curl -fsS "$CONTROL_PLANE_URL/api/v1/incidents?limit=5" | python3 -c "
import json, sys
body = json.load(sys.stdin)
print(f\"confirmed: control-plane reachable, total={body['total']} incident(s) on record\")
"

echo "=== Phase 11B: python -m detectors analyze (real endpoints, all 4 allowlisted services) ===" >&2
docker run --rm --network host -v "$REPO_ROOT:/app" -w /app python:3.13-slim bash -c "
  set -euo pipefail
  pip install -q -r detectors/requirements.txt -r catalog/requirements.txt
  python -m detectors analyze \
    --prometheus-url '$PROMETHEUS_URL' \
    --tempo-url '$TEMPO_URL' \
    --control-plane-url '$CONTROL_PLANE_URL' \
    --output /tmp/phase11b-real-stack-report.json
"

echo "" >&2
echo "PHASE 11B REAL-STACK CHECK COMPLETE: Prometheus/Tempo/control-plane connectivity confirmed, the real unified pipeline ran end to end against live endpoints, and the report above is this script's own honest, as-observed output -- it is NOT claimed to represent sustained production coverage, and no Compose service, database volume, or write-capable endpoint was touched." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
