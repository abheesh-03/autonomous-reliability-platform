"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Bounded, read-only live polling -- no WebSockets/SSE/client-state
// library. Every refresh is a plain router.refresh(), which re-runs
// the owning Server Component's own GETs; this component itself never
// calls fetch, never POSTs, and never mutates anything. Uses exactly
// ONE timer at a time (setInterval), always cleared on unmount or
// whenever the polling cadence itself changes.
//
// Cadence (all three policed independently of each other -- a run can
// be "running" while its incident is anything, but "completed"/"failed"
// only keeps polling if the LIVE incident (never the durable snapshot)
// is still "remediating", since monitoring -- not this console -- is
// the only authority that may ever report "resolved"):
//   - running: ~2.5s (fast -- a human is actively watching progress)
//   - waiting_for_approval: ~5s (slower -- waiting on a human decision
//     elsewhere, or on tool-gateway/recovery verification after resume)
//   - completed/failed + incident still remediating: ~5s (waiting for
//     Alertmanager's own natural resolution, never inferred here)
//   - completed/failed + incident resolved/anything else: no polling
export function pollIntervalMs(status: string, incidentStatus: string | null): number | null {
  if (status === "running") return 2500;
  if (status === "waiting_for_approval") return 5000;
  if ((status === "completed" || status === "failed") && incidentStatus === "remediating") return 5000;
  return null;
}

export function LiveRunPolling({
  status,
  incidentStatus,
}: {
  status: string;
  incidentStatus: string | null;
}) {
  const router = useRouter();

  useEffect(() => {
    const intervalMs = pollIntervalMs(status, incidentStatus);
    if (intervalMs === null) return;
    const timer = setInterval(() => {
      router.refresh();
    }, intervalMs);
    return () => clearInterval(timer);
  }, [status, incidentStatus, router]);

  return null;
}
