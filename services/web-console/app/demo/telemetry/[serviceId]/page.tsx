import { notFound } from "next/navigation";
import Link from "next/link";
import { Network } from "lucide-react";
import { Card, CardContent } from "../../../../components/ui/card";
import { Badge } from "../../../../components/ui/badge";
import { TelemetryPanel } from "../../../../components/services/telemetry-panel";
import { SERVICE_KIND_LABELS } from "../../../../lib/types/service";
import { formatTimestamp } from "../../../../lib/format";
import { demoSnapshot } from "../../../../lib/demo/snapshot";

export const metadata = {
  title: "Recorded telemetry — Reliability Console demo",
};

/**
 * Phase 18: a read-only replay of the live service-detail page's
 * telemetry section (app/services/[serviceId]/page.tsx), against the
 * bundled static snapshot only. This is a SEPARATE real recording
 * from the incident/investigation scenario -- a different service, a
 * different organization -- never presented as the same story (see
 * lib/demo/types.ts's own provenance split). Deliberately omits
 * `IntegrationSetupFlow` (its live "Generate credential" action
 * button); the credential is shown as a static, already-created,
 * read-only record instead. Only the snapshot's own real recorded
 * service id resolves; any other id is a genuine not-found.
 */
export default async function DemoTelemetryPage({ params }: { params: Promise<{ serviceId: string }> }) {
  const { serviceId } = await params;
  const { telemetry_scenario } = demoSnapshot;
  const { service, credential, summary } = telemetry_scenario;
  if (serviceId !== service.id) notFound();

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/demo" className="text-sm text-fg-muted hover:text-fg">
        &larr; Recorded demo
      </Link>

      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-hover text-fg-muted">
          <Network className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-fg">{service.name}</h1>
          <p className="mt-0.5 text-sm text-fg-muted">
            {SERVICE_KIND_LABELS[service.kind]}
            {service.language ? ` · ${service.language}` : ""}
          </p>
          {service.description && <p className="mt-1 text-sm text-fg-muted">{service.description}</p>}
        </div>
      </div>

      <p className="rounded-lg border border-border bg-surface-sunken p-3 text-sm text-fg-muted">
        This is a separate real recording from the incident/investigation example -- a different service, captured
        from one real OpenTelemetry metrics export using the official OTel SDK, not an auto-resolved or
        human-approved remediation.
      </p>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-fg">Telemetry</h2>
        <TelemetryPanel summary={summary} />
      </section>

      <section>
        <Card>
          <CardContent className="space-y-3 pt-5">
            <h2 className="text-sm font-semibold text-fg">OpenTelemetry integration (recorded)</h2>
            <p className="text-sm text-fg-muted">
              Authenticated metrics ingestion for this service only — a credential never grants access to any other
              service or organization.
            </p>
            <div className="flex items-center justify-between rounded-lg border border-border bg-surface-sunken p-3 text-sm">
              <div>
                <p className="font-mono text-xs text-fg">{credential.credential_id}</p>
                <p className="text-xs text-fg-subtle">
                  Created {formatTimestamp(credential.created_at)} · last telemetry{" "}
                  {formatTimestamp(credential.last_verified_telemetry_at)}
                </p>
              </div>
              <Badge tone={credential.status === "active" ? "success" : "critical"} dot>
                {credential.status}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
