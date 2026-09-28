package server

import (
	"net/http"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/api"
)

// New builds an http.Server with the service's routes registered and
// production-oriented timeouts. Using Go's method-specific ServeMux
// patterns (e.g. "GET /health") means any other HTTP method on that
// path is automatically rejected with 405 (with a correct Allow
// header), with no extra handler logic needed — that dispatch decision
// is made by ServeMux itself, before either registered handler below
// ever runs, so instrumentation does not change it.
//
// The whole mux is wrapped with otelhttp at this server boundary (not
// inside the business handlers in internal/api) to produce the SERVER
// span and HTTP server metrics. otelhttp (v0.71.0) re-derives the span
// name/route from the standard library's own matched ServeMux pattern
// (via *http.Request.Pattern, populated by ServeMux itself once the
// wrapped mux has dispatched the request) — no separate per-route
// route-tagging call is needed or available in this version.
func New(addr string) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", api.HealthHandler)
	mux.HandleFunc("POST /inventory/reservations", api.ReservationsHandler)

	handler := otelhttp.NewHandler(mux, "inventory-service")

	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}
