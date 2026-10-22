package server

import (
	"log"
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/api"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/config"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/controlplane"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/kubernetes"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/payment"
)

// New builds an http.Server with tool-gateway's small, fixed route
// set registered. Every route this service will ever have is listed
// HERE, explicitly -- there is no dynamic route registration, no
// generic catch-all handler, and no way for a request path alone to
// reach anything other than these.
func New(settings config.Settings) *http.Server {
	cpClient := controlplane.New(settings.ControlPlaneBaseURL, settings.RemediationExecutorToken, settings.RequestTimeout)
	paymentClient := payment.New(settings.PaymentBaseURL, settings.PaymentRemediationToken, settings.RequestTimeout)

	// Phase 12B-D: the Kubernetes executor is OPTIONAL -- a deployment
	// with no TOOL_GATEWAY_KUBERNETES_API_SERVER_URL configured at all
	// simply never constructs one, and the Kubernetes action/capability
	// routes fail closed (503 "not configured") rather than the
	// process refusing to start. KubernetesExecutionEnabled defaults
	// to false regardless (DRY-RUN) -- see config.go's own docstring.
	var k8sClient *kubernetes.Client
	var k8sExecutor *kubernetes.Executor
	if settings.KubernetesAPIServerURL != "" {
		// Issue 5: fail closed unless the claimed namespace/cluster
		// identity EXACTLY matches the one authorized sandbox -- never
		// trust a configuration label alone. Checked BEFORE ever
		// constructing a client, so a misconfigured namespace/cluster
		// name can never even attempt a connection.
		if err := kubernetes.ValidateSandboxIdentity(settings.KubernetesNamespace, settings.KubernetesClusterName); err != nil {
			log.Printf("kubernetes executor not constructed (routes will report 503): %v", err)
		} else {
			creds := kubernetes.ExecutorCredentials{
				APIServerURL:  settings.KubernetesAPIServerURL,
				CACertPEM:     []byte(settings.KubernetesCACertPEM),
				ClientCertPEM: []byte(settings.KubernetesClientCertPEM),
				ClientKeyPEM:  []byte(settings.KubernetesClientKeyPEM),
				BearerToken:   settings.KubernetesBearerToken,
			}
			var err error
			k8sClient, err = kubernetes.New(creds, settings.KubernetesNamespace, settings.RequestTimeout)
			if err != nil {
				// Fail closed for the Kubernetes routes only -- never
				// crash the whole process over a malformed Kubernetes
				// credential; the payment remediation path (and every
				// read-only route) must keep working regardless.
				log.Printf("kubernetes executor not constructed (routes will report 503): %v", err)
				k8sClient = nil
			} else {
				k8sExecutor = kubernetes.NewExecutor(k8sClient, settings.KubernetesExecutionEnabled, settings.KubernetesPollInterval, settings.KubernetesPollDeadline)
			}
		}
	}

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
		"GET /api/v1/remediation-capabilities/kubernetes",
		api.RequireExecutionToken(settings.ExecutionToken, api.KubernetesCapabilityHandler(k8sExecutor, k8sClient)),
	)
	mux.HandleFunc(
		"POST /api/v1/remediation-actions/execute",
		api.RequireExecutionToken(settings.ExecutionToken, api.ExecuteHandler(cpClient, paymentClient, k8sExecutor)),
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
