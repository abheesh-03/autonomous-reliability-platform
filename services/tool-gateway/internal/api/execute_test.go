package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/controlplane"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

func newHarness(t *testing.T) (*fakeControlPlane, *httptest.Server, *fakePayment, *httptest.Server, http.HandlerFunc) {
	t.Helper()
	fcp := newFakeControlPlane()
	cpSrv := fcp.server()
	t.Cleanup(cpSrv.Close)

	fp := newFakePayment()
	paymentSrv := fp.server()
	t.Cleanup(paymentSrv.Close)

	cpClient := controlplane.New(cpSrv.URL, "executor-token", 5*time.Second)
	paymentClient := payment.New(paymentSrv.URL, "remediation-token", 5*time.Second)
	handler := ExecuteHandler(cpClient, paymentClient)
	return fcp, cpSrv, fp, paymentSrv, handler
}

func postExecute(handler http.HandlerFunc, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/remediation-actions/execute", strings.NewReader(body))
	rec := httptest.NewRecorder()
	handler(rec, req)
	return rec
}

func TestExecute_ApprovedProposalSucceeds(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.active = true
	fp.healthy = true

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var resp ExecuteResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Status != "succeeded" {
		t.Fatalf("expected status=succeeded, got %+v", resp)
	}
	if fcp.resultCalls != 1 || fcp.lastOutcome != "succeeded" {
		t.Fatalf("expected exactly one 'succeeded' execution result recorded, got calls=%d outcome=%s", fcp.resultCalls, fcp.lastOutcome)
	}
	if fp.clearCalls != 1 {
		t.Fatalf("expected exactly one clear call, got %d", fp.clearCalls)
	}
}

func TestExecute_PendingApprovalRefused(t *testing.T) {
	fcp, _, _, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "pending_approval", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", rec.Code)
	}
	if fcp.startCalls != 0 {
		t.Fatal("must never start execution for a proposal that is not approved")
	}
}

func TestExecute_RejectedProposalRefused(t *testing.T) {
	fcp, _, _, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "rejected", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", rec.Code)
	}
}

func TestExecute_WrongTargetRefused(t *testing.T) {
	fcp, _, _, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "some-other-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", rec.Code)
	}
	if fcp.startCalls != 0 {
		t.Fatal("must never start execution for a disallowed target")
	}
}

func TestExecute_UnknownActionRefused(t *testing.T) {
	fcp, _, _, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "restart_payment_service", Target: "payment-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", rec.Code)
	}
}

func TestExecute_ControlPlaneUnavailableReturns503(t *testing.T) {
	_, cpSrv, _, _, handler := newHarness(t)
	cpSrv.Close() // genuinely unreachable

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", rec.Code)
	}
}

func TestExecute_PaymentUnavailableReturns503AndRecordsNothing(t *testing.T) {
	fcp, _, _, paymentSrv, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	paymentSrv.Close() // genuinely unreachable

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", rec.Code)
	}
	if fcp.resultCalls != 0 {
		t.Fatal("a transient payment-service outage must never record a terminal execution result")
	}
	// The proposal must remain safely resumable -- still 'executing'
	// (start_execution already ran), never a fabricated terminal state.
	fcp.mu.Lock()
	status := fcp.proposals["p1"].Status
	fcp.mu.Unlock()
	if status != "executing" {
		t.Fatalf("expected proposal to remain 'executing' after a transient outage, got %q", status)
	}
}

func TestExecute_PaymentClearFailureRecordsFailureAndRollsBack(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.clearShouldFail = true

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.resultCalls != 1 || fcp.lastOutcome != "failed" {
		t.Fatalf("expected exactly one 'failed' execution result recorded, got calls=%d outcome=%s", fcp.resultCalls, fcp.lastOutcome)
	}
}

func TestExecute_PostClearVerificationFailureRecordsFailure(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	// The clear call itself succeeds at the transport level (2xx), but
	// payment-service's own health independently reports unhealthy --
	// never trusted as a real success merely because the HTTP clear
	// call returned 2xx (Phase 8 §REAL RECOVERY).
	fp.healthy = false

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.lastOutcome != "failed" {
		t.Fatalf("expected a 'failed' outcome recorded, got %q", fcp.lastOutcome)
	}
}

func TestExecute_SucceededProposalIsIdempotentAndNeverCallsPaymentAgain(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "succeeded", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var resp ExecuteResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Status != "succeeded" {
		t.Fatalf("expected cached succeeded result, got %+v", resp)
	}
	if fp.clearCalls != 0 {
		t.Fatal("an already-succeeded proposal must never call payment-service again")
	}
	if fcp.startCalls != 0 || fcp.resultCalls != 0 {
		t.Fatal("an already-succeeded proposal must never write a new start/result event")
	}
}

func TestExecute_FailedProposalReturnsExistingTerminalFailure(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "failed", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", rec.Code)
	}
	if fp.clearCalls != 0 {
		t.Fatal("an already-failed proposal must never call payment-service again (no retry policy in Phase 8)")
	}
}

func TestExecute_ExecutingProposalRetriesTheSameIdempotentAction(t *testing.T) {
	// Simulates the documented crash-retry scenario: a prior attempt
	// already moved the proposal to 'executing' (execution/start
	// succeeded) but the process crashed before a result was ever
	// recorded. A fresh execute() call must retry the SAME idempotent
	// action and complete it.
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "executing", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.active = true
	fp.healthy = true

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var resp ExecuteResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Status != "succeeded" {
		t.Fatalf("expected succeeded, got %+v", resp)
	}
}

func TestExecute_RepeatedExecutionAfterSuccessIsIdempotent(t *testing.T) {
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.active = true
	fp.healthy = true

	first := postExecute(handler, `{"proposal_id":"p1"}`)
	second := postExecute(handler, `{"proposal_id":"p1"}`)

	if first.Code != http.StatusOK || second.Code != http.StatusOK {
		t.Fatalf("expected both calls to succeed, got %d and %d", first.Code, second.Code)
	}
	if fp.clearCalls != 1 {
		t.Fatalf("expected exactly one real clear call across both requests, got %d", fp.clearCalls)
	}
	if fcp.resultCalls != 1 {
		t.Fatalf("expected exactly one recorded execution result across both requests, got %d", fcp.resultCalls)
	}
}

func TestExecute_ClearMutationSucceededButResponseAmbiguousStillRecordsSuccess(t *testing.T) {
	// Phase 8 correction round (finding #1), scenario A: the clear
	// call's own mutation genuinely occurred (active -> false) but its
	// OWN response was malformed -- never inferred as a failure. A
	// fresh, independent reconciliation read (status + health) proves
	// the real post-action state, and that decides the outcome.
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.active = true
	fp.healthy = true
	fp.clearMutatesButRespondsAmbiguously = true

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var resp ExecuteResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Status != "succeeded" {
		t.Fatalf("expected status=succeeded, got %+v", resp)
	}
	if fp.clearCalls != 1 {
		t.Fatalf("expected exactly one clear call (never retried within this request), got %d", fp.clearCalls)
	}
	if fcp.resultCalls != 1 || fcp.lastOutcome != "succeeded" {
		t.Fatalf("expected exactly one 'succeeded' execution result recorded, got calls=%d outcome=%s", fcp.resultCalls, fcp.lastOutcome)
	}
}

func TestExecute_ClearResponseAmbiguousAndActionDidNotOccurRecordsFailure(t *testing.T) {
	// Scenario B: the clear response is ambiguous (non-2xx, in this
	// fake), but the real mutation never actually happened -- a fresh
	// reconciliation read reliably confirms the fault is STILL active,
	// so this is a genuine, definitive failure.
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.active = true
	fp.healthy = true
	fp.clearShouldFail = true // 500, never touches fp.active

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.resultCalls != 1 || fcp.lastOutcome != "failed" {
		t.Fatalf("expected exactly one 'failed' execution result recorded, got calls=%d outcome=%s", fcp.resultCalls, fcp.lastOutcome)
	}
}

func TestExecute_ClearResponseAmbiguousAndReconciliationUnavailableReturns503WithoutRecording(t *testing.T) {
	// Scenario C: the clear response is ambiguous AND the fresh
	// reconciliation read (status) is itself unreliable (malformed) --
	// genuinely unknown either way. Must be a safe, retryable 503,
	// NEVER a recorded succeeded or failed outcome.
	fcp, _, fp, _, handler := newHarness(t)
	fcp.addProposal(&fakeProposal{ID: "p1", Status: "approved", ActionType: "clear_payment_authorization_fault", Target: "payment-service"})
	fp.clearShouldFail = true  // ambiguous clear response
	fp.statusShouldFail = true // reconciliation read is ALSO unreliable

	rec := postExecute(handler, `{"proposal_id":"p1"}`)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.resultCalls != 0 {
		t.Fatal("an unreliable reconciliation read must never record ANY terminal execution result")
	}
	fcp.mu.Lock()
	status := fcp.proposals["p1"].Status
	fcp.mu.Unlock()
	if status != "executing" {
		t.Fatalf("expected proposal to remain 'executing' when reconciliation itself is unreliable, got %q", status)
	}
}

func TestExecute_RejectsUnknownBodyFields(t *testing.T) {
	_, _, _, _, handler := newHarness(t)

	// Phase 8 §NO CALLER-SUPPLIED EXECUTION TARGET: any extra field
	// (a URL, in this case) must be REJECTED, never silently ignored.
	rec := postExecute(handler, `{"proposal_id":"p1","url":"http://evil.example/"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for an unknown field, got %d", rec.Code)
	}
}

func TestExecute_RequiresProposalID(t *testing.T) {
	_, _, _, _, handler := newHarness(t)

	rec := postExecute(handler, `{}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for a missing proposal_id, got %d", rec.Code)
	}
}

func TestExecute_UnknownProposalReturns404(t *testing.T) {
	_, _, _, _, handler := newHarness(t)

	rec := postExecute(handler, `{"proposal_id":"does-not-exist"}`)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
}
