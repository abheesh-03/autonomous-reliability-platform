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
	baseURL           string
	executorToken     string
	internalReadToken string
	// serviceAssertion (Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY
	// FIX, Issue B/C): the SAME X-Service-Assertion agent-runtime-
	// service relayed to THIS request's own /execute call, forwarded
	// here unverified -- this client holds no copy of the shared
	// HS256 signing secret and never attempts to decode or trust it
	// itself; control-plane is the only party that cryptographically
	// verifies it. Set per-request via WithServiceAssertion, below --
	// never mutates the shared, long-lived *Client this package's
	// caller constructs once at startup.
	serviceAssertion string
	httpClient       *http.Client
}

// WithServiceAssertion returns a shallow copy of c that forwards
// `assertion` (if non-empty) as X-Service-Assertion on every one of
// its own calls to control-plane -- GetProposal, StartExecution, and
// RecordExecutionResult alike. ExecuteHandler calls this ONCE, at the
// top of handling a single incoming /execute request, with whatever
// X-Service-Assertion header THAT request itself carried (or an empty
// string if none did, in legacy/local-dev mode) -- the returned copy
// is then used for the remainder of that one request only; the
// original *Client (shared across all requests) is never mutated.
func (c *Client) WithServiceAssertion(assertion string) *Client {
	clone := *c
	clone.serviceAssertion = assertion
	return &clone
}

func New(baseURL, executorToken string, timeout time.Duration) *Client {
	return &Client{
		baseURL:       baseURL,
		executorToken: executorToken,
		httpClient:    &http.Client{Timeout: timeout},
	}
}

// NewWithInternalReadToken is the Phase 14 correction round (Issue 3)
// constructor: `internalReadToken` is tool-gateway's own distinct,
// bounded internal-service-read identity
// (CONTROL_PLANE_INTERNAL_READ_TOKEN_TOOL_GATEWAY), sent ONLY on
// GetProposal below, in its own dedicated header
// (X-Internal-Service-Token, never Authorization, which the executor
// token above already uses for a DIFFERENT capability). Only actually
// required by control-plane once
// CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is enabled there; kept as
// a separate constructor (rather than changing New's signature) so
// every existing call site/test of New continues to compile and
// behave identically.
func NewWithInternalReadToken(baseURL, executorToken, internalReadToken string, timeout time.Duration) *Client {
	c := New(baseURL, executorToken, timeout)
	c.internalReadToken = internalReadToken
	return c
}

// GetProposal was an UNAUTHENTICATED read in local-development mode
// (control-plane's own GET /api/v1/remediation-proposals/{id}
// requires no token by default) -- the same local-development "every
// GET is read-only and safe" policy every other control-plane GET
// route already follows. As of the Phase 14 correction round, it ALSO
// sends this client's own distinct internal-service-read identity
// (never the executor token, never a human-approval credential) --
// harmless when organization-context enforcement is disabled, and
// REQUIRED once it is enabled (Issue 3: tool-gateway's own independent
// proposal-status re-verification must keep working in secure mode).
func (c *Client) GetProposal(ctx context.Context, proposalID string) (*Proposal, error) {
	url := fmt.Sprintf("%s/api/v1/remediation-proposals/%s", c.baseURL, proposalID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	if c.internalReadToken != "" {
		req.Header.Set("X-Internal-Service-Token", c.internalReadToken)
	}
	// Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B:
	// ADDITIVE to the internal read token above -- control-plane's
	// own get_actor_or_tool_gateway_reader now REQUIRES this (the
	// bare internal token alone is no longer sufficient; see that
	// function's own docstring).
	if c.serviceAssertion != "" {
		req.Header.Set("X-Service-Assertion", c.serviceAssertion)
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
	// Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue C:
	// ADDITIVE to the executor token above -- control-plane now
	// independently verifies this relayed actor's organization
	// against the proposal's real owning incident before either
	// state transition below runs (see api/remediation.py's own
	// start_remediation_execution/record_remediation_execution_result
	// docstrings).
	if c.serviceAssertion != "" {
		req.Header.Set("X-Service-Assertion", c.serviceAssertion)
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
