// Stage 1 shell only: establishes product identity and the intended
// navigation structure. No incident/agent-run data, no backend calls,
// no operator credentials -- those arrive in later Phase 9 stages.
// A Server Component (the default for this app): nothing here runs in
// the browser, so there is nothing client-side to expose.

const PLANNED_SECTIONS = [
  { name: "Incidents", path: "/incidents" },
  { name: "Agent Runs", path: "/agent-runs" },
  { name: "System Health", path: "/system" },
] as const;

export default function HomePage() {
  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.75rem" }}>Reliability Console</h1>
        <p style={{ color: "#9fb3c8", marginTop: "0.5rem" }}>
          Operator console for the Autonomous Production Reliability
          Platform.
        </p>
      </header>

      <section>
        <h2 style={{ fontSize: "1.1rem", color: "#9fb3c8" }}>
          Planned sections
        </h2>
        <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.75rem" }}>
          {PLANNED_SECTIONS.map((section) => (
            <li
              key={section.path}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "1rem",
              }}
            >
              <strong>{section.name}</strong>
              <span style={{ color: "#6b7f93", marginLeft: "0.5rem" }}>
                (not yet available -- later Phase 9 stage)
              </span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
