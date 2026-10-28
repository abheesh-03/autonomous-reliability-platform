import { Check } from "lucide-react";

export function WorkflowProgress({
  completedNodes,
  currentNode,
}: {
  completedNodes: string[];
  currentNode: string;
}) {
  return (
    <div>
      <p className="mb-2 text-sm text-fg-muted">
        {completedNodes.length} completed node{completedNodes.length === 1 ? "" : "s"}
      </p>
      <ol className="flex flex-wrap gap-2">
        {completedNodes.map((node, index) => (
          <li
            key={`${node}-${index}`}
            className="flex items-center gap-1 rounded-md border border-success-fg/30 bg-success-soft-bg px-2.5 py-1 text-xs font-medium text-success-fg"
          >
            <Check className="h-3 w-3" aria-hidden="true" />
            {node}
          </li>
        ))}
        <li className="rounded-md border border-accent bg-accent-soft-bg px-2.5 py-1 text-xs font-medium text-accent-soft-fg">
          {currentNode} (current)
        </li>
      </ol>
    </div>
  );
}
