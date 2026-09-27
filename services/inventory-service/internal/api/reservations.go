package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/reservation"
)

// errorResponse is the one consistent JSON shape used for every request
// validation or internal error returned by this API.
type errorResponse struct {
	Error   string `json:"error"`
	Message string `json:"message"`
}

// ReservationsHandler handles POST /inventory/reservations: a simulated
// inventory reservation. It does not track stock, does not persist
// anything, and does not talk to any other service.
func ReservationsHandler(w http.ResponseWriter, r *http.Request) {
	var req reservation.Request
	if err := decodeStrictJSON(r.Body, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_request", "request body must be a single valid JSON object matching the reservation request shape")
		return
	}

	resp, err := reservation.Create(req)
	if err != nil {
		var verr *reservation.ValidationError
		if errors.As(err, &verr) {
			writeError(w, http.StatusBadRequest, "invalid_request", verr.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, "internal_error", "unable to create reservation")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(resp)
}

// decodeStrictJSON decodes exactly one JSON object from r into dst,
// rejecting unknown fields and any trailing data after the object. A
// second Decode is expected to fail with exactly io.EOF; anything else
// (a second value, or no error at all) means there was more than one
// top-level JSON value in the body.
func decodeStrictJSON(r io.Reader, dst any) error {
	dec := json.NewDecoder(r)
	dec.DisallowUnknownFields()

	if err := dec.Decode(dst); err != nil {
		return err
	}

	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("unexpected trailing data after JSON body")
	}

	return nil
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(errorResponse{Error: code, Message: message})
}
