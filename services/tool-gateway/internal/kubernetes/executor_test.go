package kubernetes

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// fakeK8sServer is a small, in-memory stand-in for the real Kubernetes
// API server -- enough to exercise Executor's own decision logic
// (identity binding, idempotent patch, bounded recovery polling)
// without a real cluster. Mutated directly by each test to model the
// exact sequence of states being verified.
type fakeK8sServer struct {
	uid                string
	resourceVersion    string
	generation         int64
	observedGeneration int64
	replicas           int32
	readyReplicas      int32
	availableReplicas  int32
	available          bool
	annotations        map[string]string
	podWaitingReason   string
	podsReady          bool
	forbidPods         bool
	forbidDeployment   bool
	patchCount         int
	conflictOnPatch    bool
	// healAfterPatch models a GENUINE restart fixing a real failure:
	// once the fake records a patch, subsequent GETs report the pod as
	// healthy -- the only way VERIFIED_RECOVERED should ever be
	// reachable after this correction round's fix (Issue 2).
	healAfterPatch bool
}

func (f *fakeK8sServer) handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && contains(r.URL.Path, "/deployments/"):
			if f.forbidDeployment {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			readyReplicas, availableReplicas, available := f.readyReplicas, f.availableReplicas, f.available
			if f.healAfterPatch && f.patchCount > 0 {
				readyReplicas, availableReplicas, available = f.replicas, f.replicas, true
			}
			availableStatus := "False"
			if available {
				availableStatus = "True"
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": map[string]any{"name": "crashloop-demo", "uid": f.uid, "resourceVersion": f.resourceVersion, "generation": f.generation},
				"spec": map[string]any{
					"replicas": f.replicas,
					"template": map[string]any{"metadata": map[string]any{"annotations": f.annotations}},
				},
				"status": map[string]any{
					"observedGeneration": f.observedGeneration,
					"replicas":           f.replicas,
					"readyReplicas":      readyReplicas,
					"availableReplicas":  availableReplicas,
					"conditions":         []map[string]any{{"type": "Available", "status": availableStatus}},
				},
			})
		case r.Method == http.MethodGet && contains(r.URL.Path, "/replicasets"):
			// forbidPods only takes effect from the point a patch has
			// actually been applied -- this models "forbidden DURING
			// verification", distinct from a forbidden PRE-patch health
			// check (see TestRestartAndVerify_IncompleteCollectionBlocksPatchDecision
			// and client_test.go's own forbidden-first-page tests for
			// that separate case).
			if f.forbidPods && f.patchCount > 0 {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"items": []map[string]any{
					{"metadata": map[string]any{"uid": "rs-1", "ownerReferences": []map[string]any{{"kind": "Deployment", "uid": f.uid}}}},
				},
			})
		case r.Method == http.MethodGet && contains(r.URL.Path, "/pods"):
			if f.forbidPods && f.patchCount > 0 {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			podsReady := f.podsReady
			waitingReason := f.podWaitingReason
			if f.healAfterPatch && f.patchCount > 0 {
				podsReady = true
				waitingReason = ""
			}
			var waiting any
			if waitingReason != "" {
				waiting = map[string]any{"reason": waitingReason}
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"items": []map[string]any{
					{
						"metadata": map[string]any{"name": "crashloop-demo-abc", "uid": "pod-abc-uid", "ownerReferences": []map[string]any{{"kind": "ReplicaSet", "uid": "rs-1"}}},
						"status": map[string]any{
							"phase": "Running",
							"containerStatuses": []map[string]any{
								{"ready": podsReady, "restartCount": 3, "state": map[string]any{"waiting": waiting}},
							},
						},
					},
				},
			})
		case r.Method == http.MethodPatch:
			if f.conflictOnPatch {
				w.WriteHeader(http.StatusConflict)
				return
			}
			f.patchCount++
			if ann, ok := extractAnnotations(r); ok {
				f.annotations = ann
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"uid": f.uid}})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}
}

func extractAnnotations(r *http.Request) (map[string]string, bool) {
	var body struct {
		Spec struct {
			Template struct {
				Metadata struct {
					Annotations map[string]string `json:"annotations"`
				} `json:"metadata"`
			} `json:"template"`
		} `json:"spec"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		return nil, false
	}
	return body.Spec.Template.Metadata.Annotations, true
}

func newTestExecutor(t *testing.T, f *fakeK8sServer, enabled bool) *Executor {
	t.Helper()
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	client := newWithTransport(srv.URL, "reliability-sandbox", "", srv.Client())
	return &Executor{
		client:       client,
		enabled:      enabled,
		pollInterval: time.Millisecond,
		pollDeadline: 20 * time.Millisecond,
		now:          time.Now,
		sleep:        func(time.Duration) {}, // never actually sleeps in tests
	}
}

func healthyFakeServer() *fakeK8sServer {
	return &fakeK8sServer{
		uid: "uid-1", resourceVersion: "100", generation: 2, observedGeneration: 2,
		replicas: 1, readyReplicas: 1, availableReplicas: 1, available: true,
		annotations: map[string]string{}, podsReady: true,
	}
}

func unhealthyFakeServer() *fakeK8sServer {
	return &fakeK8sServer{
		uid: "uid-1", resourceVersion: "100", generation: 2, observedGeneration: 2,
		replicas: 1, readyReplicas: 0, availableReplicas: 0, available: false,
		annotations: map[string]string{}, podsReady: false, podWaitingReason: "CrashLoopBackOff",
	}
}

func TestRestartAndVerify_IdentityMismatchRefusesToAct(t *testing.T) {
	f := unhealthyFakeServer()
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-DIFFERENT")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeIdentityMismatch {
		t.Fatalf("expected identity_mismatch, got %s", result.Outcome)
	}
	if f.patchCount != 0 {
		t.Fatal("expected NO patch to be issued on identity mismatch")
	}
}

func TestRestartAndVerify_DryRunNeverPatches(t *testing.T) {
	f := unhealthyFakeServer()
	e := newTestExecutor(t, f, false) // disabled
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeDryRun {
		t.Fatalf("expected dry_run, got %s", result.Outcome)
	}
	if f.patchCount != 0 {
		t.Fatal("expected NO patch to be issued in dry-run mode")
	}
}

// ---------------------------------------------------------------------
// Issue 2: healthy deployment must never be patched
// ---------------------------------------------------------------------

func TestRestartAndVerify_AlreadyHealthyBeforeApproval_NoPatchNoLongerApplicable(t *testing.T) {
	// "Recovery before approval": the target is already healthy by the
	// time execution is attempted at all.
	f := healthyFakeServer()
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeNoLongerApplicable {
		t.Fatalf("expected no_longer_applicable, got %s", result.Outcome)
	}
	if f.patchCount != 0 {
		t.Fatalf("expected NO patch against an already-healthy Deployment, got %d patches", f.patchCount)
	}
	if result.Recovery != "" {
		t.Fatalf("expected no recovery claim at all (nothing was performed), got %q", result.Recovery)
	}
}

func TestRestartAndVerify_RecoveredBetweenApprovalAndExecution_NoPatchNoLongerApplicable(t *testing.T) {
	// "Recovery between approval and execution": modeled identically --
	// RestartAndVerify always re-checks CURRENT state immediately
	// before any patch, regardless of how long ago the proposal was
	// approved; there is no separate "recovered later" code path to
	// distinguish here; it is this SAME fresh recheck.
	f := healthyFakeServer()
	f.annotations = map[string]string{} // no prior restart attempt recorded
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeNoLongerApplicable {
		t.Fatalf("expected no_longer_applicable, got %s", result.Outcome)
	}
	if f.patchCount != 0 {
		t.Fatal("expected NO patch")
	}
}

// ---------------------------------------------------------------------
// Issue 1 (this correction round): mere not-readiness, with NO
// supported WaitingReason, must never authorize a restart -- only
// ISSUE 1's own negative control proves ownedPodFailureState was
// tightened to match isConfirmedTargetedFailure's stricter policy.
// ---------------------------------------------------------------------

func notReadyNoFailureReasonFakeServer() *fakeK8sServer {
	return &fakeK8sServer{
		uid: "uid-1", resourceVersion: "100", generation: 2, observedGeneration: 2,
		replicas: 1, readyReplicas: 0, availableReplicas: 0, available: false,
		annotations: map[string]string{},
		// Mid-startup/mid-rollout/failing-readiness-probe: not ready,
		// but no CrashLoopBackOff/ImagePullBackOff/ErrImagePull is
		// currently reported -- this is the exact case that must NOT
		// authorize a restart.
		podsReady: false, podWaitingReason: "",
	}
}

func TestRestartAndVerify_NotReadyWithNoSupportedFailureReason_NoPatchNoLongerApplicable(t *testing.T) {
	f := notReadyNoFailureReasonFakeServer()
	e := newTestExecutor(t, f, true) // execution enabled, approved proposal, valid UID
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeNoLongerApplicable {
		t.Fatalf("expected no_longer_applicable (mere not-readiness must never authorize a restart), got %s", result.Outcome)
	}
	if f.patchCount != 0 {
		t.Fatalf("expected ZERO PATCH calls for a not-ready pod with no supported failure reason, got %d", f.patchCount)
	}
	if result.Recovery != "" {
		t.Fatalf("expected no recovery claim at all (nothing was performed), got %q", result.Recovery)
	}
}

func TestRestartAndVerify_GenuineTargetedFailure_PatchesAndRestartFixesIt(t *testing.T) {
	f := unhealthyFakeServer()
	f.healAfterPatch = true // models the restart genuinely fixing the real failure
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Outcome != OutcomeExecuted {
		t.Fatalf("expected executed, got %s", result.Outcome)
	}
	if f.patchCount != 1 {
		t.Fatalf("expected exactly one patch for a genuine targeted failure, got %d", f.patchCount)
	}
	if result.Recovery != VerifiedRecovered {
		t.Fatalf("expected VERIFIED_RECOVERED only after the patch demonstrably fixed the real failure, got %s", result.Recovery)
	}
}

func TestRestartAndVerify_ContinuingGenuineFailure_PatchesButStillUnhealthy(t *testing.T) {
	f := unhealthyFakeServer()
	// healAfterPatch left false: the restart does NOT fix a
	// deterministic failure (e.g. a bad image) -- must be reported
	// honestly, never VERIFIED_RECOVERED.
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if f.patchCount != 1 {
		t.Fatalf("expected exactly one patch, got %d", f.patchCount)
	}
	if result.Recovery != StillUnhealthy {
		t.Fatalf("expected STILL_UNHEALTHY, got %s", result.Recovery)
	}
}

func TestRestartAndVerify_IdempotentRetrySkipsASecondPatch(t *testing.T) {
	f := unhealthyFakeServer()
	f.annotations = map[string]string{RestartedForProposalAnnotation: "proposal-1"} // already applied
	e := newTestExecutor(t, f, true)
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.AlreadyApplied {
		t.Fatal("expected AlreadyApplied=true")
	}
	if f.patchCount != 0 {
		t.Fatalf("expected NO new patch for an already-applied proposal, got %d patches", f.patchCount)
	}
}

func TestRestartAndVerify_ForbiddenDuringVerificationIsSourceUnavailable(t *testing.T) {
	f := unhealthyFakeServer()
	e := newTestExecutor(t, f, true)
	f.forbidPods = true
	result, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Recovery != RecoverySourceUnavailable && result.Recovery != TimedOut {
		t.Fatalf("expected SOURCE_UNAVAILABLE or TIMED_OUT (never a false success), got %s", result.Recovery)
	}
}

func TestCheckRecoveryOnce_UIDChangedIsInconclusive(t *testing.T) {
	f := healthyFakeServer()
	f.uid = "uid-RECREATED"
	e := newTestExecutor(t, f, true)
	outcome, _, decided := e.checkRecoveryOnce(context.Background(), "uid-1", time.Now().Add(time.Second))
	if !decided || outcome != VerificationInconclusive {
		t.Fatalf("expected a decided VERIFICATION_INCONCLUSIVE, got decided=%v outcome=%s", decided, outcome)
	}
}

func TestEnabled_ReflectsConstructorFlag(t *testing.T) {
	f := healthyFakeServer()
	disabled := newTestExecutor(t, f, false)
	enabled := newTestExecutor(t, f, true)
	if disabled.Enabled() {
		t.Fatal("expected Enabled()==false")
	}
	if !enabled.Enabled() {
		t.Fatal("expected Enabled()==true")
	}
}

// ---------------------------------------------------------------------
// Issue 3: atomic resourceVersion conflict handling
// ---------------------------------------------------------------------

func TestRestartAndVerify_ResourceVersionConflictPropagatesErrConflict(t *testing.T) {
	// Models a replacement/concurrent modification occurring between
	// the GET and the PATCH: the fake server's PATCH handler reports a
	// 409 regardless of what was read.
	f := unhealthyFakeServer()
	f.conflictOnPatch = true
	e := newTestExecutor(t, f, true)
	_, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("expected ErrConflict, got %v", err)
	}
	if f.patchCount != 0 {
		t.Fatal("expected the conflicting patch to not count as applied")
	}
}

// ---------------------------------------------------------------------
// Issue 4: incomplete pod/replicaset collection must never produce a
// false STILL_UNHEALTHY or VERIFIED_RECOVERED, and must block a patch
// decision rather than guessing
// ---------------------------------------------------------------------

type incompleteListServer struct {
	uid             string
	resourceVersion string
}

func (f *incompleteListServer) handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && contains(r.URL.Path, "/deployments/"):
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": map[string]any{"name": "crashloop-demo", "uid": f.uid, "resourceVersion": f.resourceVersion, "generation": 1},
				"spec":     map[string]any{"replicas": 1, "template": map[string]any{"metadata": map[string]any{"annotations": map[string]string{}}}},
				"status":   map[string]any{"observedGeneration": 1, "replicas": 1, "readyReplicas": 1, "availableReplicas": 1, "conditions": []map[string]any{{"type": "Available", "status": "True"}}},
			})
		case r.Method == http.MethodGet && contains(r.URL.Path, "/replicasets"):
			// Always reports a continuation token that is never
			// followed to completion within this test -- models an
			// incomplete collection.
			_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"continue": "x"}, "items": []any{}})
		case r.Method == http.MethodGet && contains(r.URL.Path, "/pods"):
			_ = json.NewEncoder(w).Encode(map[string]any{"items": []any{}})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}
}

func TestRestartAndVerify_IncompleteCollectionBlocksPatchDecision(t *testing.T) {
	f := &incompleteListServer{uid: "uid-1", resourceVersion: "100"}
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	client := newWithTransport(srv.URL, "reliability-sandbox", "", srv.Client())
	e := &Executor{client: client, enabled: true, pollInterval: time.Millisecond, pollDeadline: 5 * time.Millisecond, now: time.Now, sleep: func(time.Duration) {}}

	_, err := e.RestartAndVerify(context.Background(), "proposal-1", "uid-1")
	if !errors.Is(err, ErrIncompleteCollection) {
		t.Fatalf("expected ErrIncompleteCollection, got %v", err)
	}
}
