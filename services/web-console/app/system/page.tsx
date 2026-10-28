import Link from "next/link";
import { Info } from "lucide-react";
import { checkServiceHealth } from "../../lib/server/health-client";
import type { ServiceHealthResult } from "../../lib/types/health";
import { Badge, type BadgeProps } from "../../components/ui/badge";
import { Card, CardContent } from "../../components/ui/card";

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
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-fg">System health</h1>
        <p className="mt-1 text-sm text-fg-muted">The platform&apos;s own backend components -- not your registered services.</p>
      </div>

      <div className="flex items-start gap-2.5 rounded-lg border border-border bg-surface-sunken px-4 py-3 text-sm text-fg-muted">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-info-fg" aria-hidden="true" />
        <p>
          This page shows this platform&apos;s own internal components (control-plane, agent-runtime, investigator,
          retrieval). It is not a reliability signal for anything in your{" "}
          <Link href="/services" className="text-accent-soft-fg hover:underline">
            service catalog
          </Link>
          .
        </p>
      </div>

      <Card>
        <CardContent className="pt-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-fg-subtle">
                <th className="pb-2">Service</th>
                <th className="pb-2">Live</th>
                <th className="pb-2">Ready</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <ServiceRow key={result.name} result={result} />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

const LIVE_TONE: Record<string, BadgeProps["tone"]> = {
  UP: "success",
  UNAVAILABLE: "critical",
  UNKNOWN: "neutral",
};

const READY_TONE: Record<string, BadgeProps["tone"]> = {
  READY: "success",
  NOT_READY: "warning",
  UNAVAILABLE: "critical",
  UNKNOWN: "neutral",
};

function ServiceRow({ result }: { result: ServiceHealthResult }) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-2.5 text-fg">{result.name}</td>
      <td className="py-2.5">
        <Badge tone={LIVE_TONE[result.live] ?? "neutral"}>{result.live}</Badge>
      </td>
      <td className="py-2.5">
        <Badge tone={READY_TONE[result.ready] ?? "neutral"}>{result.ready}</Badge>
      </td>
    </tr>
  );
}
