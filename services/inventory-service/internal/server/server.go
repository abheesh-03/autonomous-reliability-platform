package server

import (
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/api"
)

// New builds an http.Server with only the /health route registered and
// production-oriented timeouts. Using Go's method-specific ServeMux
// pattern ("GET /health") means any other HTTP method on that path is
// automatically rejected with 405, with no extra handler logic needed.
func New(addr string) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", api.HealthHandler)

	return &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}
