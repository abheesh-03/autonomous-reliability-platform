import { notFound } from "next/navigation";
import Link from "next/link";
import { AgentRunSummary } from "../../../components/AgentRunSummary";
import { BackendFailure } from "../../../components/BackendFailure";
import { CheckpointTimeline } from "../../../components/CheckpointTimeline";
import { InvestigationReportView } from "../../../components/InvestigationReportView";
import { RecoveryVerificationCard } from "../../../components/RecoveryVerificationCard";
import { RemediationStateCard } from "../../../components/RemediationStateCard";
import { SeverityBadge, StatusBadgePill } from "../../../components/StatusBadge";
import { WorkflowProgress } from "../../../components/WorkflowProgress";
import { formatTimestamp } from "../../../lib/format";
import { getAgentRun, getAgentRunHistory } from "../../../lib/server/agent-runtime-client";
import { getRemediationProposal } from "../../../lib/server/control-plane-client";
import type { BackendResult } from "../../../lib/server/http";
import type { RemediationProposal } from "../../../lib/types/remediation";

export default async function AgentRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const agentRunResult = await getAgentRun(runId);

  if (!agentRunResult.ok) {
    if (agentRunResult.error.kind === "not_found" || agentRunResult.error.kind === "validation") {
      notFound();
    }
    return (
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <p>
          <Link href="/">&larr; Dashboard</Link>
        </p>
        <BackendFailure kind={agentRunResult.error.kind} />
      </main>
    );
  }

  const agentRun = agentRunResult.data;

  // Each optional/scoped read is independent: a failure in history or
  // in the remediation-proposal enrichment never hides the durable
  // AgentRun itself, which already loaded successfully above.
  const historyResult = await getAgentRunHistory(runId);
  const proposalResult: BackendResult<RemediationProposal> | null = agentRun.remediation_proposal_id
    ? await getRemediationProposal(agentRun.remediation_proposal_id)
    : null;

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <p>
        <Link href="/">&larr; Dashboard</Link>
      </p>
      <h1 style={{ marginTop: "0.5rem" }}>Agent run</h1>

      {agentRun.status === "waiting_for_approval" && (
        <div
          role="status"
          style={{
            border: "1px solid #5a4a1f",
            background: "#1a140a",
            color: "#f3e2a8",
            borderRadius: 8,
            padding: "1rem",
            marginBottom: "1rem",
          }}
        >
          Waiting for human approval.
          {agentRun.remediation_proposal_id && (
            <>
              {" "}
              Remediation proposal <code>{agentRun.remediation_proposal_id}</code> has not been decided yet.
            </>
          )}
        </div>
      )}

      {agentRun.status === "failed" && (
        <div
          role="alert"
          style={{
            border: "1px solid #5a2a2a",
            background: "#1a0f0f",
            color: "#f3c9c9",
            borderRadius: 8,
            padding: "1rem",
            marginBottom: "1rem",
          }}
        >
          <div>Run failed.</div>
          {agentRun.error_code && <div>error_code: {agentRun.error_code}</div>}
          {agentRun.error_detail && <div>{agentRun.error_detail}</div>}
          <div>{agentRun.resumable ? "This run remains resumable." : "This run is not resumable."}</div>
        </div>
      )}

      <AgentRunSummary agentRun={agentRun} />

      <section style={{ marginTop: "2rem" }}>
        <h2>Workflow progress</h2>
        <WorkflowProgress completedNodes={agentRun.completed_nodes} currentNode={agentRun.current_node} />
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Checkpoint history</h2>
        {!historyResult.ok ? (
          <BackendFailure kind={historyResult.error.kind} />
        ) : (
          <CheckpointTimeline entries={historyResult.data.entries} />
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Incident snapshot</h2>
        {agentRun.incident_snapshot ? (
          <div>
            <p style={{ display: "flex", gap: "0.5rem" }}>
              <SeverityBadge severity={agentRun.incident_snapshot.severity} />
              <StatusBadgePill status={agentRun.incident_snapshot.status} />
            </p>
            <p>
              <Link href={`/incidents/${agentRun.incident_snapshot.id}`}>{agentRun.incident_snapshot.title}</Link>
            </p>
            <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.3rem", fontSize: "0.9rem" }}>
              <dt style={{ color: "#9fb3c8" }}>Source</dt>
              <dd>{agentRun.incident_snapshot.source}</dd>
              <dt style={{ color: "#9fb3c8" }}>First seen</dt>
              <dd>{formatTimestamp(agentRun.incident_snapshot.first_seen_at)}</dd>
            </dl>
          </div>
        ) : (
          <p style={{ color: "#9fb3c8" }}>No incident snapshot captured yet.</p>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Investigation report</h2>
        {agentRun.investigation_report ? (
          <InvestigationReportView report={agentRun.investigation_report} resultQuality={agentRun.result_quality} />
        ) : (
          <p style={{ color: "#9fb3c8" }}>No investigation report yet.</p>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Remediation</h2>
        <RemediationStateCard agentRun={agentRun} proposalResult={proposalResult} />
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Recovery verification</h2>
        {agentRun.recovery_verification ? (
          <RecoveryVerificationCard verification={agentRun.recovery_verification} />
        ) : (
          <p style={{ color: "#9fb3c8" }}>Recovery verification not yet performed.</p>
        )}
      </section>

      {agentRun.validation_notes.length > 0 && (
        <section style={{ marginTop: "2rem" }}>
          <h2>Validation notes</h2>
          <ul style={{ color: "#9fb3c8" }}>
            {agentRun.validation_notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
