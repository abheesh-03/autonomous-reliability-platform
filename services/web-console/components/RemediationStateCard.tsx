import { formatTimestamp } from "../lib/format";
import type { BackendResult } from "../lib/server/http";
import type { AgentRun } from "../lib/types/agent-run";
import type { RemediationProposal } from "../lib/types/remediation";
import { BackendFailure } from "./BackendFailure";
import { StatusBadgePill } from "./StatusBadge";

// Read-only. No approve/reject, no resume -- those belong to a later
// mutation stage (see docs/architecture/phase-9-web-console.md).
export function RemediationStateCard({
  agentRun,
  proposalResult,
}: {
  agentRun: AgentRun;
  // null when the run never reached propose_remediation at all (no
  // proposal_id to even look up) -- distinct from a lookup that was
  // attempted and failed (proposalResult.ok === false).
  proposalResult: BackendResult<RemediationProposal> | null;
}) {
  if (!agentRun.remediation_proposal_id) {
    return <p className="text-sm text-fg-muted">No remediation proposal exists for this run.</p>;
  }

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
        <dt className="text-fg-muted">Action</dt>
        <dd className="text-fg break-words">{agentRun.remediation_action_type ?? "—"}</dd>
        <dt className="text-fg-muted">Target</dt>
        <dd className="text-fg break-words">{agentRun.remediation_target ?? "—"}</dd>
        <dt className="text-fg-muted">Status</dt>
        <dd>{agentRun.remediation_status ? <StatusBadgePill status={agentRun.remediation_status} /> : "—"}</dd>
      </dl>

      {agentRun.execution_result && (
        <p className="text-sm">
          <strong className="font-medium text-fg">Execution:</strong>{" "}
          <span className="text-fg-muted">
            {agentRun.execution_result.status}
            {agentRun.execution_result.detail ? ` -- ${agentRun.execution_result.detail}` : ""}
          </span>
        </p>
      )}

      <div>
        {proposalResult === null ? null : !proposalResult.ok ? (
          <BackendFailure kind={proposalResult.error.kind} />
        ) : (
          <dl className="grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
            <dt className="text-fg-muted">Reason</dt>
            <dd className="text-fg break-words">{proposalResult.data.reason}</dd>
            <dt className="text-fg-muted">Decided at</dt>
            <dd className="text-fg break-words">{formatTimestamp(proposalResult.data.decided_at)}</dd>
            <dt className="text-fg-muted">Execution started</dt>
            <dd className="text-fg break-words">{formatTimestamp(proposalResult.data.execution_started_at)}</dd>
            <dt className="text-fg-muted">Execution completed</dt>
            <dd className="text-fg break-words">{formatTimestamp(proposalResult.data.execution_completed_at)}</dd>
          </dl>
        )}
      </div>
    </div>
  );
}
