import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { StatusBadgePill } from "../StatusBadge";
import { formatTimestamp } from "../../lib/format";
import type { DemoRemediationProposal, DemoRemediationEvent } from "../../lib/demo/types";

/**
 * Phase 18: a read-only rendering of a recorded remediation proposal
 * and its event history, styled identically to the live
 * `RemediationProposalCard` (app/incidents/[incidentId]/page.tsx) --
 * reused here as a dedicated component, against the narrow
 * `DemoRemediationProposal`/`DemoRemediationEvent` allowlist types
 * (lib/demo/types.ts) rather than the live `BackendResult`-wrapped
 * contract, since this data is always present and static, never
 * fetched. Its one navigation link stays within /demo (the
 * investigation workspace), never the live /agent-runs/* route.
 */
export function DemoRemediationCard({
  proposal,
  events,
  runId,
}: {
  proposal: DemoRemediationProposal;
  events: DemoRemediationEvent[];
  runId: string;
}) {
  return (
    <Card>
      <CardHeader className="flex-wrap pb-2">
        <div className="min-w-0 flex-1 basis-48">
          <CardTitle className="text-sm wrap-anywhere">
            {proposal.action_type} <span className="font-normal text-fg-muted">on {proposal.target}</span>
          </CardTitle>
        </div>
        <StatusBadgePill status={proposal.status} />
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-fg-muted">{proposal.reason}</p>
        <dl className="grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
          <dt className="text-fg-muted">Proposed at</dt>
          <dd className="text-fg break-words">{formatTimestamp(proposal.proposed_at)}</dd>
          <dt className="text-fg-muted">Decided at</dt>
          <dd className="text-fg break-words">{formatTimestamp(proposal.decided_at)}</dd>
          <dt className="text-fg-muted">Execution started</dt>
          <dd className="text-fg break-words">{formatTimestamp(proposal.execution_started_at)}</dd>
          <dt className="text-fg-muted">Execution completed</dt>
          <dd className="text-fg break-words">{formatTimestamp(proposal.execution_completed_at)}</dd>
        </dl>

        <Link
          href={`/demo/investigation/${runId}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-accent-soft-fg hover:underline"
        >
          View recorded investigation <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>

        <div>
          {events.length === 0 ? (
            <p className="text-xs text-fg-subtle">No remediation events recorded.</p>
          ) : (
            <ol className="grid gap-1">
              {events.map((event) => (
                <li key={event.id} className="text-xs text-fg-subtle">
                  {formatTimestamp(event.occurred_at)} -- {event.event_type} ({event.actor_type})
                </li>
              ))}
            </ol>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
