import Link from "next/link";
import { formatTimestamp } from "../lib/format";
import type { AgentRun } from "../lib/types/agent-run";
import { StatusBadgePill } from "./StatusBadge";

export function AgentRunSummary({ agentRun }: { agentRun: AgentRun }) {
  return (
    <section>
      <p style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <StatusBadgePill status={agentRun.status} />
        <span style={{ color: "#9fb3c8" }}>current node: {agentRun.current_node}</span>
        <span style={{ color: agentRun.resumable ? "#a8f3c0" : "#9fb3c8" }}>
          {agentRun.resumable ? "resumable" : "not resumable"}
        </span>
      </p>
      <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", rowGap: "0.4rem" }}>
        <dt style={{ color: "#9fb3c8" }}>Run ID</dt>
        <dd style={{ fontSize: "0.85rem" }}>{agentRun.run_id}</dd>
        <dt style={{ color: "#9fb3c8" }}>Thread ID</dt>
        <dd style={{ fontSize: "0.85rem", color: "#6b7f93" }}>{agentRun.thread_id}</dd>
        <dt style={{ color: "#9fb3c8" }}>Incident</dt>
        <dd>
          <Link href={`/incidents/${agentRun.incident_id}`}>{agentRun.incident_id}</Link>
        </dd>
        <dt style={{ color: "#9fb3c8" }}>Started</dt>
        <dd>{formatTimestamp(agentRun.started_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Updated</dt>
        <dd>{formatTimestamp(agentRun.updated_at)}</dd>
        <dt style={{ color: "#9fb3c8" }}>Completed</dt>
        <dd>{formatTimestamp(agentRun.completed_at)}</dd>
      </dl>
    </section>
  );
}
