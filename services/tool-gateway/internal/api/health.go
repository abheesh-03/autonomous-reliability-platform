package api

import "net/http"

const ServiceName = "tool-gateway"

type HealthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}

// HealthHandler reports that the process is up. It does not check
// any downstream dependency (control-plane/payment-service
// reachability is reported, if at all, through
// GET /api/v1/remediation-capabilities instead) -- same convention
// inventory-service's own liveness-only /health already follows: this
// service has no database of its own and no persistent state to be
// "ready" about.
func HealthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "UP", Service: ServiceName})
}
