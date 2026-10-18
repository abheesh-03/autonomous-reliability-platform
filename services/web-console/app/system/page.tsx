import Link from "next/link";
import { checkServiceHealth } from "../../lib/server/health-client";
import type { ServiceHealthResult } from "../../lib/types/health";

const MONITORED_SERVICES: Array<{ name: string; baseUrl: string }> = [
  { name: "control-plane", baseUrl: process.env.WEB_CONSOLE_CONTROL_PLANE_URL ?? "http://control-plane:8000" },
  {
    name: "agent-runtime-service",
    baseUrl: process.env.WEB_CONSOLE_AGENT_RUNTIME_URL ?? "http://agent-runtime-service:8003",
  },
  {
    name: "investigator-service",
    baseUrl: process.env.WEB_CONSOLE_INVESTIGATOR_URL ?? "http://investigator-service:8001",
  },
  {
    name: "retrieval-service",
    baseUrl: process.env.WEB_CONSOLE_RETRIEVAL_URL ?? "http://retrieval-service:8002",
  },
];

export default async function SystemPage() {
  // Promise.all is safe here: checkServiceHealth never rejects (every
  // network/parse failure resolves to an UNAVAILABLE/UNKNOWN status),
  // so one unreachable service can never prevent the others from
  // rendering their own real result.
  const results = await Promise.all(
    MONITORED_SERVICES.map((service) => checkServiceHealth(service.name, service.baseUrl)),
  );

  return (
    <main style={{ maxWidth: 700, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <p>
        <Link href="/">&larr; Dashboard</Link>
      </p>
      <h1 style={{ marginTop: "0.5rem" }}>System health</h1>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
            <th>Service</th>
            <th>Live</th>
            <th>Ready</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <ServiceRow key={result.name} result={result} />
          ))}
        </tbody>
      </table>
    </main>
  );
}

const LIVE_COLORS: Record<string, string> = {
  UP: "#a8f3c0",
  UNAVAILABLE: "#f3c9c9",
  UNKNOWN: "#9fb3c8",
};

const READY_COLORS: Record<string, string> = {
  READY: "#a8f3c0",
  NOT_READY: "#f3e2a8",
  UNAVAILABLE: "#f3c9c9",
  UNKNOWN: "#9fb3c8",
};

function ServiceRow({ result }: { result: ServiceHealthResult }) {
  return (
    <tr style={{ borderBottom: "1px solid var(--border)" }}>
      <td>{result.name}</td>
      <td style={{ color: LIVE_COLORS[result.live] }}>{result.live}</td>
      <td style={{ color: READY_COLORS[result.ready] }}>{result.ready}</td>
    </tr>
  );
}
