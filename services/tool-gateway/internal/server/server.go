package server

import (
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/api"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/config"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/controlplane"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

// New builds an http.Server with tool-gateway's small, fixed route
// set registered. Every route this service will ever have is listed
// HERE, explicitly -- there is no dynamic route registration, no
// generic catch-all handler, and no way for a request path alone to
// reach anything other than these three.
func New(settings config.Settings) *http.Server {
	cpClient := controlplane.New(settings.ControlPlaneBaseURL, settings.RemediationExecutorToken, settings.RequestTimeout)
	paymentClient := payment.New(settings.PaymentBaseURL, settings.PaymentRemediationToken, settings.RequestTimeout)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", api.HealthHandler)
	// Phase 8 correction round: the capability/precondition endpoint
	// requires TOOL_GATEWAY_EXECUTION_TOKEN too -- agent-runtime-service
	// already holds this token; it is never public/unauthenticated.
	mux.HandleFunc(
		"GET /api/v1/remediation-capabilities",
		api.RequireExecutionToken(settings.ExecutionToken, api.CapabilityHandler(paymentClient)),
	)
	mux.HandleFunc(
		"POST /api/v1/remediation-actions/execute",
		api.RequireExecutionToken(settings.ExecutionToken, api.ExecuteHandler(cpClient, paymentClient)),
	)

	return &http.Server{
		Addr:              settings.ListenAddr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}
