import { formatTimestamp } from "../lib/format";
import type { AgentRunHistoryEntry } from "../lib/types/agent-run";

// Chronological, exactly as the backend returns it (api/agent_runs.py
// reverses LangGraph's own newest-first aget_state_history before
// responding) -- this component never re-sorts or re-derives order.
// Never claims completeness from array length alone: the AgentRun's
// own current_node/completed_nodes/status remain the authoritative
// terminal/current state (see AgentRunSummary/WorkflowProgress).
export function CheckpointTimeline({ entries }: { entries: AgentRunHistoryEntry[] }) {
  if (entries.length === 0) {
    return <p style={{ color: "#9fb3c8" }}>No checkpoint history recorded.</p>;
  }
  return (
    <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
      {entries.map((entry) => (
        <li
          key={entry.checkpoint_id}
          style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.75rem" }}
        >
          <div>
            <strong>step {entry.step}</strong> -- <span>{entry.node}</span>{" "}
            <span style={{ color: "#9fb3c8" }}>({entry.status_at_step})</span>
          </div>
          {entry.next_nodes.length > 0 && (
            <div style={{ color: "#9fb3c8", fontSize: "0.9rem" }}>next: {entry.next_nodes.join(", ")}</div>
          )}
          <div style={{ color: "#6b7f93", fontSize: "0.85rem" }}>{formatTimestamp(entry.created_at)}</div>
          <div style={{ color: "#6b7f93", fontSize: "0.75rem" }}>checkpoint: {entry.checkpoint_id}</div>
        </li>
      ))}
    </ol>
  );
}
