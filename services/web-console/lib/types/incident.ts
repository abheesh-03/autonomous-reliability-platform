// Mirrors control-plane's real Incident/IncidentEvent contracts exactly
// (services/control-plane/src/control_plane/domain/incident.py,
// domain/incident_event.py) -- never a field this console invented.

export const INCIDENT_SEVERITIES = ["critical", "warning", "info"] as const;
export type IncidentSeverity = (typeof INCIDENT_SEVERITIES)[number];

export const INCIDENT_STATUSES = [
  "open",
  "acknowledged",
  "investigating",
  "remediating",
  "resolved",
  "closed",
] as const;
export type IncidentStatus = (typeof INCIDENT_STATUSES)[number];

export interface Incident {
  id: string;
  // Phase 14: see control_plane/domain/incident.py.
  organization_id: string;
  source: string;
  source_fingerprint: string;
  title: string;
  description: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentListResponse {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
}

export const INCIDENT_EVENT_TYPES = [
  "created",
  "observed",
  "status_transition",
] as const;
export type IncidentEventType = (typeof INCIDENT_EVENT_TYPES)[number];

export const INCIDENT_EVENT_ACTOR_TYPES = ["alertmanager", "operator", "kubernetes", "aws", "otel-telemetry"] as const;
export type IncidentEventActorType = (typeof INCIDENT_EVENT_ACTOR_TYPES)[number];

export interface IncidentEvent {
  id: number;
  incident_id: string;
  event_type: IncidentEventType;
  actor_type: IncidentEventActorType;
  previous_status: IncidentStatus | null;
  new_status: IncidentStatus;
  occurred_at: string;
  metadata: Record<string, unknown>;
}

export interface IncidentEventListResponse {
  items: IncidentEvent[];
  total: number;
  limit: number;
  offset: number;
}
