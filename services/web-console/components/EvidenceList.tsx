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
      <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>Source collection</h4>
      <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.3rem" }}>
        {sourceOutcomes.map((outcome, index) => (
          <li key={`${outcome.source}-${index}`} style={{ fontSize: "0.85rem", color: "#9fb3c8" }}>
            {outcome.source}: {outcome.status} -- {outcome.detail}
          </li>
        ))}
      </ul>

      <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>
        Evidence ({evidence.length})
      </h4>
      {evidence.length === 0 ? (
        <p style={{ color: "#9fb3c8" }}>No evidence items.</p>
      ) : (
        <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
          {evidence.map((item) => (
            <li key={item.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.6rem" }}>
              <div>
                <strong>{item.source}</strong>{" "}
                <span style={{ color: "#6b7f93", fontSize: "0.8rem" }}>{item.id}</span>
              </div>
              <div>{item.summary}</div>
              {item.observed_at && (
                <div style={{ color: "#6b7f93", fontSize: "0.8rem" }}>
                  observed {formatTimestamp(item.observed_at)}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
