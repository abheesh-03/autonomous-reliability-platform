import Link from "next/link";
import { formatTimestamp } from "../lib/format";
import type { AgentRun } from "../lib/types/agent-run";
import { StatusBadgePill } from "./StatusBadge";

export function AgentRunSummary({ agentRun }: { agentRun: AgentRun }) {
  return (
    <section>
      <p className="flex items-center gap-2 text-sm">
        <StatusBadgePill status={agentRun.status} />
        <span className="text-fg-muted">current node: {agentRun.current_node}</span>
        <span className={agentRun.resumable ? "text-success-fg" : "text-fg-muted"}>
          {agentRun.resumable ? "resumable" : "not resumable"}
        </span>
      </p>
      <dl className="mt-3 grid grid-cols-[8rem_minmax(0,1fr)] sm:grid-cols-[10rem_minmax(0,1fr)] gap-y-2 text-sm">
        <dt className="text-fg-muted">Run ID</dt>
        <dd className="font-mono text-xs text-fg break-all">{agentRun.run_id}</dd>
        <dt className="text-fg-muted">Thread ID</dt>
        <dd className="font-mono text-xs text-fg-subtle break-all">{agentRun.thread_id}</dd>
        <dt className="text-fg-muted">Incident</dt>
        <dd>
          <Link href={`/incidents/${agentRun.incident_id}`} className="text-accent-soft-fg hover:underline">
            {agentRun.incident_id}
          </Link>
        </dd>
        <dt className="text-fg-muted">Started</dt>
        <dd className="text-fg break-words">{formatTimestamp(agentRun.started_at)}</dd>
        <dt className="text-fg-muted">Updated</dt>
        <dd className="text-fg break-words">{formatTimestamp(agentRun.updated_at)}</dd>
        <dt className="text-fg-muted">Completed</dt>
        <dd className="text-fg break-words">{formatTimestamp(agentRun.completed_at)}</dd>
      </dl>
    </section>
  );
}
