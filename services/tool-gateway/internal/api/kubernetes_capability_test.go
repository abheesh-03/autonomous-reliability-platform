package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// ---------------------------------------------------------------------
// Correction round, Issue 5: KubernetesCapabilityHandler must report
// genuine, freshly-observed readiness/availability evidence alongside
// precondition_met -- never just "no confirmed failure reason".
// ---------------------------------------------------------------------

func TestKubernetesCapabilityHandler_HealthyDeploymentReportsFullReadiness(t *testing.T) {
	fk8s := &fakeK8sAPIServer{uid: "uid-1", ready: true}
	srv := fk8s.server()
	defer srv.Close()

	readClient := kubernetesClientForTest(t, srv.URL)
	handler := KubernetesCapabilityHandler(nil, readClient)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities/kubernetes", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var body KubernetesCapabilityResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if body.PreconditionMet {
		t.Fatal("expected precondition_met=false for a healthy deployment")
	}
	if !body.GenerationCaughtUp || !body.Available {
		t.Fatalf("expected a healthy deployment to report generation_caught_up/available=true, got %+v", body)
	}
	if body.ReadyReplicas != 1 || body.Replicas != 1 || body.AvailableReplicas != 1 {
		t.Fatalf("expected 1/1/1 replicas, got %+v", body)
	}
}

func TestKubernetesCapabilityHandler_UnhealthyDeploymentReportsIncompleteReadiness(t *testing.T) {
	fk8s := &fakeK8sAPIServer{uid: "uid-1", ready: false}
	srv := fk8s.server()
	defer srv.Close()

	readClient := kubernetesClientForTest(t, srv.URL)
	handler := KubernetesCapabilityHandler(nil, readClient)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/remediation-capabilities/kubernetes", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var body KubernetesCapabilityResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if !body.PreconditionMet {
		t.Fatal("expected precondition_met=true for a CrashLoopBackOff pod")
	}
	if body.Available || body.ReadyReplicas == body.Replicas {
		t.Fatalf("expected an unhealthy deployment to report readiness as NOT fully ready, got %+v", body)
	}
}
