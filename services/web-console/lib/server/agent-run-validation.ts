import "server-only";

import { INCIDENT_SEVERITIES, INCIDENT_STATUSES } from "../types/incident";
import {
  AGENT_RUN_STATUSES,
  COLLECTION_STATUSES,
  CONFIDENCE_LEVELS,
  EVIDENCE_SOURCES,
  RESULT_QUALITIES,
  RETRIEVAL_OUTCOMES,
  RETRIEVED_CONTEXT_SOURCE_TYPES,
  REMEDIATION_STATUSES,
  type AgentRun,
  type AgentRunHistory,
  type AgentRunHistoryEntry,
  type EvidenceItem,
  type ExecutionResult,
  type Hypothesis,
  type InvestigationReport,
  type MissingEvidence,
  type Observation,
  type RecoveryVerification,
  type RetrievalContext,
  type RetrievedContextItem,
  type SourceOutcome,
  type SuggestedCheck,
} from "../types/agent-run";
import type { Incident } from "../types/incident";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value);
}

// Deliberately NOT a full re-validation of control-plane's own
// Incident contract (Stage 2 already validates that independently
// when the incident is fetched directly) -- just enough to fail
// closed on an obviously wrong incident_snapshot rather than trusting
// arbitrary JSON into the page.
function isIncidentSnapshot(value: unknown): value is Incident {
  if (!isRecord(value)) return false;
  return (
    isString(value.id) &&
    isString(value.source) &&
    isString(value.source_fingerprint) &&
    isString(value.title) &&
    isNullableString(value.description) &&
    isOneOf(value.severity, INCIDENT_SEVERITIES) &&
    isOneOf(value.status, INCIDENT_STATUSES) &&
    isString(value.first_seen_at) &&
    isString(value.last_seen_at) &&
    isNullableString(value.resolved_at) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isObservation(value: unknown): value is Observation {
  return isRecord(value) && isString(value.statement) && isStringArray(value.evidence_ids);
}

function isHypothesis(value: unknown): value is Hypothesis {
  return (
    isRecord(value) &&
    isString(value.statement) &&
    isStringArray(value.supporting_evidence_ids) &&
    isStringArray(value.conflicting_evidence_ids) &&
    isStringArray(value.supporting_context_ids) &&
    isStringArray(value.conflicting_context_ids) &&
    isOneOf(value.confidence, CONFIDENCE_LEVELS)
  );
}

function isMissingEvidence(value: unknown): value is MissingEvidence {
  return isRecord(value) && isString(value.description);
}

function isSuggestedCheck(value: unknown): value is SuggestedCheck {
  return isRecord(value) && isString(value.description) && isString(value.rationale);
}

function isEvidenceItem(value: unknown): value is EvidenceItem {
  if (!isRecord(value)) return false;
  return (
    isString(value.id) &&
    isOneOf(value.source, EVIDENCE_SOURCES) &&
    isNullableString(value.observed_at) &&
    isNullableString(value.window_start) &&
    isNullableString(value.window_end) &&
    isString(value.summary) &&
    isString(value.detail) &&
    isRecord(value.reference)
  );
}

function isSourceOutcome(value: unknown): value is SourceOutcome {
  if (!isRecord(value)) return false;
  return (
    isOneOf(value.source, EVIDENCE_SOURCES) &&
    isOneOf(value.status, COLLECTION_STATUSES) &&
    isString(value.detail) &&
    isNullableString(value.query_summary)
  );
}

function isRetrievedContextItem(value: unknown): value is RetrievedContextItem {
  if (!isRecord(value)) return false;
  return (
    isString(value.context_id) &&
    isOneOf(value.source_type, RETRIEVED_CONTEXT_SOURCE_TYPES) &&
    isString(value.source_key) &&
    isString(value.title) &&
    isString(value.excerpt) &&
    typeof value.similarity === "number" &&
    isRecord(value.metadata) &&
    isString(value.embedding_space)
  );
}

function isRetrievalContext(value: unknown): value is RetrievalContext {
  if (!isRecord(value)) return false;
  return (
    Array.isArray(value.knowledge) &&
    value.knowledge.every(isRetrievedContextItem) &&
    Array.isArray(value.historical_incidents) &&
    value.historical_incidents.every(isRetrievedContextItem) &&
    isOneOf(value.outcome, RETRIEVAL_OUTCOMES) &&
    isString(value.detail)
  );
}

function isInvestigationReport(value: unknown): value is InvestigationReport {
  if (!isRecord(value)) return false;
  if (
    !isString(value.incident_id) ||
    !isString(value.investigated_at) ||
    !isOneOf(value.incident_status_at_investigation, INCIDENT_STATUSES) ||
    !isString(value.summary) ||
    !Array.isArray(value.observations) ||
    !value.observations.every(isObservation) ||
    !Array.isArray(value.hypotheses) ||
    !value.hypotheses.every(isHypothesis) ||
    !Array.isArray(value.missing_evidence) ||
    !value.missing_evidence.every(isMissingEvidence) ||
    !Array.isArray(value.suggested_checks) ||
    !value.suggested_checks.every(isSuggestedCheck) ||
    !Array.isArray(value.evidence) ||
    !value.evidence.every(isEvidenceItem) ||
    !Array.isArray(value.source_outcomes) ||
    !value.source_outcomes.every(isSourceOutcome) ||
    !isRetrievalContext(value.retrieval_context) ||
    !isRecord(value.provider) ||
    !isStringArray(value.validation_notes)
  ) {
    return false;
  }
  const provider = value.provider;
  return (
    typeof provider.configured === "boolean" &&
    isString(provider.provider) &&
    isNullableString(provider.model ?? null)
  );
}

function isExecutionResult(value: unknown): value is ExecutionResult {
  if (!isRecord(value)) return false;
  return (value.status === "succeeded" || value.status === "failed") && isNullableString(value.detail);
}

function isRecoveryVerification(value: unknown): value is RecoveryVerification {
  if (!isRecord(value)) return false;
  return (
    typeof value.proposal_succeeded === "boolean" &&
    typeof value.fault_inactive === "boolean" &&
    typeof value.target_healthy === "boolean"
  );
}

/**
 * Validates enough of agent-runtime-service's real AgentRun response
 * shape to fail safely instead of blindly casting arbitrary JSON --
 * the core/discriminating fields strictly, every optional nested
 * structure either absent (null) or fully shape-checked. Returns null
 * on ANY structural problem; the caller maps that to a "malformed"
 * BackendResult, never a partially-trusted object.
 */
export function parseAgentRun(body: unknown): AgentRun | null {
  if (!isRecord(body)) return null;

  if (
    !isString(body.run_id) ||
    !isString(body.thread_id) ||
    !isString(body.incident_id) ||
    !isOneOf(body.status, AGENT_RUN_STATUSES) ||
    !isString(body.started_at) ||
    !isString(body.updated_at) ||
    !isNullableString(body.completed_at) ||
    !isString(body.current_node) ||
    !isStringArray(body.completed_nodes) ||
    !isStringArray(body.validation_notes) ||
    !isNullableString(body.error_code) ||
    !isNullableString(body.error_detail) ||
    typeof body.resumable !== "boolean" ||
    !isNullableString(body.remediation_proposal_id) ||
    !isNullableString(body.remediation_action_type) ||
    !isNullableString(body.remediation_target)
  ) {
    return null;
  }

  if (body.result_quality !== null && !isOneOf(body.result_quality, RESULT_QUALITIES)) {
    return null;
  }
  if (body.remediation_status !== null && !isOneOf(body.remediation_status, REMEDIATION_STATUSES)) {
    return null;
  }
  if (body.incident_snapshot !== null && !isIncidentSnapshot(body.incident_snapshot)) {
    return null;
  }
  if (body.investigation_report !== null && !isInvestigationReport(body.investigation_report)) {
    return null;
  }
  if (body.execution_result !== null && !isExecutionResult(body.execution_result)) {
    return null;
  }
  if (body.recovery_verification !== null && !isRecoveryVerification(body.recovery_verification)) {
    return null;
  }

  return body as unknown as AgentRun;
}

function isAgentRunHistoryEntry(value: unknown): value is AgentRunHistoryEntry {
  if (!isRecord(value)) return false;
  return (
    typeof value.step === "number" &&
    isString(value.checkpoint_id) &&
    isString(value.node) &&
    isOneOf(value.status_at_step, AGENT_RUN_STATUSES) &&
    isString(value.created_at) &&
    isStringArray(value.next_nodes)
  );
}

/**
 * Same fail-safe philosophy as parseAgentRun: every history entry
 * must fully match the real backend shape, or the whole response is
 * treated as malformed -- never a page silently rendering some
 * entries and dropping others.
 */
export function parseAgentRunHistory(body: unknown): AgentRunHistory | null {
  if (!isRecord(body)) return null;
  if (!isString(body.run_id) || !isString(body.thread_id) || !Array.isArray(body.entries)) {
    return null;
  }
  if (!body.entries.every(isAgentRunHistoryEntry)) {
    return null;
  }
  return body as unknown as AgentRunHistory;
}
