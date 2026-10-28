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
    return <p className="text-sm text-fg-muted">No checkpoint history recorded.</p>;
  }
  return (
    <ol className="grid grid-cols-1 gap-2">
      {entries.map((entry) => (
        <li key={entry.checkpoint_id} className="rounded-lg border border-border bg-surface p-3 text-sm">
          <div>
            <strong className="font-medium text-fg">step {entry.step}</strong>{" "}
            <span className="text-fg">-- {entry.node}</span>{" "}
            <span className="text-fg-muted">({entry.status_at_step})</span>
          </div>
          {entry.next_nodes.length > 0 && (
            <div className="text-fg-muted">next: {entry.next_nodes.join(", ")}</div>
          )}
          <div className="text-xs text-fg-subtle">{formatTimestamp(entry.created_at)}</div>
          <div className="text-xs text-fg-subtle">checkpoint: {entry.checkpoint_id}</div>
        </li>
      ))}
    </ol>
  );
}
