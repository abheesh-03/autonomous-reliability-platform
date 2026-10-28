"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";
import { Label } from "./ui/input";

// Shown ONLY while the AgentRun is genuinely waiting_for_approval.
// Receives only safe, non-secret values -- never an approver token,
// never a backend URL. Approve/Reject and "Continue workflow" are
// deliberately TWO SEPARATE requests to two separate routes: this
// component never calls resume as a side effect of a decision, and
// the decision route never calls resume itself (see
// docs/architecture/phase-9-web-console.md). On ANY outcome this
// always reconciles via router.refresh() and never retries a mutation
// automatically.
export function RemediationDecisionControl({
  runId,
  proposalId,
  proposalStatus,
  runResumable,
}: {
  runId: string;
  proposalId: string;
  proposalStatus: string;
  runResumable: boolean;
}) {
  const router = useRouter();
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function safeMessage(response: Response): Promise<string> {
    const body: unknown = await response.json().catch(() => null);
    return body && typeof body === "object" && "message" in body && typeof (body as { message: unknown }).message === "string"
      ? (body as { message: string }).message
      : "Could not complete this action.";
  }

  async function handleDecision(decision: "approve" | "reject") {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/remediation-proposals/${proposalId}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, comment: comment.trim().length > 0 ? comment.trim() : undefined }),
      });
      if (!response.ok) {
        setError(await safeMessage(response));
      }
    } catch {
      setError("Could not reach the server. Refreshing to show the real current state.");
    } finally {
      setPending(false);
      router.refresh();
    }
  }

  async function handleContinue() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/agent-runs/${runId}/resume`, { method: "POST" });
      if (!response.ok) {
        setError(await safeMessage(response));
      }
    } catch {
      setError("Could not reach the server. Refreshing to show the real current state.");
    } finally {
      setPending(false);
      router.refresh();
    }
  }

  if (proposalStatus === "pending_approval") {
    return (
      <div className="space-y-2">
        <div>
          <Label htmlFor="decision-comment">Comment (optional)</Label>
          <textarea
            id="decision-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)"
          />
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => handleDecision("approve")} disabled={pending} loading={pending}>
            Approve
          </Button>
          <Button variant="destructive" onClick={() => handleDecision("reject")} disabled={pending} loading={pending}>
            Reject
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-critical-fg">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (runResumable) {
    // The proposal has already been decided (approved or rejected) but
    // the real durable AgentRun has not yet been resumed past its
    // interrupt -- a separate, explicit action, never triggered
    // automatically by the decision above.
    return (
      <div className="space-y-2">
        <Button onClick={handleContinue} disabled={pending} loading={pending}>
          Continue workflow
        </Button>
        {error && (
          <p role="alert" className="text-sm text-critical-fg">
            {error}
          </p>
        )}
      </div>
    );
  }

  return null;
}
