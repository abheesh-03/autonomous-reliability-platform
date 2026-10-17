package api

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/allowlist"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

// CapabilityResponse reports the ONE allowlisted action, whether its
// deterministic precondition currently holds, AND (Phase 8 correction
// round, finding #2) payment-service's own current, independently
// re-checked health -- never a secret, never a raw payment-service
// response. `TargetHealthy` is what lets agent-runtime-service's
// verify_recovery node independently re-derive REAL recovery from a
// FRESH read, rather than merely trusting execute_remediation's own
// synchronous result.
type CapabilityResponse struct {
	ActionType      string `json:"action_type"`
	Target          string `json:"target"`
	PreconditionMet bool   `json:"precondition_met"`
	TargetHealthy   bool   `json:"target_healthy"`
}

// CapabilityHandler backs GET /api/v1/remediation-capabilities --
// agent-runtime-service's own deterministic action policy
// (propose_remediation) calls this to check whether the controlled
// payment authorization fault is actually active BEFORE ever
// creating a proposal (Phase 8 §DETERMINISTIC ACTION POLICY). Guarded
// by TOOL_GATEWAY_EXECUTION_TOKEN (Phase 8 correction round: NOT a
// public/unauthenticated endpoint) -- see server.go's own route
// registration. This endpoint can never be used to bypass approval:
// it reports a precondition only, never a decision, and
// POST /api/v1/remediation-actions/execute always independently
// re-verifies the real control-plane proposal state regardless of
// what this endpoint ever reported.
func CapabilityHandler(paymentClient *payment.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()

		active, err := paymentClient.GetAuthorizationFaultStatus(ctx)
		switch {
		case errors.Is(err, payment.ErrUnavailable):
			writeError(w, http.StatusServiceUnavailable, "payment-service is temporarily unavailable")
			return
		case err != nil:
			writeError(w, http.StatusBadGateway, "payment-service returned an unexpected response")
			return
		}

		// Phase 8 correction round (finding #2): an independent,
		// FRESH health re-check every call -- never cached, never
		// inferred from a prior execute() outcome.
		healthy, healthErr := paymentClient.HealthUp(ctx)
		switch {
		case errors.Is(healthErr, payment.ErrUnavailable):
			writeError(w, http.StatusServiceUnavailable, "payment-service is temporarily unavailable")
			return
		case healthErr != nil:
			writeError(w, http.StatusBadGateway, "payment-service returned an unexpected response")
			return
		}

		writeJSON(w, http.StatusOK, CapabilityResponse{
			ActionType:      allowlist.ActionClearPaymentAuthorizationFault,
			Target:          allowlist.TargetPaymentService,
			PreconditionMet: active,
			TargetHealthy:   healthy,
		})
	}
}
