import { notFound } from "next/navigation";
import Link from "next/link";
import { AgentRunActions } from "../../../components/AgentRunActions";
import { AgentRunSummary } from "../../../components/AgentRunSummary";
import { BackendFailure } from "../../../components/BackendFailure";
import { CheckpointTimeline } from "../../../components/CheckpointTimeline";
import { InvestigationReportView } from "../../../components/InvestigationReportView";
import { LiveRunPolling } from "../../../components/LiveRunPolling";
import { RecoveryVerificationCard } from "../../../components/RecoveryVerificationCard";
import { RemediationDecisionControl } from "../../../components/RemediationDecisionControl";
import { RemediationStateCard } from "../../../components/RemediationStateCard";
import { SeverityBadge, StatusBadgePill } from "../../../components/StatusBadge";
import { WorkflowProgress } from "../../../components/WorkflowProgress";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { formatTimestamp } from "../../../lib/format";
import { getAgentRun, getAgentRunHistory } from "../../../lib/server/agent-runtime-client";
import { getIncident, getRemediationProposal } from "../../../lib/server/control-plane-client";
import type { BackendResult } from "../../../lib/server/http";
import type { RemediationProposal } from "../../../lib/types/remediation";
import { requireActorOrRedirect, signAssertion } from "../../../lib/server/actor";

export default async function AgentRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const actor = await requireActorOrRedirect();
  const controlPlaneToken = await signAssertion(actor, "control-plane");
  const agentRuntimeToken = await signAssertion(actor, "agent-runtime-service");

  const { runId } = await params;
  const agentRunResult = await getAgentRun(runId, agentRuntimeToken);

  if (!agentRunResult.ok) {
    if (agentRunResult.error.kind === "not_found" || agentRunResult.error.kind === "validation") {
      notFound();
    }
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Link href="/" className="text-sm text-fg-muted hover:text-fg">
          &larr; Dashboard
        </Link>
        <BackendFailure kind={agentRunResult.error.kind} />
      </div>
    );
  }

  const agentRun = agentRunResult.data;

  // Each optional/scoped read is independent: a failure in history or
  // in the remediation-proposal enrichment never hides the durable
  // AgentRun itself, which already loaded successfully above.
  const historyResult = await getAgentRunHistory(runId, agentRuntimeToken);
  const proposalResult: BackendResult<RemediationProposal> | null = agentRun.remediation_proposal_id
    ? await getRemediationProposal(agentRun.remediation_proposal_id, controlPlaneToken)
    : null;
  // A SEPARATE, independent, read-only fetch from the durable
  // incident_snapshot embedded in the AgentRun checkpoint -- that
  // snapshot is frozen at whatever point the graph last captured it,
  // while this is the real, current incident row. Only control-plane's
  // own authoritative state may ever report "resolved"; this console
  // never infers it.
  const liveIncidentResult = await getIncident(agentRun.incident_id, controlPlaneToken);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <LiveRunPolling
        status={agentRun.status}
        incidentStatus={liveIncidentResult.ok ? liveIncidentResult.data.status : null}
      />
      <Link href="/" className="text-sm text-fg-muted hover:text-fg">
        &larr; Dashboard
      </Link>
      <h1 className="text-xl font-semibold text-fg">AI investigation</h1>

      {agentRun.status === "waiting_for_approval" && (
        <div role="status" className="rounded-xl border border-warning-fg/30 bg-warning-soft-bg p-4 text-sm text-warning-fg">
          Waiting for human approval.
          {agentRun.remediation_proposal_id && (
            <>
              {" "}
              Remediation proposal <code className="font-mono text-xs">{agentRun.remediation_proposal_id}</code> has
              not been decided yet.
            </>
          )}
          {agentRun.remediation_proposal_id && proposalResult?.ok && (
            <div className="mt-3">
              <RemediationDecisionControl
                runId={agentRun.run_id}
                proposalId={agentRun.remediation_proposal_id}
                proposalStatus={proposalResult.data.status}
                runResumable={agentRun.resumable}
              />
            </div>
          )}
        </div>
      )}

      {agentRun.status === "failed" && (
        <div role="alert" className="space-y-1 rounded-xl border border-critical-fg/30 bg-critical-soft-bg p-4 text-sm text-critical-fg">
          <div className="font-medium">Run failed.</div>
          {agentRun.error_code && <div>error_code: {agentRun.error_code}</div>}
          {agentRun.error_detail && <div>{agentRun.error_detail}</div>}
          <div>{agentRun.resumable ? "This run remains resumable." : "This run is not resumable."}</div>
        </div>
      )}

      <AgentRunSummary agentRun={agentRun} />

      {agentRun.status !== "waiting_for_approval" && (
        <AgentRunActions runId={agentRun.run_id} currentNode={agentRun.current_node} resumable={agentRun.resumable} />
      )}

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Workflow progress</CardTitle>
          </CardHeader>
          <CardContent>
            <WorkflowProgress completedNodes={agentRun.completed_nodes} currentNode={agentRun.current_node} />
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Checkpoint history</CardTitle>
          </CardHeader>
          <CardContent>
            {!historyResult.ok ? (
              <BackendFailure kind={historyResult.error.kind} />
            ) : (
              <CheckpointTimeline entries={historyResult.data.entries} />
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardContent className="pt-5">
            {/* Deliberately in the SAME container as the status content
                below it (never a separate CardHeader) -- the real
                Playwright acceptance spec locates this live status via
                `getByText("Live incident state").locator("..")`, which
                only reaches this element's own immediate parent. */}
            <CardTitle className="mb-1">Live incident state</CardTitle>
            <p className="mb-3 text-xs text-fg-subtle">
              Read directly from control-plane just now -- distinct from the durable snapshot below, which was
              captured at an earlier point in this run.
            </p>
            {!liveIncidentResult.ok ? (
              <BackendFailure kind={liveIncidentResult.error.kind} />
            ) : (
              <div className="rounded-lg border border-border bg-surface-sunken p-3">
                <p className="flex gap-2">
                  <SeverityBadge severity={liveIncidentResult.data.severity} />
                  <StatusBadgePill status={liveIncidentResult.data.status} />
                </p>
                <dl className="mt-2 grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-1.5 text-sm">
                  <dt className="text-fg-muted">Last seen</dt>
                  <dd className="text-fg break-words">{formatTimestamp(liveIncidentResult.data.last_seen_at)}</dd>
                  <dt className="text-fg-muted">Resolved at</dt>
                  <dd className="text-fg break-words">
                    {liveIncidentResult.data.resolved_at ? formatTimestamp(liveIncidentResult.data.resolved_at) : "Not yet resolved"}
                  </dd>
                </dl>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Incident snapshot (durable, as captured during this run)</CardTitle>
          </CardHeader>
          <CardContent>
            {agentRun.incident_snapshot ? (
              <div>
                <p className="flex gap-2">
                  <SeverityBadge severity={agentRun.incident_snapshot.severity} />
                  <StatusBadgePill status={agentRun.incident_snapshot.status} />
                </p>
                <p className="mt-2">
                  <Link href={`/incidents/${agentRun.incident_snapshot.id}`} className="text-accent-soft-fg hover:underline">
                    {agentRun.incident_snapshot.title}
                  </Link>
                </p>
                <dl className="mt-2 grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-1.5 text-sm">
                  <dt className="text-fg-muted">Source</dt>
                  <dd className="text-fg break-words">{agentRun.incident_snapshot.source}</dd>
                  <dt className="text-fg-muted">First seen</dt>
                  <dd className="text-fg break-words">{formatTimestamp(agentRun.incident_snapshot.first_seen_at)}</dd>
                </dl>
              </div>
            ) : (
              <p className="text-sm text-fg-muted">No incident snapshot captured yet.</p>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Investigation report</CardTitle>
          </CardHeader>
          <CardContent>
            {agentRun.investigation_report ? (
              <InvestigationReportView report={agentRun.investigation_report} resultQuality={agentRun.result_quality} />
            ) : (
              <p className="text-sm text-fg-muted">No investigation report yet.</p>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Remediation</CardTitle>
          </CardHeader>
          <CardContent>
            <RemediationStateCard agentRun={agentRun} proposalResult={proposalResult} />
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Recovery verification</CardTitle>
          </CardHeader>
          <CardContent>
            {agentRun.recovery_verification ? (
              <RecoveryVerificationCard verification={agentRun.recovery_verification} />
            ) : (
              <p className="text-sm text-fg-muted">Recovery verification not yet performed.</p>
            )}
          </CardContent>
        </Card>
      </section>

      {agentRun.validation_notes.length > 0 && (
        <section>
          <Card>
            <CardHeader>
              <CardTitle>Validation notes</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm text-fg-muted">
                {agentRun.validation_notes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  );
}
