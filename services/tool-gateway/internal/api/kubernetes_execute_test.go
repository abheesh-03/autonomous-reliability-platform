package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/controlplane"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/kubernetes"
)

// fakeK8sAPIServer backs the Kubernetes action's own execute.go tests
// -- a small, in-memory stand-in for the real Kubernetes API server,
// mirroring fakeControlPlane/fakePayment's own convention.
type fakeK8sAPIServer struct {
	uid            string
	ready          bool
	healAfterPatch bool // models a genuine restart fixing a real failure (Issue 2)
	patchCount     int
}

func (f *fakeK8sAPIServer) server() *httptest.Server {
	healed := func() bool { return f.ready || (f.healAfterPatch && f.patchCount > 0) }
	mux := http.NewServeMux()
	mux.HandleFunc("GET /apis/apps/v1/namespaces/reliability-sandbox/deployments/crashloop-demo", func(w http.ResponseWriter, r *http.Request) {
		readyReplicas := int32(0)
		if healed() {
			readyReplicas = 1
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"metadata": map[string]any{"name": "crashloop-demo", "uid": f.uid, "resourceVersion": "100", "generation": 1},
			"spec":     map[string]any{"replicas": 1, "template": map[string]any{"metadata": map[string]any{"annotations": map[string]string{}}}},
			"status": map[string]any{
				"observedGeneration": 1, "replicas": 1, "readyReplicas": readyReplicas, "availableReplicas": readyReplicas,
				"conditions": []map[string]any{{"type": "Available", "status": boolStatus(healed())}},
			},
		})
	})
	mux.HandleFunc("GET /apis/apps/v1/namespaces/reliability-sandbox/replicasets", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []map[string]any{{"metadata": map[string]any{"uid": "rs-1", "ownerReferences": []map[string]any{{"kind": "Deployment", "uid": f.uid}}}}},
		})
	})
	mux.HandleFunc("GET /api/v1/namespaces/reliability-sandbox/pods", func(w http.ResponseWriter, r *http.Request) {
		var waiting any
		if !healed() {
			waiting = map[string]any{"reason": "CrashLoopBackOff"}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []map[string]any{{
				"metadata": map[string]any{"name": "crashloop-demo-x", "uid": "pod-x-uid", "ownerReferences": []map[string]any{{"kind": "ReplicaSet", "uid": "rs-1"}}},
				"status":   map[string]any{"phase": "Running", "containerStatuses": []map[string]any{{"ready": healed(), "state": map[string]any{"waiting": waiting}}}},
			}},
		})
	})
	mux.HandleFunc("PATCH /apis/apps/v1/namespaces/reliability-sandbox/deployments/crashloop-demo", func(w http.ResponseWriter, r *http.Request) {
		f.patchCount++
		_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"uid": f.uid}})
	})
	return httptest.NewServer(mux)
}

func boolStatus(b bool) string {
	if b {
		return "True"
	}
	return "False"
}

func newKubernetesHarness(t *testing.T, k8sReady, executionEnabled, healAfterPatch bool) (*fakeControlPlane, *fakeK8sAPIServer, http.HandlerFunc) {
	t.Helper()
	fcp := newFakeControlPlane()
	cpSrv := fcp.server()
	t.Cleanup(cpSrv.Close)

	fk8s := &fakeK8sAPIServer{uid: "uid-1", ready: k8sReady, healAfterPatch: healAfterPatch}
	k8sSrv := fk8s.server()
	t.Cleanup(k8sSrv.Close)

	cpClient := controlplane.New(cpSrv.URL, "executor-token", 5*time.Second)
	k8sClient := kubernetesClientForTest(t, k8sSrv.URL)
	executor := kubernetes.NewExecutor(k8sClient, executionEnabled, time.Millisecond, 20*time.Millisecond)

	handler := ExecuteHandler(cpClient, nil, executor)
	return fcp, fk8s, handler
}

// kubernetesClientForTest constructs a real kubernetes.Client pointed
// at a local httptest server -- via the package's own test-only seam
// (NewInsecureForTesting), since New() now requires real TLS/credential
// material (Issue 5) that a local httptest.Server has no use for.
func kubernetesClientForTest(t *testing.T, baseURL string) *kubernetes.Client {
	t.Helper()
	c := kubernetes.NewInsecureForTesting(baseURL, "reliability-sandbox", 5*time.Second)
	return c
}

func TestExecute_KubernetesAction_DryRunNeverStartsExecutionOrPatches(t *testing.T) {
	fcp, fk8s, handler := newKubernetesHarness(t, true, false, false) // executionEnabled=false
	fcp.addProposal(&fakeProposal{
		ID: "k1", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})

	rec := postExecute(handler, `{"proposal_id":"k1"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.startCalls != 0 {
		t.Fatalf("expected StartExecution to NEVER be called in dry-run mode, got %d calls", fcp.startCalls)
	}
	if fk8s.patchCount != 0 {
		t.Fatalf("expected NO patch in dry-run mode, got %d", fk8s.patchCount)
	}
	if fcp.proposals["k1"].Status != "approved" {
		t.Fatalf("expected the proposal to remain 'approved', got %s", fcp.proposals["k1"].Status)
	}
}

func TestExecute_KubernetesAction_GenuineFailure_RestartFixesIt_RecordsSuccess(t *testing.T) {
	// Starts UNHEALTHY (a genuine targeted failure) with healAfterPatch=true
	// -- modeling a restart that demonstrably fixes a real, transient
	// failure. Correction round, Issue 2: a healthy target is never
	// patched at all (see TestExecute_KubernetesAction_AlreadyHealthy_NoPatchRecordsFailure
	// below), so "success" can only ever be reached via a genuine
	// failure -> patch -> independently verified recovery path.
	fcp, fk8s, handler := newKubernetesHarness(t, false, true, true)
	fcp.addProposal(&fakeProposal{
		ID: "k2", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})

	rec := postExecute(handler, `{"proposal_id":"k2"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var resp ExecuteResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Status != "succeeded" {
		t.Fatalf("expected succeeded, got %s", resp.Status)
	}
	if fk8s.patchCount != 1 {
		t.Fatalf("expected exactly one patch, got %d", fk8s.patchCount)
	}
}

func TestExecute_KubernetesAction_AlreadyHealthy_NoPatchRecordsFailure(t *testing.T) {
	// Correction round, Issue 2 negative control: the target is
	// ALREADY healthy (k8sReady=true from the start) when execution is
	// attempted -- no patch must ever be sent, and this must NEVER be
	// recorded as a successful/recovered remediation.
	fcp, fk8s, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k2b", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})

	rec := postExecute(handler, `{"proposal_id":"k2b"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409 (recorded as a non-success), got %d: %s", rec.Code, rec.Body.String())
	}
	if fk8s.patchCount != 0 {
		t.Fatalf("expected NO patch against an already-healthy target, got %d patches", fk8s.patchCount)
	}
	if fcp.proposals["k2b"].Status != "failed" {
		t.Fatalf("expected the proposal to be honestly recorded 'failed' (never 'succeeded' for an action that never ran), got %s", fcp.proposals["k2b"].Status)
	}
}

func TestExecute_KubernetesAction_IdentityMismatchRecordsFailureNeverSucceeds(t *testing.T) {
	fcp, fk8s, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k3", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-DIFFERENT",
	})

	rec := postExecute(handler, `{"proposal_id":"k3"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.proposals["k3"].Status != "failed" {
		t.Fatalf("expected the proposal to be recorded 'failed', got %s", fcp.proposals["k3"].Status)
	}
	if fk8s.patchCount != 0 {
		t.Fatal("expected NO patch when the target identity does not match")
	}
}

func TestExecute_KubernetesAction_StillUnhealthyRecordsFailure(t *testing.T) {
	fcp, _, handler := newKubernetesHarness(t, false, true, false) // k8sReady=false, healAfterPatch=false -- restart does not fix it
	fcp.addProposal(&fakeProposal{
		ID: "k4", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})

	rec := postExecute(handler, `{"proposal_id":"k4"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.proposals["k4"].Status != "failed" {
		t.Fatalf("expected the proposal to be recorded 'failed', got %s", fcp.proposals["k4"].Status)
	}
}

func TestExecute_KubernetesAction_UnconfiguredExecutorFailsSafelyWithoutRecording(t *testing.T) {
	fcp := newFakeControlPlane()
	cpSrv := fcp.server()
	t.Cleanup(cpSrv.Close)
	cpClient := controlplane.New(cpSrv.URL, "executor-token", 5*time.Second)
	handler := ExecuteHandler(cpClient, nil, nil) // k8sExecutor == nil: not configured at all

	fcp.addProposal(&fakeProposal{
		ID: "k5", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})

	rec := postExecute(handler, `{"proposal_id":"k5"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 (dry-run response, unconfigured executor), got %d: %s", rec.Code, rec.Body.String())
	}
	if fcp.proposals["k5"].Status != "approved" {
		t.Fatalf("expected the proposal to remain 'approved' (never started), got %s", fcp.proposals["k5"].Status)
	}
}

func TestExecute_KubernetesAction_RejectsPaymentTarget(t *testing.T) {
	fcp, _, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k6", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "payment-service", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})
	rec := postExecute(handler, `{"proposal_id":"k6"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409 (not allowlisted), got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestExecute_KubernetesAction_RejectsUnsupportedCluster(t *testing.T) {
	fcp, _, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k7", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "some-other-cluster", ExpectedResourceUID: "uid-1",
	})
	rec := postExecute(handler, `{"proposal_id":"k7"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409 (cluster not allowlisted), got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestExecute_KubernetesAction_PendingApprovalIsRefused(t *testing.T) {
	fcp, _, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k8", Status: "pending_approval", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})
	rec := postExecute(handler, `{"proposal_id":"k8"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestExecute_KubernetesAction_RejectedIsRefused(t *testing.T) {
	fcp, _, handler := newKubernetesHarness(t, true, true, false)
	fcp.addProposal(&fakeProposal{
		ID: "k9", Status: "rejected", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})
	rec := postExecute(handler, `{"proposal_id":"k9"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestExecute_KubernetesAction_RetryAfterSuccessIsIdempotent(t *testing.T) {
	fcp, fk8s, handler := newKubernetesHarness(t, false, true, true)
	fcp.addProposal(&fakeProposal{
		ID: "k10", Status: "approved", ActionType: "restart_allowlisted_deployment",
		Target: "Deployment/reliability-sandbox/crashloop-demo", TargetCluster: "kind-reliability-lab", ExpectedResourceUID: "uid-1",
	})
	first := postExecute(handler, `{"proposal_id":"k10"}`)
	second := postExecute(handler, `{"proposal_id":"k10"}`)
	if first.Code != http.StatusOK || second.Code != http.StatusOK {
		t.Fatalf("expected both retries to succeed, got %d and %d", first.Code, second.Code)
	}
	if fk8s.patchCount != 1 {
		t.Fatalf("expected exactly ONE patch across both calls (idempotent retry), got %d", fk8s.patchCount)
	}
}
