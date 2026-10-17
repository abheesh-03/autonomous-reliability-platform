package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/allowlist"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/controlplane"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

// ExecuteRequest is the ENTIRE request body this endpoint accepts
// (Phase 8 §NO CALLER-SUPPLIED EXECUTION TARGET): a bare proposal id,
// nothing else. Decoded with DisallowUnknownFields, so a caller
// attempting to also supply a URL, hostname, shell command, container
// id, Docker service name, or any other field is REJECTED with 400 --
// never silently ignored, and never accidentally honored.
type ExecuteRequest struct {
	ProposalID string `json:"proposal_id"`
}

// ExecuteResponse is the bounded, structured result -- never a raw
// HTTP response body, exception text, or secret.
type ExecuteResponse struct {
	ProposalID string `json:"proposal_id"`
	Status     string `json:"status"` // "succeeded" | "failed"
	Detail     string `json:"detail,omitempty"`
}

// ExecuteHandler backs POST /api/v1/remediation-actions/execute.
//
// The ENTIRE authorization decision is re-derived from control-plane
// on every call, independently of the caller (Phase 8 §TOOL-GATEWAY
// EXECUTION API): TOOL_GATEWAY_EXECUTION_TOKEN alone never authorizes
// the action -- a valid token merely lets a caller ASK; whether
// anything actually happens depends entirely on what control-plane's
// own durable proposal record says RIGHT NOW. A compromised or
// misbehaving agent-runtime-service holding a valid execution token
// cannot turn `pending_approval` into an executed action by itself.
func ExecuteHandler(cpClient *controlplane.Client, paymentClient *payment.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()

		decoder := json.NewDecoder(r.Body)
		decoder.DisallowUnknownFields()
		var req ExecuteRequest
		if err := decoder.Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "malformed request body (only proposal_id is accepted)")
			return
		}
		if req.ProposalID == "" {
			writeError(w, http.StatusBadRequest, "proposal_id is required")
			return
		}

		proposal, err := cpClient.GetProposal(ctx, req.ProposalID)
		switch {
		case errors.Is(err, controlplane.ErrUnavailable):
			writeError(w, http.StatusServiceUnavailable, "control-plane is temporarily unavailable; this request can be retried")
			return
		case errors.Is(err, controlplane.ErrNotFound):
			writeError(w, http.StatusNotFound, "remediation proposal not found")
			return
		case err != nil:
			writeError(w, http.StatusBadGateway, "control-plane returned an unexpected response")
			return
		}

		// Independently verify the allowlisted action/target -- never
		// trusts the caller's own belief about what this proposal is
		// for. Phase 8 has exactly one legal pair; anything else is
		// refused outright regardless of the proposal's status.
		if !allowlist.IsAllowed(proposal.ActionType, proposal.Target) {
			writeError(w, http.StatusConflict, "proposal action_type/target is not allowlisted")
			return
		}

		switch proposal.Status {
		case "pending_approval":
			writeError(w, http.StatusConflict, "proposal is not approved yet")
			return
		case "rejected":
			writeError(w, http.StatusConflict, "proposal was rejected")
			return
		case "succeeded":
			// Idempotent: already finished. Never calls payment-service
			// again, never records a second event (Phase 8
			// §TOOL-GATEWAY EXECUTION IDEMPOTENCY).
			writeJSON(w, http.StatusOK, ExecuteResponse{ProposalID: proposal.ID, Status: "succeeded"})
			return
		case "failed":
			// Terminal. Phase 8 defines no retry policy for an
			// already-failed proposal -- returning the EXISTING result
			// rather than attempting anything again.
			writeError(w, http.StatusConflict, "proposal already failed; no retry policy is defined for this phase")
			return
		case "approved", "executing":
			// Proceed -- see below. "executing" is the documented
			// crash-retry re-entry point: a PRIOR attempt already
			// called execution/start (and tool-gateway itself may have
			// crashed before recording a result) -- the SAME idempotent
			// action and verification are simply retried.
		default:
			writeError(w, http.StatusBadGateway, "control-plane reported an unexpected proposal status")
			return
		}

		started, err := cpClient.StartExecution(ctx, proposal.ID)
		switch {
		case errors.Is(err, controlplane.ErrUnavailable):
			writeError(w, http.StatusServiceUnavailable, "control-plane is temporarily unavailable; this request can be retried")
			return
		case err != nil:
			writeError(w, http.StatusBadGateway, "control-plane returned an unexpected response")
			return
		}
		switch started.Status {
		case "succeeded":
			writeJSON(w, http.StatusOK, ExecuteResponse{ProposalID: proposal.ID, Status: "succeeded"})
			return
		case "failed":
			writeError(w, http.StatusConflict, "proposal already failed; no retry policy is defined for this phase")
			return
		case "executing":
			// expected -- proceed to perform the action.
		default:
			writeError(w, http.StatusBadGateway, "control-plane reported an unexpected proposal status after execution/start")
			return
		}

		// Perform the ONE allowlisted, idempotent action.
		//
		// Phase 8 correction round (finding #1): a clear response that
		// is reachable but NOT a trusted 2xx shape
		// (payment.ErrUnexpectedResponse -- non-200 HTTP, malformed
		// JSON, or a response-contract failure) is NOT sufficient
		// evidence that the mutation failed. payment-service can
		// perform the real fault-clearing side effect and only
		// AFTERWARD produce a response that is lost, truncated, or
		// otherwise unexpected -- the exact same distributed-systems
		// ambiguity already fixed between agent-runtime-service and
		// this gateway. A confirmed-success clear (clearErr == nil)
		// and an ambiguous-response clear (clearErr ==
		// ErrUnexpectedResponse) therefore both fall through to the
		// SAME independent, FRESH post-action verification below --
		// the clear response itself is never trusted either way, and
		// clear is never called a second time within this request.
		_, _, clearErr := paymentClient.ClearAuthorizationFault(ctx)
		if errors.Is(clearErr, payment.ErrUnavailable) {
			// Genuinely transient -- payment-service could not be
			// reached at all. Nothing is recorded; the proposal stays
			// 'executing' and a retried execute() call will safely
			// retry the SAME idempotent action.
			writeError(w, http.StatusServiceUnavailable, "payment-service is temporarily unavailable; this request can be retried")
			return
		}

		// Independent post-action verification (Phase 8 §REAL
		// RECOVERY, extended by correction round finding #1): never
		// report success merely because the clear request itself
		// returned 2xx, and -- symmetrically -- never report failure
		// merely because the clear response (or either read below)
		// was ambiguous. Only a RELIABLE fresh read of both facts ever
		// decides the outcome; an unreliable read of EITHER one always
		// means "truly unknown right now", never "assume failure".
		active, activeErr := paymentClient.GetAuthorizationFaultStatus(ctx)
		if errors.Is(activeErr, payment.ErrUnavailable) {
			writeError(w, http.StatusServiceUnavailable, "payment-service is temporarily unavailable; this request can be retried")
			return
		}
		if activeErr != nil {
			// The fault-status read ITSELF was ambiguous -- genuinely
			// unknown whether the clear achieved its effect. Never
			// recorded as a failure: that would reintroduce the exact
			// false-failure risk this correction closes. Safe to
			// retry; nothing durable is written, and the proposal
			// stays 'executing'.
			writeError(w, http.StatusServiceUnavailable, "could not reliably verify the authorization fault's post-action state; this request can be retried")
			return
		}

		healthy, healthErr := paymentClient.HealthUp(ctx)
		if errors.Is(healthErr, payment.ErrUnavailable) {
			writeError(w, http.StatusServiceUnavailable, "payment-service is temporarily unavailable; this request can be retried")
			return
		}
		if healthErr != nil {
			writeError(w, http.StatusServiceUnavailable, "could not reliably verify payment-service's post-action health; this request can be retried")
			return
		}

		if active || !healthy {
			// A RELIABLE read confirms the mutation genuinely did not
			// achieve its required state (the fault is still active,
			// or payment-service itself is not healthy) -- a
			// definitive, terminal outcome, never a guess.
			recordFailureAndRespond(
				w, ctx, cpClient, proposal.ID,
				"post-clear verification failed: fault still reports active or payment-service is not healthy",
			)
			return
		}

		// CASE A (correction round, finding #1): the real side effect
		// genuinely occurred (fault now reliably inactive,
		// payment-service reliably healthy) -- true whether the clear
		// call itself reported success OR was merely ambiguous. Falls
		// through to the normal durable success-recording path below;
		// clear is never invoked again within this request.

		result, recordErr := cpClient.RecordExecutionResult(ctx, proposal.ID, "succeeded", "fault cleared and independently verified inactive; payment-service healthy")
		if errors.Is(recordErr, controlplane.ErrUnavailable) {
			// The real action succeeded and was verified, but the
			// durable record of that could not be written. Still
			// safe to retry: the proposal remains 'executing', and a
			// retried execute() call will repeat the (already
			// idempotent) clear+verify and try recording again.
			writeError(w, http.StatusServiceUnavailable, "control-plane is temporarily unavailable; this request can be retried")
			return
		}
		if recordErr != nil {
			writeError(w, http.StatusBadGateway, "control-plane returned an unexpected response")
			return
		}

		writeJSON(w, http.StatusOK, ExecuteResponse{ProposalID: result.ID, Status: result.Status})
	}
}

// recordFailureAndRespond is reached only when payment-service was
// genuinely REACHABLE but the action or its verification did not
// succeed -- a TERMINAL outcome (Phase 8 §HANDLE FAILED REMEDIATION
// INCIDENT STATE), as opposed to the TRANSIENT "could not even reach
// it" case handled separately above. Recording this also atomically
// rolls the owning incident back remediating -> investigating, on
// control-plane's own side (repositories/remediation_repository.py);
// tool-gateway has no incident-lifecycle credential of its own and
// never touches that table directly.
func recordFailureAndRespond(
	w http.ResponseWriter, ctx context.Context, cpClient *controlplane.Client, proposalID, detail string,
) {
	result, err := cpClient.RecordExecutionResult(ctx, proposalID, "failed", detail)
	if errors.Is(err, controlplane.ErrUnavailable) {
		writeError(w, http.StatusServiceUnavailable, "control-plane is temporarily unavailable; this request can be retried")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadGateway, "control-plane returned an unexpected response")
		return
	}
	writeJSON(w, http.StatusConflict, ExecuteResponse{ProposalID: result.ID, Status: result.Status, Detail: detail})
}
