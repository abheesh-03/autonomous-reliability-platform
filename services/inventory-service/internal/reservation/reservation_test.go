package reservation

import (
	"errors"
	"strings"
	"testing"
)

func validRequest() Request {
	return Request{
		CheckoutID: "chk_12345",
		SKU:        "sku_keyboard_001",
		Quantity:   2,
	}
}

func TestCreateSucceedsForValidRequest(t *testing.T) {
	req := validRequest()

	resp, err := Create(req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if resp.CheckoutID != req.CheckoutID {
		t.Errorf("expected checkout_id %q, got %q", req.CheckoutID, resp.CheckoutID)
	}
	if resp.SKU != req.SKU {
		t.Errorf("expected sku %q, got %q", req.SKU, resp.SKU)
	}
	if resp.Quantity != req.Quantity {
		t.Errorf("expected quantity %d, got %d", req.Quantity, resp.Quantity)
	}
	if resp.Status != statusReserved {
		t.Errorf("expected status %q, got %q", statusReserved, resp.Status)
	}
	if resp.ReservationID == "" {
		t.Error("expected a non-empty reservation_id")
	}
}

func TestCreateProducesDifferentIDsAcrossCalls(t *testing.T) {
	first, err := Create(validRequest())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	second, err := Create(validRequest())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if first.ReservationID == second.ReservationID {
		t.Fatalf("expected different reservation IDs, got the same value twice: %q", first.ReservationID)
	}
}

func TestValidateRejectsInvalidRequests(t *testing.T) {
	tests := []struct {
		name string
		req  Request
	}{
		{
			name: "zero quantity",
			req:  Request{CheckoutID: "chk_12345", SKU: "sku_keyboard_001", Quantity: 0},
		},
		{
			name: "negative quantity",
			req:  Request{CheckoutID: "chk_12345", SKU: "sku_keyboard_001", Quantity: -1},
		},
		{
			name: "empty checkout_id",
			req:  Request{CheckoutID: "", SKU: "sku_keyboard_001", Quantity: 1},
		},
		{
			name: "empty sku",
			req:  Request{CheckoutID: "chk_12345", SKU: "", Quantity: 1},
		},
		{
			name: "checkout_id too long",
			req:  Request{CheckoutID: strings.Repeat("a", 101), SKU: "sku_keyboard_001", Quantity: 1},
		},
		{
			name: "sku too long",
			req:  Request{CheckoutID: "chk_12345", SKU: strings.Repeat("a", 101), Quantity: 1},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.req.Validate()
			if err == nil {
				t.Fatal("expected a validation error, got nil")
			}

			var verr *ValidationError
			if !errors.As(err, &verr) {
				t.Fatalf("expected a *ValidationError, got %T: %v", err, err)
			}
		})
	}
}
