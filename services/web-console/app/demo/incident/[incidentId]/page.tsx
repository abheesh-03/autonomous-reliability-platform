import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Card, CardContent } from "../../../../components/ui/card";
import { SeverityBadge, StatusBadgePill } from "../../../../components/StatusBadge";
import { DemoRemediationCard } from "../../../../components/demo/demo-remediation-card";
import { formatTimestamp } from "../../../../lib/format";
import { demoSnapshot } from "../../../../lib/demo/snapshot";

export const metadata = {
  title: "Recorded incident — Reliability Console demo",
};

/**
 * Phase 18: a read-only replay of the live incident-detail page
 * (app/incidents/[incidentId]/page.tsx), against the bundled static
 * snapshot only -- no backend call, no StartInvestigationControl (no
 * pretend action buttons in the demo). Only the snapshot's own real
 * recorded incident id resolves; any other id is a genuine not-found,
 * exactly like the live page's own `notFound()` on an unknown id.
 */
export default async function DemoIncidentPage({ params }: { params: Promise<{ incidentId: string }> }) {
  const { incidentId } = await params;
  const { incident_scenario } = demoSnapshot;
  if (incidentId !== incident_scenario.incident.id) notFound();

  const { incident, events, remediation_proposal, remediation_events, agent_run } = incident_scenario;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/demo" className="text-sm text-fg-muted hover:text-fg">
        &larr; Recorded demo
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

      <p className="text-sm text-fg-muted">
        This incident was investigated once, as part of the recorded run below.{" "}
        <Link
          href={`/demo/investigation/${agent_run.run_id}`}
          className="inline-flex items-center gap-1 font-medium text-accent-soft-fg hover:underline"
        >
          View the recorded investigation <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </p>

      <section>
        <h2 className="mb-3 text-base font-semibold text-fg">Audit timeline</h2>
        {events.length === 0 ? (
          <p className="text-sm text-fg-muted">No audit events recorded.</p>
        ) : (
          <ol className="grid gap-2">
            {events.map((event) => (
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
        <DemoRemediationCard proposal={remediation_proposal} events={remediation_events} runId={agent_run.run_id} />
      </section>
    </div>
  );
}
