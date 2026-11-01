import { notFound } from "next/navigation";
import Link from "next/link";
import { InvestigationReportView } from "../../../../components/InvestigationReportView";
import { RecoveryVerificationCard } from "../../../../components/RecoveryVerificationCard";
import { WorkflowProgress } from "../../../../components/WorkflowProgress";
import { SeverityBadge, StatusBadgePill } from "../../../../components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../../components/ui/card";
import { DemoRemediationCard } from "../../../../components/demo/demo-remediation-card";
import { formatTimestamp } from "../../../../lib/format";
import { demoSnapshot } from "../../../../lib/demo/snapshot";

export const metadata = {
  title: "Recorded investigation — Reliability Console demo",
};

/**
 * Phase 18: a read-only replay of the live agent-run workspace
 * (app/agent-runs/[runId]/page.tsx), against the bundled static
 * snapshot only. Deliberately omits what the live page has that a
 * recorded, completed run cannot honestly show: `LiveRunPolling` (no
 * polling here -- see Section 3), `AgentRunActions`/
 * `RemediationDecisionControl` (no Run/Approve/Reject/Continue
 * buttons -- this run is already finished), and the "Live incident
 * state" panel (there is no "just now" to read here). Only the
 * snapshot's own real recorded run id resolves; any other id is a
 * genuine not-found.
 */
export default async function DemoInvestigationPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const { incident_scenario } = demoSnapshot;
  const { agent_run, incident, remediation_proposal, remediation_events } = incident_scenario;
  if (runId !== agent_run.run_id) notFound();

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/demo" className="text-sm text-fg-muted hover:text-fg">
        &larr; Recorded demo
      </Link>
      <h1 className="text-xl font-semibold text-fg">AI investigation</h1>

      <section>
        <p className="flex items-center gap-2 text-sm">
          <StatusBadgePill status={agent_run.status} />
          <span className="text-fg-muted">current node: {agent_run.current_node}</span>
          <span className="text-fg-muted">recorded run — not resumable</span>
        </p>
        <dl className="mt-3 grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
          <dt className="text-fg-muted">Run ID</dt>
          <dd className="font-mono text-xs text-fg break-all">{agent_run.run_id}</dd>
          <dt className="text-fg-muted">Incident</dt>
          <dd>
            <Link href={`/demo/incident/${incident.id}`} className="text-accent-soft-fg hover:underline">
              {incident.title}
            </Link>
          </dd>
          <dt className="text-fg-muted">Started</dt>
          <dd className="text-fg break-words">{formatTimestamp(agent_run.started_at)}</dd>
          <dt className="text-fg-muted">Completed</dt>
          <dd className="text-fg break-words">{formatTimestamp(agent_run.completed_at)}</dd>
        </dl>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Workflow progress</CardTitle>
          </CardHeader>
          <CardContent>
            <WorkflowProgress completedNodes={agent_run.completed_nodes} currentNode={agent_run.current_node} />
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Recorded incident — final state at capture</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="flex gap-2">
              <SeverityBadge severity={incident.severity} />
              <StatusBadgePill status={incident.status} />
            </p>
            <p className="mt-2">
              <Link href={`/demo/incident/${incident.id}`} className="text-accent-soft-fg hover:underline">
                {incident.title}
              </Link>
            </p>
            <dl className="mt-2 grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-1.5 text-sm">
              <dt className="text-fg-muted">Source</dt>
              <dd className="text-fg break-words">{incident.source}</dd>
              <dt className="text-fg-muted">First seen</dt>
              <dd className="text-fg break-words">{formatTimestamp(incident.first_seen_at)}</dd>
            </dl>
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Investigation report</CardTitle>
          </CardHeader>
          <CardContent>
            <InvestigationReportView report={agent_run.investigation_report} resultQuality={agent_run.result_quality} />
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Remediation (recorded approval and execution)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
              <dt className="text-fg-muted">Action</dt>
              <dd className="text-fg break-words">{agent_run.remediation_action_type}</dd>
              <dt className="text-fg-muted">Target</dt>
              <dd className="text-fg break-words">{agent_run.remediation_target}</dd>
              <dt className="text-fg-muted">Status</dt>
              <dd>
                <StatusBadgePill status={agent_run.remediation_status} />
              </dd>
            </dl>
            <p className="text-sm">
              <strong className="font-medium text-fg">Execution:</strong>{" "}
              <span className="text-fg-muted">
                {agent_run.execution_result.status}
                {agent_run.execution_result.detail ? ` -- ${agent_run.execution_result.detail}` : ""}
              </span>
            </p>
          </CardContent>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-base font-semibold text-fg">Recorded approval &amp; remediation history</h2>
        <DemoRemediationCard proposal={remediation_proposal} events={remediation_events} runId={agent_run.run_id} />
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Recovery verification</CardTitle>
          </CardHeader>
          <CardContent>
            <RecoveryVerificationCard verification={agent_run.recovery_verification} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
