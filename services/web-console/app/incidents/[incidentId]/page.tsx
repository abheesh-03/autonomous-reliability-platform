import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { BackendFailure } from "../../../components/BackendFailure";
import { StartInvestigationControl } from "../../../components/StartInvestigationControl";
import { SeverityBadge, StatusBadgePill } from "../../../components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { formatTimestamp } from "../../../lib/format";
import { fail, type BackendResult } from "../../../lib/server/http";
import {
  getAllIncidentEvents,
  getAllIncidentRemediationProposals,
  getAllRemediationProposalEvents,
  getIncident,
} from "../../../lib/server/control-plane-client";
import type { RemediationEvent, RemediationProposal } from "../../../lib/types/remediation";
import { requireActorOrRedirect, signAssertion } from "../../../lib/server/actor";

export default async function IncidentDetailPage({
  params,
}: {
  params: Promise<{ incidentId: string }>;
}) {
  const actor = await requireActorOrRedirect();
  const actorToken = await signAssertion(actor, "control-plane");

  const { incidentId } = await params;
  const incidentResult = await getIncident(incidentId, actorToken);

  if (!incidentResult.ok) {
    if (incidentResult.error.kind === "not_found" || incidentResult.error.kind === "validation") {
      notFound();
    }
    return (
      <div className="space-y-4">
        <Link href="/incidents" className="text-sm text-fg-muted hover:text-fg">
          &larr; Incidents
        </Link>
        <BackendFailure kind={incidentResult.error.kind} />
      </div>
    );
  }

  const incident = incidentResult.data;

  const [eventsResult, proposalsResult] = await Promise.all([
    getAllIncidentEvents(incidentId, actorToken),
    getAllIncidentRemediationProposals(incidentId, actorToken),
  ]);

  // Each proposal's own event history is fetched independently -- a
  // failure fetching one proposal's events never hides the others, the
  // incident's own timeline above it, or any OTHER proposal's own
  // valid events. The full BackendResult is kept (never collapsed to
  // `[]` on failure) so "the backend failed" stays visibly distinct
  // from "this proposal genuinely has no events" -- see
  // RemediationProposalCard below.
  const proposalEventsByProposalId = new Map<string, BackendResult<RemediationEvent[]>>();
  if (proposalsResult.ok) {
    await Promise.all(
      proposalsResult.data.map(async (proposal) => {
        const eventsForProposal = await getAllRemediationProposalEvents(proposal.id, actorToken);
        proposalEventsByProposalId.set(proposal.id, eventsForProposal);
      }),
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/incidents" className="text-sm text-fg-muted hover:text-fg">
        &larr; Incidents
      </Link>

      <div>
        <h1 className="text-xl font-semibold text-fg">{incident.title}</h1>
        <p className="mt-2 flex gap-2">
          <SeverityBadge severity={incident.severity} />
          <StatusBadgePill status={incident.status} />
        </p>
      </div>

      <Card>
        <CardContent className="pt-5">
          <dl className="grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2.5 text-sm">
            <dt className="text-fg-muted">Source</dt>
            <dd className="text-fg break-words">{incident.source}</dd>
            <dt className="text-fg-muted">Description</dt>
            <dd className="text-fg break-words">{incident.description ?? "—"}</dd>
            <dt className="text-fg-muted">First seen</dt>
            <dd className="text-fg break-words">{formatTimestamp(incident.first_seen_at)}</dd>
            <dt className="text-fg-muted">Last seen</dt>
            <dd className="text-fg break-words">{formatTimestamp(incident.last_seen_at)}</dd>
            <dt className="text-fg-muted">Resolved at</dt>
            <dd className="text-fg break-words">{formatTimestamp(incident.resolved_at)}</dd>
            <dt className="text-fg-muted">Incident ID</dt>
            <dd className="font-mono text-xs text-fg-subtle break-all">{incident.id}</dd>
          </dl>
        </CardContent>
      </Card>

      <div>
        {incident.status === "open" || incident.status === "acknowledged" || incident.status === "investigating" ? (
          <StartInvestigationControl incidentId={incident.id} incidentStatus={incident.status} />
        ) : (
          <p className="text-sm text-fg-muted">
            Investigation cannot be started while the incident is {incident.status}.
          </p>
        )}
      </div>

      <section>
        <h2 className="mb-3 text-base font-semibold text-fg">Audit timeline</h2>
        {!eventsResult.ok ? (
          <BackendFailure kind={eventsResult.error.kind} />
        ) : eventsResult.data.length === 0 ? (
          <p className="text-sm text-fg-muted">No audit events recorded.</p>
        ) : (
          <ol className="grid gap-2">
            {eventsResult.data.map((event) => (
              <li key={event.id} className="rounded-lg border border-border bg-surface p-3 text-sm">
                <div>
                  <strong className="font-medium text-fg">{event.event_type}</strong>{" "}
                  <span className="text-fg-muted">by {event.actor_type}</span>
                </div>
                <div className="text-fg-muted">
                  {event.previous_status ?? "(none)"} &rarr; {event.new_status}
                </div>
                <div className="text-xs text-fg-subtle">{formatTimestamp(event.occurred_at)}</div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-base font-semibold text-fg">Remediation history</h2>
        {!proposalsResult.ok ? (
          <BackendFailure kind={proposalsResult.error.kind} />
        ) : proposalsResult.data.length === 0 ? (
          <p className="text-sm text-fg-muted">No remediation proposal exists for this incident.</p>
        ) : (
          <div className="space-y-3">
            {proposalsResult.data.map((proposal) => (
              <RemediationProposalCard
                key={proposal.id}
                proposal={proposal}
                eventsResult={
                  proposalEventsByProposalId.get(proposal.id) ??
                  // Defensive only -- every proposal in proposalsResult.data
                  // always gets an entry set above; this fail-closed
                  // default is never reached in practice, but never
                  // silently renders an empty history if it somehow were.
                  fail("malformed", "proposal event history was never fetched")
                }
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function RemediationProposalCard({
  proposal,
  eventsResult,
}: {
  proposal: RemediationProposal;
  eventsResult: BackendResult<RemediationEvent[]>;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div>
          <CardTitle className="text-sm">
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
          href={`/agent-runs/${proposal.agent_run_id}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-accent-soft-fg hover:underline"
        >
          View agent run <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>

        <div>
          {!eventsResult.ok ? (
            <BackendFailure kind={eventsResult.error.kind} />
          ) : eventsResult.data.length === 0 ? (
            <p className="text-xs text-fg-subtle">No remediation events recorded.</p>
          ) : (
            <ol className="grid gap-1">
              {eventsResult.data.map((event) => (
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
