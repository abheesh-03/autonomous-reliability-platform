export function WorkflowProgress({
  completedNodes,
  currentNode,
}: {
  completedNodes: string[];
  currentNode: string;
}) {
  return (
    <div>
      <p style={{ color: "#9fb3c8", margin: "0 0 0.5rem" }}>
        {completedNodes.length} completed node{completedNodes.length === 1 ? "" : "s"}
      </p>
      <ol style={{ listStyle: "none", padding: 0, display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {completedNodes.map((node, index) => (
          <li
            key={`${node}-${index}`}
            style={{
              border: "1px solid #2a4a33",
              background: "#0f1a12",
              color: "#a8f3c0",
              borderRadius: 6,
              padding: "0.25rem 0.6rem",
              fontSize: "0.85rem",
            }}
          >
            {node}
          </li>
        ))}
        <li
          style={{
            border: "1px solid var(--accent)",
            background: "#0f1a24",
            color: "var(--accent)",
            borderRadius: 6,
            padding: "0.25rem 0.6rem",
            fontSize: "0.85rem",
          }}
        >
          {currentNode} (current)
        </li>
      </ol>
    </div>
  );
}
