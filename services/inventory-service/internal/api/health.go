package api

import (
	"encoding/json"
	"net/http"
)

// ServiceName is reported in the health response body.
const ServiceName = "inventory-service"

// HealthResponse is the typed JSON body returned by HealthHandler.
type HealthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}

// HealthHandler reports that the service process is up. It does not
// check any downstream dependency, since this service has none yet.
func HealthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	_ = json.NewEncoder(w).Encode(HealthResponse{
		Status:  "UP",
		Service: ServiceName,
	})
}
