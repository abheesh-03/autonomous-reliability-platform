import { notFound } from "next/navigation";
import Link from "next/link";
import { BackendFailure } from "../../../components/BackendFailure";
import { SeverityBadge, StatusBadgePill } from "../../../components/StatusBadge";
import { formatTimestamp } from "../../../lib/format";
import { fail, type BackendResult } from "../../../lib/server/http";
import {
  getAllIncidentEvents,
  getAllIncidentRemediationProposals,
  getAllRemediationProposalEvents,
  getIncident,
} from "../../../lib/server/control-plane-client";
import type { RemediationEvent, RemediationProposal } from "../../../lib/types/remediation";

export default async function IncidentDetailPage({
  params,
}: {
  params: Promise<{ incidentId: string }>;
}) {
  const { incidentId } = await params;
  const incidentResult = await getIncident(incidentId);

  if (!incidentResult.ok) {
    if (incidentResult.error.kind === "not_found" || incidentResult.error.kind === "validation") {
      notFound();
    }
    return (
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <p>
          <Link href="/incidents">&larr; Incidents</Link>
        </p>
        <BackendFailure kind={incidentResult.error.kind} />
      </main>
    );
  }

  const incident = incidentResult.data;

  const [eventsResult, proposalsResult] = await Promise.all([
    getAllIncidentEvents(incidentId),
    getAllIncidentRemediationProposals(incidentId),
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
        const eventsForProposal = await getAllRemediationProposalEvents(proposal.id);
        proposalEventsByProposalId.set(proposal.id, eventsForProposal);
      }),
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <p>
        <Link href="/incidents">&larr; Incidents</Link>
      </p>

      <h1 style={{ marginTop: "0.5rem" }}>{incident.title}</h1>
      <p style={{ display: "flex", gap: "0.5rem" }}>
        <SeverityBadge severity={incident.severity} />
        <StatusBadgePill status={incident.status} />
      </p>

      <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.4rem" }}>
        <dt style={{ color: "#9fb3c8" }}>Source</dt>
        <dd>{incident.source}</dd>
        <dt style={{ color: "#9fb3c8" }}>Description</dt>
        <dd>{incident.description ?? "—"}</dd>
        <dt style={{ color: "#9fb3c8" }}>First seen</dt>
        <dd>{formatTimestamp(incident.first_seen_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Last seen</dt>
        <dd>{formatTimestamp(incident.last_seen_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Resolved at</dt>
        <dd>{formatTimestamp(incident.resolved_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Incident ID</dt>
        <dd style={{ color: "#6b7f93", fontSize: "0.85rem" }}>{incident.id}</dd>
      </dl>

      <section style={{ marginTop: "2rem" }}>
        <h2>Audit timeline</h2>
        {!eventsResult.ok ? (
          <BackendFailure kind={eventsResult.error.kind} />
        ) : eventsResult.data.length === 0 ? (
          <p style={{ color: "#9fb3c8" }}>No audit events recorded.</p>
        ) : (
          <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
            {eventsResult.data.map((event) => (
              <li
                key={event.id}
                style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.75rem" }}
              >
                <div>
                  <strong>{event.event_type}</strong>{" "}
                  <span style={{ color: "#9fb3c8" }}>by {event.actor_type}</span>
                </div>
                <div style={{ color: "#9fb3c8", fontSize: "0.9rem" }}>
                  {event.previous_status ?? "(none)"} &rarr; {event.new_status}
                </div>
                <div style={{ color: "#6b7f93", fontSize: "0.85rem" }}>
                  {formatTimestamp(event.occurred_at)}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Remediation history</h2>
        {!proposalsResult.ok ? (
          <BackendFailure kind={proposalsResult.error.kind} />
        ) : proposalsResult.data.length === 0 ? (
          <p style={{ color: "#9fb3c8" }}>No remediation proposal exists for this incident.</p>
        ) : (
          proposalsResult.data.map((proposal) => (
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
          ))
        )}
      </section>
    </main>
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
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "1rem", marginBottom: "1rem" }}>
      <div>
        <strong>{proposal.action_type}</strong>{" "}
        <span style={{ color: "#9fb3c8" }}>on {proposal.target}</span>
        <span style={{ marginLeft: "0.5rem" }}>
          <StatusBadgePill status={proposal.status} />
        </span>
      </div>
      <p style={{ color: "#9fb3c8" }}>{proposal.reason}</p>
      <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.3rem", fontSize: "0.9rem" }}>
        <dt style={{ color: "#9fb3c8" }}>Proposed at</dt>
        <dd>{formatTimestamp(proposal.proposed_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Decided at</dt>
        <dd>{formatTimestamp(proposal.decided_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Execution started</dt>
        <dd>{formatTimestamp(proposal.execution_started_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Execution completed</dt>
        <dd>{formatTimestamp(proposal.execution_completed_at)}</dd>
      </dl>

      <div style={{ marginTop: "0.75rem" }}>
        {!eventsResult.ok ? (
          <BackendFailure kind={eventsResult.error.kind} />
        ) : eventsResult.data.length === 0 ? (
          <p style={{ color: "#9fb3c8", fontSize: "0.85rem" }}>No remediation events recorded.</p>
        ) : (
          <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.4rem" }}>
            {eventsResult.data.map((event) => (
              <li key={event.id} style={{ fontSize: "0.85rem", color: "#9fb3c8" }}>
                {formatTimestamp(event.occurred_at)} -- {event.event_type} ({event.actor_type})
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
