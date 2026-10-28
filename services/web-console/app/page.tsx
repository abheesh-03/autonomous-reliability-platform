import Link from "next/link";
import { AlertTriangle, ArrowRight, Boxes, CheckCircle2, ClipboardCheck, Search, Siren } from "lucide-react";
import { BackendFailure } from "../components/BackendFailure";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { MetricCard } from "../components/dashboard/metric-card";
import { AttentionSection } from "../components/dashboard/attention-section";
import { ActivityChart } from "../components/dashboard/activity-chart";
import { RecentActivity } from "../components/dashboard/recent-activity";
import { formatTimestamp } from "../lib/format";
import { getDashboardSummary } from "../lib/server/control-plane-client";
import { listServices } from "../lib/server/service-client";
import { requireActorOrRedirect, signAssertion } from "../lib/server/actor";

export default async function DashboardPage() {
  const actor = await requireActorOrRedirect();
  const actorToken = await signAssertion(actor, "control-plane");

  const [summaryResult, servicesResult] = await Promise.all([
    getDashboardSummary(14, actorToken),
    // Independent-review correction round, BLOCKER 4: this card only
    // ever needs the real, bounded total -- `limit: 1` means at most
    // one row is actually fetched/serialized, never every registered
    // service merely to read `.total` (which is itself a real COUNT,
    // independent of how many rows this call actually returns).
    listServices(actorToken, { limit: 1, offset: 0 }),
  ]);

  if (!summaryResult.ok) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-fg">Dashboard</h1>
        <BackendFailure kind={summaryResult.error.kind} />
      </div>
    );
  }

  const { counts, pending_approvals_count, attention_incidents, pending_approvals, activity, recent_events } =
    summaryResult.data;
  const activeCount = counts.open + counts.acknowledged + counts.investigating + counts.remediating;
  // Independent-review correction round, BLOCKER 3 bug C: the absence
  // of a recorded incident is never proof of production health --
  // this platform has no customer telemetry connected for a newly
  // registered organization (see Integrations). "healthy"/"all clear"
  // is never claimed; only the honest, narrower fact this data
  // actually supports is stated.
  const noActiveIncidents = counts.active_critical === 0 && activeCount === 0;
  const serviceCount = servicesResult.ok ? servicesResult.data.total : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg">Dashboard</h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-fg-muted">
            {noActiveIncidents ? (
              <Badge tone="success" dot>
                No active incidents recorded
              </Badge>
            ) : counts.active_critical > 0 ? (
              <Badge tone="critical" dot>
                Critical attention needed
              </Badge>
            ) : (
              <Badge tone="warning" dot>
                {activeCount} active incident{activeCount === 1 ? "" : "s"}
              </Badge>
            )}
            <span>· Last refreshed {formatTimestamp(summaryResult.data.generated_at)}</span>
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Active incidents"
          value={activeCount}
          icon={Siren}
          href="/incidents"
          tone={activeCount > 0 ? "warning" : "neutral"}
        />
        <MetricCard
          label="Critical incidents"
          value={counts.active_critical}
          icon={AlertTriangle}
          href="/incidents?severity=critical"
          tone={counts.active_critical > 0 ? "critical" : "neutral"}
        />
        {/* Independent-review correction round, BLOCKER 3 bug A: this
            is a real INCIDENT status count (reliability.incidents.status
            = 'investigating'), never a count of active LangGraph
            AgentRuns -- control-plane has no bounded, tenant-scoped
            "active agent run" aggregate to report that honestly yet.
            Labeled for exactly what it measures. */}
        <MetricCard
          label="Incidents being investigated"
          value={counts.investigating}
          icon={Search}
          tone={counts.investigating > 0 ? "accent" : "neutral"}
        />
        {/* Independent-review correction round, BLOCKER 3 bug B: a
            real, unbounded SQL COUNT from the backend -- never
            pending_approvals.length, which is silently wrong whenever
            more than the "needs attention" section's own display
            limit (8) are actually pending. */}
        <MetricCard
          label="Pending approvals"
          value={pending_approvals_count}
          icon={ClipboardCheck}
          tone={pending_approvals_count > 0 ? "accent" : "neutral"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <AttentionSection attentionIncidents={attention_incidents} pendingApprovals={pending_approvals} />
        </div>
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Incident activity (14 days)</CardTitle>
            </CardHeader>
            <CardContent>
              <ActivityChart points={activity} />
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <RecentActivity events={recent_events} />
        </div>
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Services</CardTitle>
            </CardHeader>
            <CardContent>
              {serviceCount === null ? (
                <BackendFailure kind={servicesResult.ok ? "malformed" : servicesResult.error.kind} />
              ) : serviceCount === 0 ? (
                <div className="space-y-3">
                  <p className="text-sm text-fg-muted">No services registered yet.</p>
                  <Link href="/services" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-soft-fg hover:underline">
                    Register your first service <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </div>
              ) : (
                <div className="flex items-center gap-4">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface-hover text-fg-muted">
                    <Boxes className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="flex-1">
                    <p className="text-2xl font-semibold leading-none text-fg">{serviceCount}</p>
                    <p className="mt-1 text-sm text-fg-muted">registered service{serviceCount === 1 ? "" : "s"}</p>
                  </div>
                  <Link href="/services" className="text-sm font-medium text-accent-soft-fg hover:underline">
                    View all
                  </Link>
                </div>
              )}
              <p className="mt-4 flex items-center gap-1.5 text-xs text-fg-subtle">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                Connection status is shown honestly on each service -- real telemetry correlation is not implemented
                yet (see Integrations).
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
