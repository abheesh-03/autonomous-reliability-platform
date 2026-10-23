// Phase 14 correction round, Issue 3: proves GetProposal sends this
// service's own distinct internal-service-read identity in its own
// dedicated header, never Authorization (which the executor token
// uses for a different capability), and never at all when
// unconfigured (pre-Phase-14 behavior, unchanged).
package controlplane

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestGetProposal_SendsInternalReadTokenHeaderWhenConfigured(t *testing.T) {
	var gotHeader, gotAuth string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotHeader = r.Header.Get("X-Internal-Service-Token")
		gotAuth = r.Header.Get("Authorization")
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Proposal{ID: "p1", Status: "approved"})
	}))
	defer server.Close()

	client := NewWithInternalReadToken(server.URL, "executor-token", "internal-read-token", 5*time.Second)
	proposal, err := client.GetProposal(context.Background(), "p1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if proposal.ID != "p1" {
		t.Fatalf("expected proposal id p1, got %q", proposal.ID)
	}
	if gotHeader != "internal-read-token" {
		t.Fatalf("expected X-Internal-Service-Token to be sent, got %q", gotHeader)
	}
	// Never sent in Authorization -- that header is reserved for the
	// executor token on the write-capable endpoints only.
	if gotAuth != "" {
		t.Fatalf("expected no Authorization header on GetProposal, got %q", gotAuth)
	}
}

func TestGetProposal_SendsNoInternalHeaderWhenUnconfigured(t *testing.T) {
	var gotHeader string
	headerSeen := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotHeader, headerSeen = r.Header.Get("X-Internal-Service-Token"), r.Header.Get("X-Internal-Service-Token") != ""
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Proposal{ID: "p1", Status: "approved"})
	}))
	defer server.Close()

	// The plain `New` constructor (every pre-Phase-14 call site) --
	// behavior must be unchanged.
	client := New(server.URL, "executor-token", 5*time.Second)
	if _, err := client.GetProposal(context.Background(), "p1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if headerSeen {
		t.Fatalf("expected no X-Internal-Service-Token header to be sent, got %q", gotHeader)
	}
}

// Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B/C:
// WithServiceAssertion returns a per-request copy that relays
// X-Service-Assertion on EVERY one of this client's own calls to
// control-plane -- GetProposal, StartExecution, and
// RecordExecutionResult alike -- additive to (never a replacement
// for) the existing internal-read/executor tokens, and never mutating
// the original, shared *Client.

func TestWithServiceAssertion_RelaysOnGetProposal(t *testing.T) {
	var gotAssertion string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAssertion = r.Header.Get("X-Service-Assertion")
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Proposal{ID: "p1", Status: "approved"})
	}))
	defer server.Close()

	original := NewWithInternalReadToken(server.URL, "executor-token", "internal-read-token", 5*time.Second)
	scoped := original.WithServiceAssertion("relayed-assertion-token")
	if _, err := scoped.GetProposal(context.Background(), "p1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotAssertion != "relayed-assertion-token" {
		t.Fatalf("expected X-Service-Assertion to be relayed, got %q", gotAssertion)
	}

	// The ORIGINAL, shared client must never be mutated by the scoped copy.
	gotAssertion = ""
	if _, err := original.GetProposal(context.Background(), "p1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotAssertion != "" {
		t.Fatalf("expected the original client to still send no assertion, got %q", gotAssertion)
	}
}

func TestWithServiceAssertion_RelaysOnStartExecutionAndRecordExecutionResult(t *testing.T) {
	var gotAssertions []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAssertions = append(gotAssertions, r.Header.Get("X-Service-Assertion"))
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Proposal{ID: "p1", Status: "executing"})
	}))
	defer server.Close()

	client := New(server.URL, "executor-token", 5*time.Second).WithServiceAssertion("relayed-assertion-token")
	if _, err := client.StartExecution(context.Background(), "p1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := client.RecordExecutionResult(context.Background(), "p1", "succeeded", "detail"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	for i, got := range gotAssertions {
		if got != "relayed-assertion-token" {
			t.Fatalf("call %d: expected X-Service-Assertion to be relayed, got %q", i, got)
		}
	}
}

func TestWithServiceAssertion_SendsNoHeaderWhenEmpty(t *testing.T) {
	headerSeen := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		headerSeen = r.Header.Get("X-Service-Assertion") != ""
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Proposal{ID: "p1", Status: "approved"})
	}))
	defer server.Close()

	// Mirrors ExecuteHandler calling WithServiceAssertion("") when the
	// incoming request carried no X-Service-Assertion at all (legacy/
	// local-dev mode) -- no stray empty header should ever be sent.
	client := New(server.URL, "executor-token", 5*time.Second).WithServiceAssertion("")
	if _, err := client.GetProposal(context.Background(), "p1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if headerSeen {
		t.Fatalf("expected no X-Service-Assertion header to be sent when empty")
	}
}
