import type { RetrievalContext, RetrievedContextItem } from "../lib/types/agent-run";

// Renders ONLY the retrieval context already attached to this durable
// investigation report -- never calls retrieval-service, never runs a
// new query. If the report has no retrieval_context, the caller
// simply does not render this component at all.
export function RetrievalContextView({ context }: { context: RetrievalContext }) {
  return (
    <div>
      <p className="text-sm text-fg-muted">
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
    <div className="mt-3">
      <h4 className="mb-2 text-sm font-semibold text-fg">{title}</h4>
      <ol className="grid grid-cols-1 gap-2">
        {items.map((item) => (
          <li key={item.context_id} className="rounded-lg border border-border bg-surface p-3 text-sm">
            <div className="break-words">
              <strong className="font-medium text-fg">{item.title}</strong>{" "}
              <span className="text-xs text-fg-subtle">
                ({item.source_key}, similarity {item.similarity.toFixed(3)})
              </span>
            </div>
            <div className="break-words text-fg-muted">{item.excerpt}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}
