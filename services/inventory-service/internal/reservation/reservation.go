// Package reservation implements the business behavior behind a
// simulated inventory reservation: request validation and reservation
// creation. It has no knowledge of HTTP — that lives in internal/api.
package reservation

import (
	"fmt"

	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/uuid"
)

const (
	maxCheckoutIDLength = 100
	maxSKULength        = 100
	statusReserved      = "RESERVED"
)

// ValidationError indicates the request failed a business validation
// rule, as opposed to an internal error. Its message is safe to return
// to the client directly.
type ValidationError struct {
	msg string
}

func (e *ValidationError) Error() string { return e.msg }

func validationErrorf(format string, args ...any) error {
	return &ValidationError{msg: fmt.Sprintf(format, args...)}
}

// Request is the domain shape of a reservation request.
type Request struct {
	CheckoutID string `json:"checkout_id"`
	SKU        string `json:"sku"`
	Quantity   int    `json:"quantity"`
}

// Response is the domain shape of a successful reservation. No stock is
// tracked and nothing is persisted — this is a simulated reservation.
type Response struct {
	ReservationID string `json:"reservation_id"`
	CheckoutID    string `json:"checkout_id"`
	SKU           string `json:"sku"`
	Quantity      int    `json:"quantity"`
	Status        string `json:"status"`
}

// Validate checks the request against this phase's business rules.
func (r Request) Validate() error {
	if r.CheckoutID == "" {
		return validationErrorf("checkout_id is required")
	}
	if len(r.CheckoutID) > maxCheckoutIDLength {
		return validationErrorf("checkout_id must be at most %d characters", maxCheckoutIDLength)
	}

	if r.SKU == "" {
		return validationErrorf("sku is required")
	}
	if len(r.SKU) > maxSKULength {
		return validationErrorf("sku must be at most %d characters", maxSKULength)
	}

	if r.Quantity <= 0 {
		return validationErrorf("quantity must be greater than zero")
	}

	return nil
}

// Create validates the request and, if valid, creates a simulated
// reservation. Every valid request currently succeeds deterministically
// — there is no stock tracking, so there is no out-of-stock behavior.
func Create(req Request) (Response, error) {
	if err := req.Validate(); err != nil {
		return Response{}, err
	}

	id, err := uuid.NewV4()
	if err != nil {
		return Response{}, fmt.Errorf("generate reservation id: %w", err)
	}

	return Response{
		ReservationID: id,
		CheckoutID:    req.CheckoutID,
		SKU:           req.SKU,
		Quantity:      req.Quantity,
		Status:        statusReserved,
	}, nil
}
