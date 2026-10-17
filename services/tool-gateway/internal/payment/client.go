// Package payment is tool-gateway's client for the ONE downstream
// service it may ever mutate: payment-service's controlled
// authorization fault. It reaches exactly ONE base URL, read from
// trusted configuration (config.Settings.PaymentBaseURL) -- never a
// URL supplied by a caller of tool-gateway's own API -- and holds
// exactly ONE payment-service credential, PAYMENT_REMEDIATION_TOKEN.
// It is never given PAYMENT_FAULT_INJECTION_TOKEN and has no method
// that could call the ENABLE endpoint at all.
package payment

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"
)

var (
	// ErrUnavailable means payment-service could not be reached at
	// all -- genuinely transient.
	ErrUnavailable = errors.New("payment-service unavailable")
	// ErrUnexpectedResponse means payment-service responded, but not
	// with a 2xx this client understands, or with a 2xx body that did
	// not match the expected shape.
	ErrUnexpectedResponse = errors.New("payment-service returned an unexpected response")
)

type faultStatusBody struct {
	Active bool `json:"active"`
}

type faultClearBody struct {
	Active  bool `json:"active"`
	Changed bool `json:"changed"`
}

type healthBody struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}

type Client struct {
	baseURL          string
	remediationToken string
	httpClient       *http.Client
}

func New(baseURL, remediationToken string, timeout time.Duration) *Client {
	return &Client{
		baseURL:          baseURL,
		remediationToken: remediationToken,
		httpClient:       &http.Client{Timeout: timeout},
	}
}

// ClearAuthorizationFault calls the ONE mutating endpoint this client
// ever calls. Idempotent on payment-service's own side (clearing an
// already-inactive fault is always a safe 200) -- this method itself
// adds no retry logic; tool-gateway's own caller (api/execute.go)
// decides what to do with a failure, exactly once per execute()
// attempt (Phase 8 §TOOL-GATEWAY EXECUTION IDEMPOTENCY: at-least-once
// invocation from the OUTSIDE, via agent-runtime's own retried calls
// to tool-gateway -- never a retry loop hidden inside this client).
func (c *Client) ClearAuthorizationFault(ctx context.Context) (active bool, changed bool, err error) {
	url := c.baseURL + "/internal/v1/faults/authorization/clear"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, nil)
	if err != nil {
		return false, false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	req.Header.Set("Authorization", "Bearer "+c.remediationToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, false, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false, false, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, resp.StatusCode)
	}

	var body faultClearBody
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return false, false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return body.Active, body.Changed, nil
}

// GetAuthorizationFaultStatus is the independent verification read
// (Phase 8 §REAL RECOVERY) -- authenticated with the SAME
// remediation token as Clear (payment-service's own
// require_remediation_token, never the injection token), which is
// exactly what lets this one credential both recover the fault and
// independently confirm it is gone. Also used by the read-only
// capability/precondition endpoint (api/capability.go) to check
// whether the fault is active BEFORE any approval exists.
func (c *Client) GetAuthorizationFaultStatus(ctx context.Context) (active bool, err error) {
	url := c.baseURL + "/internal/v1/faults/authorization"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	req.Header.Set("Authorization", "Bearer "+c.remediationToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, resp.StatusCode)
	}

	var body faultStatusBody
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return body.Active, nil
}

// HealthUp independently verifies payment-service's existing health
// contract (GET /health -- NOT /health/ready, which payment-service
// has never exposed; Phase 8 reuses the contract that already exists
// rather than inventing a new one). Validates the EXACT documented
// shape -- status=="UP" AND service=="payment-service" -- never just
// "got a 200", so a misrouted response (e.g. hitting the wrong
// service entirely) cannot be mistaken for a healthy payment-service.
func (c *Client) HealthUp(ctx context.Context) (bool, error) {
	url := c.baseURL + "/health"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, resp.StatusCode)
	}

	var body healthBody
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return body.Status == "UP" && body.Service == "payment-service", nil
}
