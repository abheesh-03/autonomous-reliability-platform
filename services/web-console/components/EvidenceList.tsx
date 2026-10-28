import { formatTimestamp } from "../lib/format";
import type { EvidenceItem, SourceOutcome } from "../lib/types/agent-run";

export function EvidenceList({
  evidence,
  sourceOutcomes,
}: {
  evidence: EvidenceItem[];
  sourceOutcomes: SourceOutcome[];
}) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-fg">Source collection</h4>
      <ul className="grid grid-cols-1 gap-1">
        {sourceOutcomes.map((outcome, index) => (
          <li key={`${outcome.source}-${index}`} className="text-xs text-fg-muted">
            {outcome.source}: {outcome.status} -- {outcome.detail}
          </li>
        ))}
      </ul>

      <h4 className="mb-2 mt-4 text-sm font-semibold text-fg">Evidence ({evidence.length})</h4>
      {evidence.length === 0 ? (
        <p className="text-sm text-fg-muted">No evidence items.</p>
      ) : (
        <ol className="grid grid-cols-1 gap-2">
          {evidence.map((item) => (
            <li key={item.id} className="rounded-lg border border-border bg-surface p-3 text-sm">
              <div>
                <strong className="font-medium text-fg">{item.source}</strong>{" "}
                <span className="text-xs text-fg-subtle">{item.id}</span>
              </div>
              <div className="text-fg-muted">{item.summary}</div>
              {item.observed_at && (
                <div className="text-xs text-fg-subtle">observed {formatTimestamp(item.observed_at)}</div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
