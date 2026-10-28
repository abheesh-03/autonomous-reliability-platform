"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";

// Receives only safe, non-secret values -- never a token, never a
// backend URL. On ANY outcome (success, safe failure, or an ambiguous
// network/timeout error) this always reconciles via router.refresh(),
// which re-runs the owning Server Component's own data fetching
// against the real durable state -- this is the reconciliation
// mechanism the durability model requires; this component never
// retries the mutation itself.
export function AgentRunActions({
  runId,
  currentNode,
  resumable,
}: {
  runId: string;
  currentNode: string;
  resumable: boolean;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!resumable) return null;

  const label = currentNode === "start" ? "Run investigation" : "Resume run";

  async function handleClick() {
    if (pending) return; // UX-only guard -- never a substitute for a real idempotency key.
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/agent-runs/${runId}/resume`, { method: "POST" });
      if (!response.ok) {
        const body: unknown = await response.json().catch(() => null);
        const message =
          body && typeof body === "object" && "message" in body && typeof (body as { message: unknown }).message === "string"
            ? (body as { message: string }).message
            : "Could not continue this run.";
        setError(message);
      }
    } catch {
      setError("Could not reach the server. Refreshing to show the real current state.");
    } finally {
      setPending(false);
      router.refresh();
    }
  }

  return (
    <div className="space-y-2">
      <Button onClick={handleClick} disabled={pending} loading={pending}>
        {label}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-critical-fg">
          {error}
        </p>
      )}
    </div>
  );
}
