import Link from "next/link";
import { notFound } from "next/navigation";
import { Boxes, Database, Cloud, Server, Workflow, Network, Layers } from "lucide-react";
import { BackendFailure } from "../../../components/BackendFailure";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { SeverityBadge, StatusBadgePill } from "../../../components/StatusBadge";
import { IntegrationSetupFlow } from "../../../components/services/integration-setup-flow";
import { TelemetryPanel } from "../../../components/services/telemetry-panel";
import { formatTimestamp } from "../../../lib/format";
import { getService } from "../../../lib/server/service-client";
import { listIntegrationCredentials, getServiceTelemetrySummary } from "../../../lib/server/integration-client";
import { listIncidents } from "../../../lib/server/control-plane-client";
import { SERVICE_KIND_LABELS, ROLES_THAT_MAY_REGISTER_SERVICES, type ServiceKind } from "../../../lib/types/service";
import { requireActorOrRedirect, signAssertion } from "../../../lib/server/actor";

const KIND_ICONS: Record<ServiceKind, typeof Boxes> = {
  rest_api: Network,
  graphql_api: Network,
  microservice: Workflow,
  database: Database,
  queue_worker: Layers,
  kubernetes_workload: Server,
  cloud_resource: Cloud,
  other: Boxes,
};

export default async function ServiceDetailPage({
  params,
}: {
  params: Promise<{ serviceId: string }>;
}) {
  const actor = await requireActorOrRedirect();
  const actorToken = await signAssertion(actor, "control-plane");
  const { serviceId } = await params;

  const [serviceResult, telemetryResult, integrationsResult, incidentsResult] = await Promise.all([
    getService(serviceId, actorToken),
    getServiceTelemetrySummary(serviceId, actorToken),
    listIntegrationCredentials(serviceId, actorToken),
    // Gate 5: "Recent incidents" -- a real, already-org-scoped query,
    // filtered client-side to this service's own real incident
    // fingerprint (see ingestion/telemetry_threshold_detector.py's
    // `service:<service_id>` convention). No dedicated "incidents by
    // service" backend endpoint exists yet this round; see this
    // page's own "known limitations" note in
    // docs/architecture/phase-16-secure-telemetry-onboarding.md.
    listIncidents({ source: "otel-telemetry", limit: 50 }, actorToken),
  ]);

  if (!serviceResult.ok) {
    if (serviceResult.error.kind === "not_found") notFound();
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Link href="/services" className="text-sm text-fg-muted hover:text-fg">
          &larr; Services
        </Link>
        <BackendFailure kind={serviceResult.error.kind} />
      </div>
    );
  }

  const service = serviceResult.data;
  const Icon = KIND_ICONS[service.kind];
  const canManage = (ROLES_THAT_MAY_REGISTER_SERVICES as readonly string[]).includes(actor.role);

  const relatedIncidents = incidentsResult.ok
    ? incidentsResult.data.items.filter((incident) => incident.source_fingerprint === `service:${serviceId}`)
    : [];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/services" className="text-sm text-fg-muted hover:text-fg">
        &larr; Services
      </Link>

      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-hover text-fg-muted">
          <Icon className="h-5 w-5" aria-hidden="true" />
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

      <section>
        <h2 className="mb-2 text-sm font-semibold text-fg">Telemetry</h2>
        {telemetryResult.ok ? (
          <TelemetryPanel summary={telemetryResult.data} />
        ) : (
          <Card>
            <CardContent className="pt-5">
              <BackendFailure kind={telemetryResult.error.kind} />
            </CardContent>
          </Card>
        )}
      </section>

      <section>
        <Card>
          <CardContent className="pt-5">
            {integrationsResult.ok ? (
              <IntegrationSetupFlow
                serviceId={serviceId}
                initialCredentials={integrationsResult.data.items}
                canManage={canManage}
                otlpEndpoint={process.env.NEXT_PUBLIC_OTLP_INGEST_ENDPOINT ?? "http://127.0.0.1:8000"}
              />
            ) : (
              <BackendFailure kind={integrationsResult.error.kind} />
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardTitle>Recent incidents</CardTitle>
          </CardHeader>
          <CardContent>
            {relatedIncidents.length === 0 ? (
              <p className="text-sm text-fg-muted">No incidents recorded for this service.</p>
            ) : (
              <ul className="divide-y divide-border">
                {relatedIncidents.map((incident) => (
                  <li key={incident.id} className="flex items-center justify-between gap-3 py-2.5">
                    <Link
                      href={`/incidents/${incident.id}`}
                      className="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-1 py-0.5 hover:bg-surface-hover"
                    >
                      <SeverityBadge severity={incident.severity} />
                      <StatusBadgePill status={incident.status} />
                      <span className="truncate text-sm text-fg">{incident.title}</span>
                      <span className="ml-auto shrink-0 text-xs text-fg-subtle">{formatTimestamp(incident.last_seen_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
