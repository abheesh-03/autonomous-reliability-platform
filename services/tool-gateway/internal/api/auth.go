// Package api implements tool-gateway's small HTTP surface.
package api

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"strings"
)

// writeJSON writes a JSON body with the given status code. Errors
// from the encoder are deliberately ignored (the same convention
// inventory-service's own health handler already follows) -- by the
// time encoding could fail, the status line is already written and
// there is nothing more useful to do with the error.
func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

// RequireExecutionToken wraps a handler so it only runs for a request
// bearing TOOL_GATEWAY_EXECUTION_TOKEN. Guards BOTH
// POST /api/v1/remediation-actions/execute and the read-only
// GET /api/v1/remediation-capabilities precondition endpoint (Phase 8
// correction round: the precondition endpoint is not public -- only
// agent-runtime-service, which already holds this token, may call
// it). Fails closed: an unconfigured server-side token means
// authentication can never succeed. Uses constant-time comparison
// (crypto/subtle.ConstantTimeCompare) -- the same discipline
// control_plane.api.auth/payment_service.api.auth already apply with
// Python's hmac.compare_digest. The expected token value is never
// logged and never appears in any response.
func RequireExecutionToken(expectedToken string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if expectedToken == "" {
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}

		authHeader := r.Header.Get("Authorization")
		const prefix = "Bearer "
		if !strings.HasPrefix(authHeader, prefix) {
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		supplied := authHeader[len(prefix):]

		if len(supplied) != len(expectedToken) ||
			subtle.ConstantTimeCompare([]byte(supplied), []byte(expectedToken)) != 1 {
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}

		next(w, r)
	}
}
