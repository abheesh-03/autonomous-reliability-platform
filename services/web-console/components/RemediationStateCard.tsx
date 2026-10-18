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
    return <p style={{ color: "#9fb3c8" }}>No remediation proposal exists for this run.</p>;
  }

  return (
    <div>
      <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.4rem" }}>
        <dt style={{ color: "#9fb3c8" }}>Action</dt>
        <dd>{agentRun.remediation_action_type ?? "—"}</dd>
        <dt style={{ color: "#9fb3c8" }}>Target</dt>
        <dd>{agentRun.remediation_target ?? "—"}</dd>
        <dt style={{ color: "#9fb3c8" }}>Status</dt>
        <dd>{agentRun.remediation_status ? <StatusBadgePill status={agentRun.remediation_status} /> : "—"}</dd>
      </dl>

      {agentRun.execution_result && (
        <p style={{ marginTop: "0.5rem" }}>
          <strong>Execution:</strong> {agentRun.execution_result.status}
          {agentRun.execution_result.detail ? ` -- ${agentRun.execution_result.detail}` : ""}
        </p>
      )}

      <div style={{ marginTop: "0.75rem" }}>
        {proposalResult === null ? null : !proposalResult.ok ? (
          <BackendFailure kind={proposalResult.error.kind} />
        ) : (
          <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.3rem", fontSize: "0.9rem" }}>
            <dt style={{ color: "#9fb3c8" }}>Reason</dt>
            <dd>{proposalResult.data.reason}</dd>
            <dt style={{ color: "#9fb3c8" }}>Decided at</dt>
            <dd>{formatTimestamp(proposalResult.data.decided_at)}</dd>
            <dt style={{ color: "#9fb3c8" }}>Execution started</dt>
            <dd>{formatTimestamp(proposalResult.data.execution_started_at)}</dd>
            <dt style={{ color: "#9fb3c8" }}>Execution completed</dt>
            <dd>{formatTimestamp(proposalResult.data.execution_completed_at)}</dd>
          </dl>
        )}
      </div>
    </div>
  );
}
