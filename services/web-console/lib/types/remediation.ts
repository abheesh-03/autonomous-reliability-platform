// Mirrors control-plane's real RemediationProposal/RemediationEvent
// contracts exactly (services/control-plane/src/control_plane/domain/remediation.py)
// -- read-only in Stage 2; no approve/reject fields are used here.

export const REMEDIATION_PROPOSAL_STATUSES = [
  "pending_approval",
  "approved",
  "rejected",
  "executing",
  "succeeded",
  "failed",
] as const;
export type RemediationProposalStatus =
  (typeof REMEDIATION_PROPOSAL_STATUSES)[number];

export interface RemediationProposal {
  id: string;
  incident_id: string;
  agent_run_id: string;
  idempotency_key: string;
  action_type: string;
  target: string;
  reason: string;
  supporting_evidence_ids: string[];
  supporting_context_ids: string[];
  status: RemediationProposalStatus;
  proposed_at: string;
  updated_at: string;
  decided_at: string | null;
  decision_comment: string | null;
  execution_started_at: string | null;
  execution_completed_at: string | null;
}

export interface RemediationProposalListResponse {
  items: RemediationProposal[];
  total: number;
  limit: number;
  offset: number;
}

export const REMEDIATION_EVENT_TYPES = [
  "proposed",
  "approved",
  "rejected",
  "execution_started",
  "execution_succeeded",
  "execution_failed",
] as const;
export type RemediationEventType = (typeof REMEDIATION_EVENT_TYPES)[number];

export const REMEDIATION_EVENT_ACTOR_TYPES = [
  "agent",
  "operator",
  "executor",
] as const;
export type RemediationEventActorType =
  (typeof REMEDIATION_EVENT_ACTOR_TYPES)[number];

export interface RemediationEvent {
  id: number;
  proposal_id: string;
  event_type: RemediationEventType;
  actor_type: RemediationEventActorType;
  occurred_at: string;
  metadata: Record<string, unknown>;
}

export interface RemediationEventListResponse {
  items: RemediationEvent[];
  total: number;
  limit: number;
  offset: number;
}
