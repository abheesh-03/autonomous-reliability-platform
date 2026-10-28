// Mirrors control-plane's real response contract exactly
// (services/control-plane/src/control_plane/domain/dashboard.py).
// Every field is sourced from a real, bounded, organization-scoped SQL
// query -- see that service's repositories/dashboard_repository.py.

import type { Incident, IncidentSeverity } from "./incident";

export interface StatusCounts {
  open: number;
  acknowledged: number;
  investigating: number;
  remediating: number;
  resolved: number;
  closed: number;
  active_critical: number;
}

export interface AttentionIncident {
  id: string;
  title: string;
  severity: IncidentSeverity;
  status: Incident["status"];
  source: string;
  last_seen_at: string;
}

export interface PendingApproval {
  proposal_id: string;
  incident_id: string;
  agent_run_id: string;
  incident_title: string;
  incident_severity: IncidentSeverity;
  action_type: string;
  target: string;
  proposed_at: string;
}

export interface ActivityPoint {
  day: string;
  critical: number;
  warning: number;
  info: number;
}

export interface RecentEvent {
  id: number;
  incident_id: string;
  incident_title: string;
  incident_severity: IncidentSeverity;
  event_type: string;
  actor_type: string;
  previous_status: string | null;
  new_status: string;
  occurred_at: string;
}

export interface DashboardSummary {
  generated_at: string;
  counts: StatusCounts;
  // Independent-review correction round, BLOCKER 3 bug B: a real,
  // unbounded count -- NEVER derive this from pending_approvals.length,
  // which is capped at 8 for display purposes by the backend.
  pending_approvals_count: number;
  attention_incidents: AttentionIncident[];
  pending_approvals: PendingApproval[];
  activity: ActivityPoint[];
  recent_events: RecentEvent[];
}
