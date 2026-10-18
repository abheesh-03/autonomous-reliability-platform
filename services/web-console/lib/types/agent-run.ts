// Mirrors agent-runtime-service's REAL domain models exactly, re-audited
// directly against source for Stage 3 (never the prior Stage-9-audit
// notes alone):
//   services/agent-runtime-service/src/agent_runtime_service/domain/agent_run.py
//   services/agent-runtime-service/src/agent_runtime_service/domain/investigation.py
//   services/agent-runtime-service/src/agent_runtime_service/domain/incident_snapshot.py
//
// Two real discrepancies from a looser prior description, both
// confirmed directly in graph/nodes.py (where these two fields are
// actually populated, since the Pydantic model itself only declares
// them as a generic `dict | None`, never a structured sub-model):
//   - execution_result is ALWAYS exactly {status, detail} across every
//     code path that sets it (success, business-level refusal, and
//     every ambiguous-response-reconciliation branch).
//   - recovery_verification is ALWAYS exactly {proposal_succeeded,
//     fault_inactive, target_healthy} (three booleans), matching the
//     Phase 8 architecture doc's own description.
// A third discrepancy: `remediation_status` is typed as plain
// `str | None` in the real Pydantic model, NOT a `Literal` enum like
// `status` is -- the seven-value vocabulary below is a real, observed
// CONVENTION from graph/nodes.py (every value it ever actually sets),
// not something the backend's own schema enforces. This console still
// validates against it and fails closed on an unrecognized value,
// consistent with Stage 2's existing philosophy, but it is worth
// recording as a backend contract looseness, not a web-console
// invention.

import type { Incident, IncidentStatus } from "./incident";

export const AGENT_RUN_STATUSES = ["running", "waiting_for_approval", "completed", "failed"] as const;
export type AgentRunStatus = (typeof AGENT_RUN_STATUSES)[number];

export const RESULT_QUALITIES = ["well_supported", "inconclusive", "partial"] as const;
export type ResultQuality = (typeof RESULT_QUALITIES)[number];

// The real, observed convention (see module docstring above) -- NOT a
// backend-enforced Literal.
export const REMEDIATION_STATUSES = [
  "not_applicable",
  "pending_approval",
  "approved",
  "rejected",
  "succeeded",
  "failed",
] as const;
export type RemediationStatus = (typeof REMEDIATION_STATUSES)[number];

// The real, observed shape from graph/nodes.py's execute_remediation
// (and its ambiguous-response reconciliation branches) -- not a
// Pydantic-enforced sub-model on the backend.
export interface ExecutionResult {
  status: "succeeded" | "failed";
  detail: string | null;
}

// The real, observed shape from graph/nodes.py's verify_recovery --
// not a Pydantic-enforced sub-model on the backend.
export interface RecoveryVerification {
  proposal_succeeded: boolean;
  fault_inactive: boolean;
  target_healthy: boolean;
}

// --- Investigation report (mirrors investigator-service's real
// response contract, carried through unchanged -- domain/investigation.py) ---

export const EVIDENCE_SOURCES = ["control_plane", "prometheus", "loki", "tempo"] as const;
export type EvidenceSource = (typeof EVIDENCE_SOURCES)[number];

export const COLLECTION_STATUSES = ["ok", "partial", "no_data", "unavailable"] as const;
export type CollectionStatus = (typeof COLLECTION_STATUSES)[number];

export const RETRIEVAL_OUTCOMES = ["ok", "no_data", "unavailable"] as const;
export type RetrievalOutcome = (typeof RETRIEVAL_OUTCOMES)[number];

export const CONFIDENCE_LEVELS = ["low", "medium", "high"] as const;
export type ConfidenceLevel = (typeof CONFIDENCE_LEVELS)[number];

export const RETRIEVED_CONTEXT_SOURCE_TYPES = ["knowledge", "historical_incident"] as const;
export type RetrievedContextSourceType = (typeof RETRIEVED_CONTEXT_SOURCE_TYPES)[number];

export interface SourceOutcome {
  source: EvidenceSource;
  status: CollectionStatus;
  detail: string;
  query_summary: string | null;
}

export interface EvidenceItem {
  id: string;
  source: EvidenceSource;
  observed_at: string | null;
  window_start: string | null;
  window_end: string | null;
  summary: string;
  detail: string;
  reference: Record<string, string>;
}

export interface Observation {
  statement: string;
  evidence_ids: string[];
}

export interface Hypothesis {
  statement: string;
  supporting_evidence_ids: string[];
  conflicting_evidence_ids: string[];
  supporting_context_ids: string[];
  conflicting_context_ids: string[];
  confidence: ConfidenceLevel;
}

export interface MissingEvidence {
  description: string;
}

export interface SuggestedCheck {
  description: string;
  rationale: string;
}

export interface RetrievedContextItem {
  context_id: string;
  source_type: RetrievedContextSourceType;
  source_key: string;
  title: string;
  excerpt: string;
  similarity: number;
  metadata: Record<string, unknown>;
  embedding_space: string;
}

export interface RetrievalContext {
  knowledge: RetrievedContextItem[];
  historical_incidents: RetrievedContextItem[];
  outcome: RetrievalOutcome;
  detail: string;
}

export interface ProviderMetadata {
  configured: boolean;
  provider: string;
  model: string | null;
}

export interface InvestigationReport {
  incident_id: string;
  investigated_at: string;
  incident_status_at_investigation: IncidentStatus;
  summary: string;
  observations: Observation[];
  hypotheses: Hypothesis[];
  missing_evidence: MissingEvidence[];
  suggested_checks: SuggestedCheck[];
  evidence: EvidenceItem[];
  source_outcomes: SourceOutcome[];
  retrieval_context: RetrievalContext;
  provider: ProviderMetadata;
  validation_notes: string[];
}

// --- AgentRun / AgentRunHistory (domain/agent_run.py) ---

export interface AgentRun {
  run_id: string;
  thread_id: string;
  incident_id: string;
  status: AgentRunStatus;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  current_node: string;
  completed_nodes: string[];
  // Field-for-field identical to control-plane's own Incident shape
  // (confirmed against domain/incident_snapshot.py) -- reused rather
  // than duplicated.
  incident_snapshot: Incident | null;
  investigation_report: InvestigationReport | null;
  result_quality: ResultQuality | null;
  validation_notes: string[];
  error_code: string | null;
  error_detail: string | null;
  resumable: boolean;
  remediation_proposal_id: string | null;
  remediation_action_type: string | null;
  remediation_target: string | null;
  remediation_status: RemediationStatus | null;
  execution_result: ExecutionResult | null;
  recovery_verification: RecoveryVerification | null;
}

export interface AgentRunHistoryEntry {
  step: number;
  checkpoint_id: string;
  node: string;
  status_at_step: AgentRunStatus;
  created_at: string;
  next_nodes: string[];
}

export interface AgentRunHistory {
  run_id: string;
  thread_id: string;
  entries: AgentRunHistoryEntry[];
}
