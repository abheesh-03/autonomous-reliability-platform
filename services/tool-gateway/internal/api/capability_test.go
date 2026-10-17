package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

func TestCapabilityHandler_ReportsPreconditionFromPayment(t *testing.T) {
	fp := newFakePayment()
	fp.active = true
	fp.healthy = true
	srv := fp.server()
	defer srv.Close()

	client := payment.New(srv.URL, "remediation-token", 5*time.Second)
	handler := CapabilityHandler(client)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var body CapabilityResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if body.ActionType != "clear_payment_authorization_fault" || body.Target != "payment-service" {
		t.Fatalf("unexpected action/target: %+v", body)
	}
	if !body.PreconditionMet {
		t.Fatal("expected precondition_met=true when the fault is active")
	}
	if !body.TargetHealthy {
		t.Fatal("expected target_healthy=true when payment-service reports healthy")
	}
}

func TestCapabilityHandler_ReportsUnhealthyTargetIndependently(t *testing.T) {
	// Phase 8 correction round (finding #2): target_healthy is an
	// INDEPENDENT fresh health re-check, not derived from the fault
	// precondition -- a fault-inactive but unhealthy payment-service
	// must still be reported as unhealthy.
	fp := newFakePayment()
	fp.active = false
	fp.healthy = false
	srv := fp.server()
	defer srv.Close()

	client := payment.New(srv.URL, "remediation-token", 5*time.Second)
	handler := CapabilityHandler(client)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var body CapabilityResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	if body.TargetHealthy {
		t.Fatal("expected target_healthy=false when payment-service reports unhealthy")
	}
}

func TestCapabilityHandler_ReportsFalseWhenFaultInactive(t *testing.T) {
	fp := newFakePayment()
	fp.active = false
	srv := fp.server()
	defer srv.Close()

	client := payment.New(srv.URL, "remediation-token", 5*time.Second)
	handler := CapabilityHandler(client)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	var body CapabilityResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	if body.PreconditionMet {
		t.Fatal("expected precondition_met=false when the fault is inactive")
	}
}

func TestCapabilityHandler_PaymentUnavailableReturns503(t *testing.T) {
	fp := newFakePayment()
	srv := fp.server()
	srv.Close() // genuinely unreachable -- connection refused

	client := payment.New(srv.URL, "remediation-token", 2*time.Second)
	handler := CapabilityHandler(client)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", rec.Code)
	}
}
