package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
)

var v4Pattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func postReservation(t *testing.T, body string) *httptest.ResponseRecorder {
	t.Helper()

	req := httptest.NewRequest(http.MethodPost, "/inventory/reservations", strings.NewReader(body))
	rec := httptest.NewRecorder()

	ReservationsHandler(rec, req)

	return rec
}

func TestReservationsHandlerSucceedsForValidRequest(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":2}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d: %s", http.StatusOK, rec.Code, rec.Body.String())
	}

	if contentType := rec.Header().Get("Content-Type"); contentType != "application/json" {
		t.Fatalf("expected Content-Type application/json, got %q", contentType)
	}

	var body struct {
		ReservationID string `json:"reservation_id"`
		CheckoutID    string `json:"checkout_id"`
		SKU           string `json:"sku"`
		Quantity      int    `json:"quantity"`
		Status        string `json:"status"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode response body: %v", err)
	}

	if body.CheckoutID != "chk_12345" {
		t.Errorf("expected checkout_id %q, got %q", "chk_12345", body.CheckoutID)
	}
	if body.SKU != "sku_keyboard_001" {
		t.Errorf("expected sku %q, got %q", "sku_keyboard_001", body.SKU)
	}
	if body.Quantity != 2 {
		t.Errorf("expected quantity 2, got %d", body.Quantity)
	}
	if body.Status != "RESERVED" {
		t.Errorf("expected status %q, got %q", "RESERVED", body.Status)
	}
	if !v4Pattern.MatchString(body.ReservationID) {
		t.Errorf("expected reservation_id to be a structurally valid UUID v4, got %q", body.ReservationID)
	}
}

func TestReservationsHandlerRejectsZeroQuantity(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":0}`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsNegativeQuantity(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":-1}`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsEmptyCheckoutID(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"","sku":"sku_keyboard_001","quantity":1}`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsEmptySKU(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"chk_12345","sku":"","quantity":1}`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsMalformedJSON(t *testing.T) {
	rec := postReservation(t, `{"checkout_id": "chk_12345",`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsUnknownField(t *testing.T) {
	rec := postReservation(t, `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":2,"unexpected":true}`)
	assertInvalidRequest(t, rec)
}

func TestReservationsHandlerRejectsTrailingJSON(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{
			name: "second top-level object",
			body: `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":2}{"checkout_id":"chk_999","sku":"sku_mouse_002","quantity":1}`,
		},
		{
			name: "trailing primitive",
			body: `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":2} true`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := postReservation(t, tt.body)
			assertInvalidRequest(t, rec)
		})
	}
}

func TestReservationsRouteRejectsWrongMethod(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /inventory/reservations", ReservationsHandler)

	req := httptest.NewRequest(http.MethodGet, "/inventory/reservations", nil)
	rec := httptest.NewRecorder()

	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected status %d, got %d", http.StatusMethodNotAllowed, rec.Code)
	}

	allow := rec.Header().Get("Allow")
	if !strings.Contains(allow, "POST") {
		t.Errorf("expected Allow header to contain POST, got %q", allow)
	}
}

func TestReservationsHandlerProducesDifferentIDsAcrossCalls(t *testing.T) {
	body := `{"checkout_id":"chk_12345","sku":"sku_keyboard_001","quantity":2}`

	first := postReservation(t, body)
	second := postReservation(t, body)

	var firstBody, secondBody struct {
		ReservationID string `json:"reservation_id"`
	}
	if err := json.NewDecoder(first.Body).Decode(&firstBody); err != nil {
		t.Fatalf("failed to decode first response body: %v", err)
	}
	if err := json.NewDecoder(second.Body).Decode(&secondBody); err != nil {
		t.Fatalf("failed to decode second response body: %v", err)
	}

	if firstBody.ReservationID == secondBody.ReservationID {
		t.Fatalf("expected different reservation IDs, got the same value twice: %q", firstBody.ReservationID)
	}
}

func assertInvalidRequest(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected status %d, got %d: %s", http.StatusBadRequest, rec.Code, rec.Body.String())
	}

	var body errorResponse
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode error response body: %v", err)
	}

	if body.Error != "invalid_request" {
		t.Errorf("expected error code %q, got %q", "invalid_request", body.Error)
	}
	if body.Message == "" {
		t.Error("expected a non-empty error message")
	}
}
