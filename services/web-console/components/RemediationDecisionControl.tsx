"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

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
      <div>
        <label htmlFor="decision-comment" style={{ display: "block", marginBottom: "0.3rem" }}>
          Comment (optional)
        </label>
        <textarea
          id="decision-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          maxLength={1000}
          rows={2}
          style={{ width: "100%", marginBottom: "0.5rem" }}
        />
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button onClick={() => handleDecision("approve")} disabled={pending}>
            {pending ? "Working…" : "Approve"}
          </button>
          <button onClick={() => handleDecision("reject")} disabled={pending}>
            {pending ? "Working…" : "Reject"}
          </button>
        </div>
        {error && (
          <p role="alert" style={{ color: "#f3c9c9", marginTop: "0.4rem" }}>
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
      <div>
        <button onClick={handleContinue} disabled={pending}>
          {pending ? "Working…" : "Continue workflow"}
        </button>
        {error && (
          <p role="alert" style={{ color: "#f3c9c9", marginTop: "0.4rem" }}>
            {error}
          </p>
        )}
      </div>
    );
  }

  return null;
}
