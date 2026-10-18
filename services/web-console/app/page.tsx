// Dashboard shell. Stage 2 wires real links for the two sections that
// now have real backend-data pages (/incidents, /system); Agent Runs
// remains a placeholder until a later Phase 9 stage implements it. No
// dashboard statistics are fabricated here -- a richer dashboard with
// real aggregate numbers can come later, once it can be obtained
// cleanly without loading unbounded data.
import Link from "next/link";

const SECTIONS = [
  { name: "Incidents", path: "/incidents", available: true },
  { name: "Agent Runs", path: "/agent-runs", available: false },
  { name: "System Health", path: "/system", available: true },
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
        <h2 style={{ fontSize: "1.1rem", color: "#9fb3c8" }}>Sections</h2>
        <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.75rem" }}>
          {SECTIONS.map((section) => (
            <li
              key={section.path}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "1rem",
              }}
            >
              {section.available ? (
                <Link href={section.path}>
                  <strong>{section.name}</strong>
                </Link>
              ) : (
                <>
                  <strong>{section.name}</strong>
                  <span style={{ color: "#6b7f93", marginLeft: "0.5rem" }}>
                    (not yet available -- later Phase 9 stage)
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
