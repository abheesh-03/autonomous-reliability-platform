import Link from "next/link";
import { Siren } from "lucide-react";
import { BackendFailure } from "../../components/BackendFailure";
import { SeverityBadge, StatusBadgePill } from "../../components/StatusBadge";
import { EmptyState } from "../../components/ui/empty-state";
import { Select } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { formatTimestamp } from "../../lib/format";
import { parseIncidentListSearchParams, type RawSearchParams } from "../../lib/incident-query";
import { listIncidents } from "../../lib/server/control-plane-client";
import { INCIDENT_SEVERITIES, INCIDENT_STATUSES } from "../../lib/types/incident";
import { requireActorOrRedirect, signAssertion } from "../../lib/server/actor";

export default async function IncidentsPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  // Phase 14 Gate 9: every protected page re-establishes the real
  // actor on every render -- never assumes a prior page's check still
  // holds (Gate 2: "Do not rely solely on Next.js middleware/proxy
  // redirects... every protected server route must validate the real
  // session and authorization").
  const actor = await requireActorOrRedirect();
  const actorToken = await signAssertion(actor, "control-plane");

  const rawParams = await searchParams;
  const parsed = parseIncidentListSearchParams(rawParams);
  const result = await listIncidents(parsed, actorToken);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-fg">Incidents</h1>
        <p className="mt-1 text-sm text-fg-muted">Every incident this organization has observed.</p>
      </div>

      <form method="get" className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-3">
        <label className="text-sm">
          <span className="mb-1.5 block font-medium text-fg">Status</span>
          <Select name="status" defaultValue={parsed.status ?? ""} className="w-40">
            <option value="">Any</option>
            {INCIDENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-sm">
          <span className="mb-1.5 block font-medium text-fg">Severity</span>
          <Select name="severity" defaultValue={parsed.severity ?? ""} className="w-40">
            <option value="">Any</option>
            {INCIDENT_SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {severity}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-sm">
          <span className="mb-1.5 block font-medium text-fg">Source</span>
          <input
            type="text"
            name="source"
            defaultValue={parsed.source ?? ""}
            placeholder="alertmanager"
            className="h-9 w-48 rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)"
          />
        </label>
        <Button type="submit" variant="secondary">
          Filter
        </Button>
      </form>

      {!result.ok ? (
        <BackendFailure kind={result.error.kind} />
      ) : (
        <IncidentTable
          items={result.data.items}
          total={result.data.total}
          limit={result.data.limit}
          offset={result.data.offset}
          rawParams={rawParams}
        />
      )}
    </div>
  );
}

function buildPageHref(rawParams: RawSearchParams, offset: number): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(rawParams)) {
    if (key === "offset" || value === undefined) continue;
    search.set(key, Array.isArray(value) ? value[0] : value);
  }
  search.set("offset", String(offset));
  return `/incidents?${search.toString()}`;
}

function IncidentTable({
  items,
  total,
  limit,
  offset,
  rawParams,
}: {
  items: Array<{
    id: string;
    title: string;
    source: string;
    severity: string;
    status: string;
    first_seen_at: string;
    last_seen_at: string;
  }>;
  total: number;
  limit: number;
  offset: number;
  rawParams: RawSearchParams;
}) {
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface">
        <EmptyState icon={Siren} title="No incidents match this filter." />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <p className="border-b border-border px-4 py-2.5 text-sm text-fg-muted">
        {total} incident{total === 1 ? "" : "s"} total
      </p>
      <div className="thin-scrollbar overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-fg-subtle">
              <th className="px-4 py-2.5">Severity</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5">Title</th>
              <th className="px-4 py-2.5">Source</th>
              <th className="px-4 py-2.5">First seen</th>
              <th className="px-4 py-2.5">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((incident) => (
              <tr key={incident.id} className="border-b border-border last:border-0 hover:bg-surface-hover">
                <td className="px-4 py-3">
                  <SeverityBadge severity={incident.severity} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadgePill status={incident.status} />
                </td>
                <td className="px-4 py-3">
                  <Link href={`/incidents/${incident.id}`} className="font-medium text-fg hover:underline">
                    {incident.title}
                  </Link>
                </td>
                <td className="px-4 py-3 text-fg-muted">{incident.source}</td>
                <td className="px-4 py-3 text-fg-muted">{formatTimestamp(incident.first_seen_at)}</td>
                <td className="px-4 py-3 text-fg-muted">{formatTimestamp(incident.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <nav className="flex items-center justify-between gap-4 border-t border-border px-4 py-3">
        {hasPrev ? (
          <Link
            href={buildPageHref(rawParams, Math.max(0, offset - limit))}
            className="text-sm font-medium text-accent-soft-fg hover:underline"
          >
            ← Previous
          </Link>
        ) : (
          <span className="text-sm text-fg-subtle">← Previous</span>
        )}
        {hasNext ? (
          <Link
            href={buildPageHref(rawParams, offset + limit)}
            className="text-sm font-medium text-accent-soft-fg hover:underline"
          >
            Next →
          </Link>
        ) : (
          <span className="text-sm text-fg-subtle">Next →</span>
        )}
      </nav>
    </div>
  );
}
