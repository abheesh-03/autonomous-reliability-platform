import type { RetrievalContext, RetrievedContextItem } from "../lib/types/agent-run";

// Renders ONLY the retrieval context already attached to this durable
// investigation report -- never calls retrieval-service, never runs a
// new query. If the report has no retrieval_context, the caller
// simply does not render this component at all.
export function RetrievalContextView({ context }: { context: RetrievalContext }) {
  return (
    <div>
      <p style={{ color: "#9fb3c8" }}>
        outcome: {context.outcome}
        {context.detail ? ` -- ${context.detail}` : ""}
      </p>
      <RetrievedContextGroup title="Runbook / knowledge" items={context.knowledge} />
      <RetrievedContextGroup title="Historical incidents" items={context.historical_incidents} />
    </div>
  );
}

function RetrievedContextGroup({ title, items }: { title: string; items: RetrievedContextItem[] }) {
  if (items.length === 0) return null;
  return (
    <div style={{ marginTop: "0.75rem" }}>
      <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>{title}</h4>
      <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.4rem" }}>
        {items.map((item) => (
          <li key={item.context_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.6rem" }}>
            <div>
              <strong>{item.title}</strong>{" "}
              <span style={{ color: "#6b7f93", fontSize: "0.8rem" }}>
                ({item.source_key}, similarity {item.similarity.toFixed(3)})
              </span>
            </div>
            <div style={{ color: "#9fb3c8", fontSize: "0.9rem" }}>{item.excerpt}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}
