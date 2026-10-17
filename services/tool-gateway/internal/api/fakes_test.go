package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
)

// fakeProposal is the small, in-memory stand-in for a real
// control-plane remediation proposal row -- enough to exercise this
// package's own HTTP-calling logic (execute.go/capability.go)
// without a real database. Real database/atomicity/idempotency
// behavior is proven separately in control-plane's own real-PostgreSQL
// tests (services/control-plane/tests/test_remediation_transactions.py);
// this fake only approximates the STATUS MACHINE closely enough for
// tool-gateway's own unit tests.
type fakeProposal struct {
	ID         string
	Status     string
	ActionType string
	Target     string
}

type fakeControlPlane struct {
	mu          sync.Mutex
	proposals   map[string]*fakeProposal
	startCalls  int
	resultCalls int
	lastOutcome string
	lastDetail  string
}

func newFakeControlPlane() *fakeControlPlane {
	return &fakeControlPlane{proposals: map[string]*fakeProposal{}}
}

func (f *fakeControlPlane) addProposal(p *fakeProposal) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.proposals[p.ID] = p
}

func (f *fakeControlPlane) server() *httptest.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/remediation-proposals/{id}", f.handleGet)
	mux.HandleFunc("POST /internal/v1/remediation-proposals/{id}/execution/start", f.handleStart)
	mux.HandleFunc("POST /internal/v1/remediation-proposals/{id}/execution/result", f.handleResult)
	return httptest.NewServer(mux)
}

func (f *fakeControlPlane) writeProposal(w http.ResponseWriter, p *fakeProposal) {
	_ = json.NewEncoder(w).Encode(map[string]string{
		"id":          p.ID,
		"status":      p.Status,
		"action_type": p.ActionType,
		"target":      p.Target,
	})
}

func (f *fakeControlPlane) handleGet(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	id := r.PathValue("id")
	p, ok := f.proposals[id]
	if !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	f.writeProposal(w, p)
}

func (f *fakeControlPlane) handleStart(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	id := r.PathValue("id")
	p, ok := f.proposals[id]
	if !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	f.startCalls++
	if p.Status == "approved" {
		p.Status = "executing"
	}
	f.writeProposal(w, p)
}

func (f *fakeControlPlane) handleResult(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	id := r.PathValue("id")
	p, ok := f.proposals[id]
	if !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	var body struct {
		Outcome string `json:"outcome"`
		Detail  string `json:"detail"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	f.resultCalls++
	f.lastOutcome = body.Outcome
	f.lastDetail = body.Detail
	if p.Status == "executing" {
		p.Status = body.Outcome
	}
	f.writeProposal(w, p)
}

// fakePayment is the small in-memory stand-in for payment-service's
// own fault/health endpoints.
type fakePayment struct {
	mu               sync.Mutex
	active           bool
	healthy          bool
	clearCalls       int
	clearShouldFail  bool
	statusShouldFail bool
	healthShouldFail bool
	// clearMutatesButRespondsAmbiguously models the real, dangerous
	// case (Phase 8 correction round, finding #1): the clear call's
	// OWN mutation genuinely succeeds (active -> false), but the HTTP
	// response describing that is itself malformed/unexpected -- never
	// a non-2xx. A clear caller must never infer success OR failure
	// from this response alone.
	clearMutatesButRespondsAmbiguously bool
}

func newFakePayment() *fakePayment {
	return &fakePayment{active: true, healthy: true}
}

func (f *fakePayment) server() *httptest.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /internal/v1/faults/authorization/clear", f.handleClear)
	mux.HandleFunc("GET /internal/v1/faults/authorization", f.handleStatus)
	mux.HandleFunc("GET /health", f.handleHealth)
	return httptest.NewServer(mux)
}

func (f *fakePayment) handleClear(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.clearCalls++
	if f.clearShouldFail {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	if f.clearMutatesButRespondsAmbiguously {
		// The real mutation genuinely happens first...
		f.active = false
		// ...then the response itself is malformed (a 200 with a body
		// the real client's json.Decoder cannot parse) -- simulating a
		// truncated/corrupted response AFTER the side effect already
		// took hold, never a non-2xx.
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("{not valid json"))
		return
	}
	changed := f.active
	f.active = false
	_ = json.NewEncoder(w).Encode(map[string]any{"active": false, "changed": changed})
}

func (f *fakePayment) handleStatus(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.statusShouldFail {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"active": f.active})
}

func (f *fakePayment) handleHealth(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.healthShouldFail {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	status := "UP"
	if !f.healthy {
		status = "DOWN"
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"status": status, "service": "payment-service"})
}
