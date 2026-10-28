import Link from "next/link";
import { ArrowRight, CheckCircle2, ShieldQuestion } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { EmptyState } from "../ui/empty-state";
import { formatTimestamp } from "../../lib/format";
import type { AttentionIncident, PendingApproval } from "../../lib/types/dashboard";

const SEVERITY_TONE: Record<string, "critical" | "warning" | "info"> = {
  critical: "critical",
  warning: "warning",
  info: "info",
};

export function AttentionSection({
  attentionIncidents,
  pendingApprovals,
}: {
  attentionIncidents: AttentionIncident[];
  pendingApprovals: PendingApproval[];
}) {
  const hasNothing = attentionIncidents.length === 0 && pendingApprovals.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Needs attention</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {hasNothing ? (
          <EmptyState
            icon={CheckCircle2}
            title="Nothing needs attention right now"
            description="No active incidents and no pending remediation approvals."
          />
        ) : (
          <ul className="divide-y divide-border">
            {pendingApprovals.map((approval) => (
              <li key={approval.proposal_id} className="py-2.5">
                <Link
                  href={`/agent-runs/${approval.agent_run_id}`}
                  className="group flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-1 py-0.5 hover:bg-surface-hover sm:flex-nowrap"
                >
                  <ShieldQuestion className="h-4 w-4 shrink-0 text-violet-fg" aria-hidden="true" />
                  <div className="min-w-0 flex-1 basis-full sm:basis-auto">
                    <p className="truncate text-sm font-medium text-fg">
                      Approval needed: {approval.action_type} on {approval.target}
                    </p>
                    <p className="truncate text-xs text-fg-muted">{approval.incident_title}</p>
                  </div>
                  {/* Independent-review correction round, BLOCKER 5: no
                      longer `shrink-0` -- that forced this timestamp to
                      render at its full single-line width regardless of
                      available space, which is what actually drove the
                      dashboard's real horizontal overflow at a 375px
                      viewport (confirmed via document.documentElement.
                      scrollWidth, not assumed). It now wraps onto its
                      own line below the title on narrow viewports
                      (`basis-full` forces that break) and sits inline,
                      right-aligned, from sm: up. */}
                  <span className="ml-7 shrink text-xs text-fg-subtle sm:ml-0 sm:shrink-0">
                    {formatTimestamp(approval.proposed_at)}
                  </span>
                  <ArrowRight className="hidden h-3.5 w-3.5 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100 sm:block" aria-hidden="true" />
                </Link>
              </li>
            ))}
            {attentionIncidents.map((incident) => (
              <li key={incident.id} className="py-2.5">
                <Link
                  href={`/incidents/${incident.id}`}
                  className="group flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-1 py-0.5 hover:bg-surface-hover sm:flex-nowrap"
                >
                  <Badge tone={SEVERITY_TONE[incident.severity] ?? "neutral"} className="shrink-0">
                    {incident.severity}
                  </Badge>
                  <div className="min-w-0 flex-1 basis-full sm:basis-auto">
                    <p className="truncate text-sm font-medium text-fg">{incident.title}</p>
                    <p className="truncate text-xs text-fg-muted">
                      {incident.status} · {incident.source}
                    </p>
                  </div>
                  <span className="ml-7 shrink text-xs text-fg-subtle sm:ml-0 sm:shrink-0">
                    {formatTimestamp(incident.last_seen_at)}
                  </span>
                  <ArrowRight className="hidden h-3.5 w-3.5 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100 sm:block" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
