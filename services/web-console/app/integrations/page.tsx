import { Boxes, Cloud, Radio } from "lucide-react";
import { IntegrationCard } from "../../components/integrations/integration-card";
import { requireActorOrRedirect } from "../../lib/server/actor";

export default async function IntegrationsPage() {
  await requireActorOrRedirect();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-fg">Integrations</h1>
        <p className="mt-1 max-w-2xl text-sm text-fg-muted">
          How this platform observes your systems, and the truthful status of each pathway. No integration is ever
          shown as connected unless it genuinely is.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <IntegrationCard
          icon={Radio}
          name="OpenTelemetry"
          description="Real, structured traces, metrics, and logs via the OpenTelemetry Collector -- the same pipeline that already powers this platform's own demo services (Prometheus, Loki, and Tempo ingestion)."
          status="configuration_required"
          blocker="Tenant-scoped, self-service OTLP onboarding (a credentialed endpoint your own organization's services push to, with cross-tenant denial enforced) is not implemented yet. The existing collector pipeline is shared and platform-operated, not per-organization."
          steps={[
            { title: "Select integration", detail: "OpenTelemetry selected.", done: true },
            {
              title: "Review prerequisites",
              detail: "An OpenTelemetry SDK or Collector exporter configured in your service.",
              done: true,
            },
            {
              title: "Configure enrollment",
              detail: "Issue a tenant-bound collector credential scoped to your organization.",
              done: false,
            },
            {
              title: "Validate configuration",
              detail: "Confirm the credential authenticates and is rejected for any other organization.",
              done: false,
            },
            {
              title: "Observe connectivity",
              detail: "Confirm real telemetry arrives, tagged to your organization only.",
              done: false,
            },
            { title: "View resulting data", detail: "See your service's real health on its Services card.", done: false },
          ]}
        />

        <IntegrationCard
          icon={Boxes}
          name="Kubernetes"
          description="Read-only observation of Deployments, Pods, and Events for failure detection and evidence-gathering. Remediation actions remain allowlisted and require human approval."
          status="operator_only"
          blocker="A real, read-only Kubernetes observer exists at the platform level (Phase 12A) for an operator-configured cluster. Self-service, organization-scoped cluster enrollment for your own cluster is not implemented yet."
          steps={[
            { title: "Select integration", detail: "Kubernetes selected.", done: true },
            { title: "Review prerequisites", detail: "A read-only service account/kubeconfig for your cluster.", done: false },
            { title: "Configure enrollment", detail: "Bind that credential to your organization only.", done: false },
            { title: "Validate configuration", detail: "Confirm read-only access and tenant isolation.", done: false },
            { title: "Observe connectivity", detail: "Confirm real cluster observations arrive.", done: false },
            { title: "View resulting data", detail: "See Kubernetes evidence on relevant incidents.", done: false },
          ]}
        />

        <IntegrationCard
          icon={Cloud}
          name="AWS (read-only)"
          description="Read-only observation of relevant AWS resources for incident evidence. No resource provisioning, no Terraform apply, and no autonomous AWS remediation -- ever."
          status="operator_only"
          blocker="A real, read-only AWS observer exists at the platform level (Phase 13) for an operator-configured account. Self-service, organization-scoped account enrollment is not implemented yet."
          steps={[
            { title: "Select integration", detail: "AWS selected.", done: true },
            { title: "Review prerequisites", detail: "A read-only IAM role for your AWS account.", done: false },
            { title: "Configure enrollment", detail: "Bind that role to your organization only.", done: false },
            { title: "Validate configuration", detail: "Confirm read-only access and tenant isolation.", done: false },
            { title: "Observe connectivity", detail: "Confirm real AWS observations arrive.", done: false },
            { title: "View resulting data", detail: "See AWS evidence on relevant incidents.", done: false },
          ]}
        />
      </div>
    </div>
  );
}
