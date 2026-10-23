import Link from "next/link";
import { BackendFailure } from "../../components/BackendFailure";
import { SeverityBadge, StatusBadgePill } from "../../components/StatusBadge";
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
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <p>
        <Link href="/">&larr; Dashboard</Link>
      </p>
      <h1 style={{ marginTop: "0.5rem" }}>Incidents</h1>

      <form method="get" style={{ display: "flex", gap: "0.75rem", margin: "1rem 0", flexWrap: "wrap" }}>
        <label>
          Status{" "}
          <select name="status" defaultValue={parsed.status ?? ""}>
            <option value="">(any)</option>
            {INCIDENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Severity{" "}
          <select name="severity" defaultValue={parsed.severity ?? ""}>
            <option value="">(any)</option>
            {INCIDENT_SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {severity}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source{" "}
          <input type="text" name="source" defaultValue={parsed.source ?? ""} placeholder="alertmanager" />
        </label>
        <button type="submit">Filter</button>
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
    </main>
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

  return (
    <>
      <p style={{ color: "#9fb3c8" }}>
        {total} incident{total === 1 ? "" : "s"} total
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
            <th>Severity</th>
            <th>Status</th>
            <th>Title</th>
            <th>Source</th>
            <th>First seen</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={6} style={{ padding: "1rem 0", color: "#9fb3c8" }}>
                No incidents match this filter.
              </td>
            </tr>
          ) : (
            items.map((incident) => (
              <tr key={incident.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td>
                  <SeverityBadge severity={incident.severity} />
                </td>
                <td>
                  <StatusBadgePill status={incident.status} />
                </td>
                <td>
                  <Link href={`/incidents/${incident.id}`}>{incident.title}</Link>
                </td>
                <td>{incident.source}</td>
                <td>{formatTimestamp(incident.first_seen_at)}</td>
                <td>{formatTimestamp(incident.last_seen_at)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <nav style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
        {hasPrev ? (
          <Link href={buildPageHref(rawParams, Math.max(0, offset - limit))}>&larr; Previous</Link>
        ) : (
          <span style={{ color: "#6b7f93" }}>&larr; Previous</span>
        )}
        {hasNext ? (
          <Link href={buildPageHref(rawParams, offset + limit)}>Next &rarr;</Link>
        ) : (
          <span style={{ color: "#6b7f93" }}>Next &rarr;</span>
        )}
      </nav>
    </>
  );
}
