#!/usr/bin/env bash
# Phase 17A item 6: the retention scheduler's own run loop -- sleeps
# for TELEMETRY_RETENTION_INTERVAL_HOURS between invocations of
# scripts/prune-telemetry-samples.py, and lets a real failure (any
# non-zero exit) surface in `docker compose logs retention-scheduler`
# with a FAIL line rather than retrying silently forever or exiting
# the container (which `restart: unless-stopped` would otherwise spin
# on). Observable failure path: if the script fails, this loop logs
# it, waits the SAME interval, and tries again on the next tick --
# never crash-loops the container, never silently stops reporting.
set -uo pipefail

interval_hours="${TELEMETRY_RETENTION_INTERVAL_HOURS:-24}"

# CORRECTION ROUND: previously unvalidated -- a non-numeric value
# would make the `$(( ))` below error out with an unset
# interval_seconds and a confusing `sleep` failure; a `0` or negative
# value would either loop with no sleep at all (hammering the
# database every tick) or `sleep` would reject a negative argument.
# Belt-and-suspenders alongside deploy/scripts/preflight.sh's own
# identical deploy-time bound check on this same variable.
case "$interval_hours" in
  ''|*[!0-9]*)
    echo "[retention-scheduler] FAIL: TELEMETRY_RETENTION_INTERVAL_HOURS=${interval_hours@Q} is not a positive integer" >&2
    exit 1
    ;;
esac
if [ "$interval_hours" -lt 1 ] || [ "$interval_hours" -gt 8760 ]; then
  echo "[retention-scheduler] FAIL: TELEMETRY_RETENTION_INTERVAL_HOURS=$interval_hours is out of the required bounds [1, 8760]" >&2
  exit 1
fi
interval_seconds=$((interval_hours * 3600))

echo "[retention-scheduler] starting -- interval=${interval_hours}h dry_run=${TELEMETRY_RETENTION_DRY_RUN:-true} retention_days=${TELEMETRY_RETENTION_DAYS:-30}"

while true; do
  run_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "${TELEMETRY_RETENTION_DRY_RUN:-true}" = "false" ]; then
    python3 ./prune-telemetry-samples.py --execute
  else
    python3 ./prune-telemetry-samples.py
  fi
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[retention-scheduler] FAIL: run started ${run_started} exited ${status} -- will retry in ${interval_hours}h"
  else
    echo "[retention-scheduler] ok: run started ${run_started} completed"
  fi
  sleep "$interval_seconds"
done
