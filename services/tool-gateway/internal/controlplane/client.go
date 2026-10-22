// Package controlplane is tool-gateway's ONLY way of learning a
// remediation proposal's real, trusted status (Phase 8 §TOOL-GATEWAY
// EXECUTION API): it independently fetches the proposal from
// control-plane and verifies approval/action/target itself --
// nothing about a caller's own execute request is ever trusted for
// that decision. Also records execution start/result -- the ONLY
// write capability CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN
// authorizes (it cannot create or approve/reject a proposal; neither
// of those calls exists in this package at all).
//
// This client reaches exactly ONE base URL, read from trusted
// configuration (config.Settings.ControlPlaneBaseURL) -- never a URL
// supplied by a caller of tool-gateway's own API.
package controlplane

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Sentinel errors the api package switches on to pick the right HTTP
// status to report back to tool-gateway's own caller. Never wraps a
// raw response body or exception text into these -- see each
// method's own bounded error construction below.
var (
	// ErrUnavailable means control-plane could not be reached at all
	// (connection refused/timeout/DNS failure) -- genuinely transient;
	// the caller should treat this the same way agent-runtime-service's
	// own ControlPlaneUnavailableError is treated (Phase 7): leave the
	// proposal's real state untouched and let a retry try again.
	ErrUnavailable = errors.New("control-plane unavailable")
	// ErrNotFound means control-plane returned 404 for this proposal id.
	ErrNotFound = errors.New("remediation proposal not found")
	// ErrUnexpectedResponse means control-plane responded, but not with
	// a 2xx/404 this client understands, or with a 2xx body that did
	// not match the expected shape -- a genuine contract mismatch, not
	// a transient outage.
	ErrUnexpectedResponse = errors.New("control-plane returned an unexpected response")
)

// Proposal is the small, safe subset of control-plane's remediation
// proposal view this service actually needs. Deliberately decoded
// with extra JSON fields ignored (Go's default `encoding/json`
// behavior) rather than a strict/exhaustive mirror, so control-plane
// adding more fields later can never break this client.
type Proposal struct {
	ID         string `json:"id"`
	Status     string `json:"status"`
	ActionType string `json:"action_type"`
	Target     string `json:"target"`
	// Phase 12B-D: populated only for the Kubernetes action -- the
	// identity-binding anchor Gate 6 requires be rechecked immediately
	// before any write.
	TargetCluster       string `json:"target_cluster"`
	ExpectedResourceUID string `json:"expected_resource_uid"`
}

type Client struct {
	baseURL       string
	executorToken string
	httpClient    *http.Client
}

func New(baseURL, executorToken string, timeout time.Duration) *Client {
	return &Client{
		baseURL:       baseURL,
		executorToken: executorToken,
		httpClient:    &http.Client{Timeout: timeout},
	}
}

// GetProposal is an UNAUTHENTICATED read (control-plane's own
// GET /api/v1/remediation-proposals/{id} requires no token -- the
// same local-development "every GET is read-only and safe" policy
// every other control-plane GET route already follows). Sending the
// executor token here would be harmless but pointless; it is
// deliberately omitted so a bug can never make this read path
// silently depend on the one token this client is never meant to
// rely on for reads.
func (c *Client) GetProposal(ctx context.Context, proposalID string) (*Proposal, error) {
	url := fmt.Sprintf("%s/api/v1/remediation-proposals/%s", c.baseURL, proposalID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrNotFound
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, resp.StatusCode)
	}

	var proposal Proposal
	if err := json.NewDecoder(resp.Body).Decode(&proposal); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return &proposal, nil
}

func (c *Client) StartExecution(ctx context.Context, proposalID string) (*Proposal, error) {
	url := fmt.Sprintf("%s/internal/v1/remediation-proposals/%s/execution/start", c.baseURL, proposalID)
	return c.postExecutor(ctx, url, map[string]any{})
}

// RecordExecutionResult is the ONLY place this service ever reports
// "succeeded" or "failed" -- `detail` MUST already be a short,
// bounded, non-secret string (see api/execute.go's own call sites);
// this client never inspects or further bounds it itself.
func (c *Client) RecordExecutionResult(ctx context.Context, proposalID, outcome, detail string) (*Proposal, error) {
	url := fmt.Sprintf("%s/internal/v1/remediation-proposals/%s/execution/result", c.baseURL, proposalID)
	body := map[string]any{"outcome": outcome}
	if detail != "" {
		body["detail"] = detail
	}
	return c.postExecutor(ctx, url, body)
}

func (c *Client) postExecutor(ctx context.Context, url string, body map[string]any) (*Proposal, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	req.Header.Set("Content-Type", "application/json")
	// The ONE write capability this token authorizes -- recording
	// execution start/result only. It is never sent on GetProposal
	// (an unauthenticated read) and this client has no method that
	// could create or approve/reject a proposal at all.
	req.Header.Set("Authorization", "Bearer "+c.executorToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrNotFound
	}
	if resp.StatusCode != http.StatusOK {
		// Drain (bounded) for diagnostics server-side only -- never
		// returned to tool-gateway's own caller.
		_, _ = io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, resp.StatusCode)
	}

	var proposal Proposal
	if err := json.NewDecoder(resp.Body).Decode(&proposal); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return &proposal, nil
}
