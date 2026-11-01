// Phase 18: the explicit, narrow shape of the public recorded-demo
// snapshot. Deliberately NOT a reuse of lib/types/*'s live backend
// contracts (Incident, RegisteredService, IntegrationCredential, ...)
// -- those include fields (organization_id, created_by_user_id, a raw
// bearer_token on credential creation) that must never reach this
// public, unauthenticated bundle. Every field below is an explicit
// allowlist entry; anything not listed here was deliberately excluded
// when the real snapshot was captured (see lib/demo/snapshot.ts's own
// header and docs/demo-snapshot-provenance.md).

import type { IncidentSeverity, IncidentStatus, IncidentEventType, IncidentEventActorType } from "../types/incident";
import type {
  AgentRunStatus,
  ResultQuality,
  RemediationStatus,
  ExecutionResult,
  RecoveryVerification,
  InvestigationReport,
} from "../types/agent-run";
import type { RemediationProposalStatus, RemediationEventType, RemediationEventActorType } from "../types/remediation";
import type { ConnectionStatus } from "../types/telemetry";
import type { ServiceKind } from "../types/service";

export interface DemoProvenance {
  /** ISO 8601 date this snapshot's underlying data was captured. */
  captured_at: string;
  /** How the incident/investigation/remediation scenario was produced. */
  incident_scenario_source: string;
  /** How the telemetry scenario was produced -- a SEPARATE real capture. */
  telemetry_scenario_source: string;
  /** Always "stub" for this snapshot -- no live/paid LLM call was made. */
  investigator_provider: "stub";
}

export interface DemoIncident {
  id: string;
  title: string;
  description: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  source: string;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  created_at: string;
}

export interface DemoIncidentEvent {
  id: number;
  event_type: IncidentEventType;
  actor_type: IncidentEventActorType;
  previous_status: IncidentStatus | null;
  new_status: IncidentStatus;
  occurred_at: string;
}

export interface DemoAgentRun {
  run_id: string;
  status: AgentRunStatus;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  current_node: string;
  completed_nodes: string[];
  investigation_report: InvestigationReport;
  result_quality: ResultQuality | null;
  resumable: boolean;
  remediation_proposal_id: string;
  remediation_action_type: string;
  remediation_target: string;
  remediation_status: RemediationStatus;
  execution_result: ExecutionResult;
  recovery_verification: RecoveryVerification;
}

export interface DemoRemediationProposal {
  id: string;
  action_type: string;
  target: string;
  reason: string;
  status: RemediationProposalStatus;
  proposed_at: string;
  decided_at: string | null;
  decision_comment: string | null;
  execution_started_at: string | null;
  execution_completed_at: string | null;
}

export interface DemoRemediationEvent {
  id: number;
  event_type: RemediationEventType;
  actor_type: RemediationEventActorType;
  occurred_at: string;
}

export interface DemoIncidentScenario {
  incident: DemoIncident;
  events: DemoIncidentEvent[];
  agent_run: DemoAgentRun;
  remediation_proposal: DemoRemediationProposal;
  remediation_events: DemoRemediationEvent[];
}

export interface DemoService {
  id: string;
  name: string;
  kind: ServiceKind;
  language: string | null;
  description: string | null;
  created_at: string;
}

export interface DemoCredential {
  id: string;
  credential_id: string;
  status: "active" | "revoked";
  created_at: string;
  last_verified_telemetry_at: string | null;
}

export interface DemoTelemetrySummary {
  service_id: string;
  status: ConnectionStatus;
  window_minutes: number;
  request_count: number;
  error_count: number;
  request_rate_per_minute: number;
  error_rate: number | null;
  mean_latency_seconds: number | null;
  last_observed_at: string | null;
  generated_at: string;
}

export interface DemoTelemetryScenario {
  service: DemoService;
  credential: DemoCredential;
  summary: DemoTelemetrySummary;
}

export interface DemoDashboardCounts {
  open: number;
  acknowledged: number;
  investigating: number;
  remediating: number;
  resolved: number;
  closed: number;
  active_critical: number;
}

export interface DemoSnapshot {
  provenance: DemoProvenance;
  dashboard_counts: DemoDashboardCounts;
  incident_scenario: DemoIncidentScenario;
  telemetry_scenario: DemoTelemetryScenario;
}
