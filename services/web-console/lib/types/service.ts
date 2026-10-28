// Mirrors control-plane's real contract exactly
// (services/control-plane/src/control_plane/domain/service.py).
// Deliberately no health/connection field -- see that module's own
// docstring for why. Every caller must render the ABSENCE of one as
// "not connected", never assume or display a fabricated healthy state.

export const SERVICE_KINDS = [
  "rest_api",
  "graphql_api",
  "microservice",
  "database",
  "queue_worker",
  "kubernetes_workload",
  "cloud_resource",
  "other",
] as const;
export type ServiceKind = (typeof SERVICE_KINDS)[number];

export const SERVICE_KIND_LABELS: Record<ServiceKind, string> = {
  rest_api: "REST API",
  graphql_api: "GraphQL API",
  microservice: "Microservice",
  database: "Database",
  queue_worker: "Queue / background worker",
  kubernetes_workload: "Kubernetes workload",
  cloud_resource: "Cloud resource",
  other: "Other",
};

export interface RegisteredService {
  id: string;
  organization_id: string;
  name: string;
  kind: ServiceKind;
  language: string | null;
  description: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface ServiceListResponse {
  items: RegisteredService[];
  total: number;
  limit: number;
  offset: number;
}

// Independent-review correction round, BLOCKER 2: mirrors
// control-plane's own core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES
// EXACTLY -- used only to decide whether to show/enable the
// "Register service" control, never as the actual authorization
// decision (control-plane re-enforces this unconditionally on every
// POST /api/v1/services regardless of what this list says).
export const ROLES_THAT_MAY_REGISTER_SERVICES = ["OWNER", "ADMIN", "ENGINEER"] as const;
