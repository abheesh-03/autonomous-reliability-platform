import Link from "next/link";
import { Boxes, Database, Cloud, Server, Workflow, Network, Layers } from "lucide-react";
import { BackendFailure } from "../../components/BackendFailure";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/ui/empty-state";
import { RegisterServiceDialog } from "../../components/services/register-service-dialog";
import { formatTimestamp } from "../../lib/format";
import { listServices } from "../../lib/server/service-client";
import { parseServiceListSearchParams, type RawSearchParams } from "../../lib/service-query";
import { ROLES_THAT_MAY_REGISTER_SERVICES, SERVICE_KIND_LABELS, type ServiceKind } from "../../lib/types/service";
import { requireActorOrRedirect, signAssertion } from "../../lib/server/actor";

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

export default async function ServicesPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const actor = await requireActorOrRedirect();
  const actorToken = await signAssertion(actor, "control-plane");

  const rawParams = await searchParams;
  const { limit, offset } = parseServiceListSearchParams(rawParams);
  const result = await listServices(actorToken, { limit, offset });

  // Independent-review correction round, BLOCKER 2: a UI-only
  // convenience that mirrors control-plane's own real enforcement
  // (core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES) -- see
  // RegisterServiceDialog's own docstring for why this never replaces
  // the backend's own check.
  const canRegister = (ROLES_THAT_MAY_REGISTER_SERVICES as readonly string[]).includes(actor.role);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-fg">Services</h1>
          <p className="mt-1 text-sm text-fg-muted">
            The systems your organization operates -- APIs, microservices, databases, queues, Kubernetes workloads,
            and cloud resources.
          </p>
        </div>
        <RegisterServiceDialog canRegister={canRegister} />
      </div>

      {!result.ok ? (
        <BackendFailure kind={result.error.kind} />
      ) : result.data.items.length === 0 && offset === 0 ? (
        <Card>
          <EmptyState
            icon={Boxes}
            title="No services registered yet"
            description="Register the first service your organization operates -- this is a catalog entry, not a telemetry connection. Connect real monitoring data from the Integrations page once a service is registered."
            action={<RegisterServiceDialog canRegister={canRegister} />}
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {result.data.items.map((service) => {
              const Icon = KIND_ICONS[service.kind];
              return (
                <Link key={service.id} href={`/services/${service.id}`} className="block">
                  <Card className="h-full transition-colors hover:bg-surface-hover">
                    <CardContent className="space-y-3 pt-5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
                            <Icon className="h-4 w-4" aria-hidden="true" />
                          </div>
                          <div>
                            <p className="font-medium text-fg">{service.name}</p>
                            <p className="text-xs text-fg-subtle">{SERVICE_KIND_LABELS[service.kind]}</p>
                          </div>
                        </div>
                      </div>
                      {service.description && <p className="text-sm text-fg-muted">{service.description}</p>}
                      <div className="flex items-center justify-between pt-1">
                        {service.language ? (
                          <Badge tone="neutral">{service.language}</Badge>
                        ) : (
                          <span className="text-xs text-fg-subtle">Language not specified</span>
                        )}
                        <Badge tone="neutral" dot>
                          View integration
                        </Badge>
                      </div>
                      <p className="text-xs text-fg-subtle">Registered {formatTimestamp(service.created_at)}</p>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>
          <ServicePagination total={result.data.total} limit={result.data.limit} offset={result.data.offset} />
        </>
      )}
    </div>
  );
}

// Independent-review correction round, BLOCKER 4: a real pagination
// control, mirroring app/incidents/page.tsx's own -- a service
// registry with more than one page of results must remain navigable,
// never silently truncated to the first page with no way to reach the
// rest.
function ServicePagination({ total, limit, offset }: { total: number; limit: number; offset: number }) {
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  if (!hasPrev && !hasNext) return null;

  return (
    <nav className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface px-4 py-3">
      <p className="text-sm text-fg-muted">
        {total} service{total === 1 ? "" : "s"} total
      </p>
      <div className="flex items-center gap-4">
        {hasPrev ? (
          <Link
            href={`/services?offset=${Math.max(0, offset - limit)}`}
            className="text-sm font-medium text-accent-soft-fg hover:underline"
          >
            ← Previous
          </Link>
        ) : (
          <span className="text-sm text-fg-subtle">← Previous</span>
        )}
        {hasNext ? (
          <Link href={`/services?offset=${offset + limit}`} className="text-sm font-medium text-accent-soft-fg hover:underline">
            Next →
          </Link>
        ) : (
          <span className="text-sm text-fg-subtle">Next →</span>
        )}
      </div>
    </nav>
  );
}
