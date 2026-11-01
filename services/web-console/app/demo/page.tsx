import Link from "next/link";
import { LayoutDashboard, Siren, Sparkles, Gauge, ArrowRight } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { SeverityBadge, StatusBadgePill } from "../../components/StatusBadge";
import { DemoDisclosure } from "../../components/demo/demo-disclosure";
import { demoSnapshot } from "../../lib/demo/snapshot";

export const metadata = {
  title: "Recorded demo — Reliability Console",
};

const COUNT_LABELS: Array<[keyof typeof demoSnapshot.dashboard_counts, string]> = [
  ["open", "Open"],
  ["investigating", "Investigating"],
  ["remediating", "Remediating"],
  ["resolved", "Resolved"],
  ["active_critical", "Active critical"],
];

/**
 * Phase 18: the recorded demo's entry point. A populated recorded
 * dashboard summary, the required disclosure, and three entry points
 * into the rest of the demo -- never a fourth, decorative page with
 * nothing in it.
 */
export default function DemoOverviewPage() {
  const { incident_scenario, telemetry_scenario } = demoSnapshot;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-fg">
          <LayoutDashboard className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
          Recorded demo dashboard
        </h1>
        <p className="mt-1 text-sm text-fg-muted">
          A real, completed incident investigation and a real OpenTelemetry telemetry recording, replayed exactly as
          captured -- explore without creating an account.
        </p>
      </div>

      <DemoDisclosure provenance={demoSnapshot.provenance} />

      <section>
        <h2 className="mb-2 text-sm font-semibold text-fg">Incident status counts (recorded)</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {COUNT_LABELS.map(([key, label]) => (
            <Card key={key}>
              <CardContent className="pt-5">
                <p className="text-2xl font-semibold text-fg">{demoSnapshot.dashboard_counts[key]}</p>
                <p className="text-xs text-fg-muted">{label}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-3">
        <Link
          href={`/demo/incident/${incident_scenario.incident.id}`}
          className="group rounded-xl border border-border bg-surface p-4 transition-colors hover:bg-surface-hover"
        >
          <Siren className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
          <h3 className="mt-2 text-sm font-semibold text-fg">Incident &amp; audit timeline</h3>
          <p className="mt-1 text-sm text-fg-muted">{incident_scenario.incident.title}</p>
          <p className="mt-2 flex gap-2">
            <SeverityBadge severity={incident_scenario.incident.severity} />
            <StatusBadgePill status={incident_scenario.incident.status} />
          </p>
          <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent-soft-fg">
            View incident <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </span>
        </Link>

        <Link
          href={`/demo/investigation/${incident_scenario.agent_run.run_id}`}
          className="group rounded-xl border border-border bg-surface p-4 transition-colors hover:bg-surface-hover"
        >
          <Sparkles className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
          <h3 className="mt-2 text-sm font-semibold text-fg">AI investigation</h3>
          <p className="mt-1 text-sm text-fg-muted">
            Completed investigation, recorded human approval, bounded remediation, and recovery verification.
          </p>
          <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent-soft-fg">
            View investigation <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </span>
        </Link>

        <Link
          href={`/demo/telemetry/${telemetry_scenario.service.id}`}
          className="group rounded-xl border border-border bg-surface p-4 transition-colors hover:bg-surface-hover"
        >
          <Gauge className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
          <h3 className="mt-2 text-sm font-semibold text-fg">Service telemetry</h3>
          <p className="mt-1 text-sm text-fg-muted">{telemetry_scenario.service.name} — a separate, real OpenTelemetry recording.</p>
          <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent-soft-fg">
            View telemetry <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </span>
        </Link>
      </section>
    </div>
  );
}
