"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { IncidentStatus } from "../lib/types/incident";
import { Button } from "./ui/button";

// The ONLY Client Component in Stage 4. Receives only safe, non-secret
// values (an incident id and its current status) -- NEVER the
// lifecycle token, which exists only server-side in
// lib/server/control-plane-client.ts and the BFF Route Handler this
// component calls. On success, the browser receives the durable
// run_id and navigates with it BEFORE any graph execution has
// occurred (Stage 4's core invariant) -- this component never calls
// anything resembling /resume, and never polls afterward.
export function StartInvestigationControl({
  incidentId,
  incidentStatus,
}: {
  incidentId: string;
  incidentStatus: IncidentStatus;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRecoveryVariant = incidentStatus === "investigating";

  async function handleClick() {
    if (pending) return; // UX-only guard -- never a substitute for a real idempotency key.
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/incidents/${incidentId}/investigations`, {
        method: "POST",
      });
      const body: unknown = await response.json().catch(() => null);
      const runId =
        response.ok && body && typeof body === "object" && "run_id" in body
          ? (body as { run_id: unknown }).run_id
          : null;
      if (!response.ok || typeof runId !== "string") {
        const message =
          body && typeof body === "object" && "message" in body && typeof (body as { message: unknown }).message === "string"
            ? (body as { message: string }).message
            : "Could not start an investigation.";
        setError(message);
        setPending(false);
        return;
      }
      router.push(`/agent-runs/${runId}`);
    } catch {
      setError("Could not reach the server.");
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button onClick={handleClick} disabled={pending} loading={pending}>
        {isRecoveryVariant ? "Create investigation run" : "Start AI investigation"}
      </Button>
      {isRecoveryVariant && (
        <p className="text-sm text-fg-muted">
          This incident is already investigating. This console cannot list existing agent runs for an
          incident, so this action may create an additional run rather than resuming one that already
          exists.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-critical-fg">
          {error}
        </p>
      )}
    </div>
  );
}
