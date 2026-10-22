package api

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/allowlist"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/kubernetes"
)

// KubernetesCapabilityResponse is the Phase 12B-D analogue of
// CapabilityResponse, for the ONE allowlisted Kubernetes action.
// `PreconditionMet` is true only when a pod OWNED by the target
// Deployment currently reports one of the detector-confirmed targeted
// failure reasons (CrashLoopBackOff/ImagePullBackOff/ErrImagePull) --
// never merely "the deployment exists" or "some pod somewhere is
// unhealthy". `DeploymentUID` is the CURRENT, freshly-read UID -- the
// exact value agent-runtime-service's own propose_remediation node
// must pass through as expected_resource_uid when creating a proposal
// (Gate 4/6's own identity-binding requirement).
//
// Correction round (Issue 1): `FailingPodUIDs` additionally lists the
// UID of every pod CURRENTLY owned by the target Deployment and
// CURRENTLY reporting a confirmed targeted failure reason. This is
// what lets a caller (agent-runtime-service's propose_remediation)
// demonstrate that a SPECIFIC incident's own persisted evidence
// (resource_uid) corresponds to a pod this Deployment actually,
// currently owns -- never merely "some capability exists for this
// Deployment in the abstract". Bounded (same MaxItems cap as every
// other list in this package).
//
// Correction round (Issue 5): `GenerationCaughtUp`/`ReadyReplicas`/
// `Replicas`/`AvailableReplicas`/`Available` expose the SAME genuine
// readiness/availability evidence executor.go's own checkRecoveryOnce
// already requires for VERIFIED_RECOVERED -- so agent-runtime-
// service's verify_recovery can independently confirm REAL recovery
// (generation caught up, all replicas ready/available, Available
// condition true) rather than merely inferring health from the
// absence of a confirmed targeted failure reason (PreconditionMet
// alone only proves "no CrashLoopBackOff/ImagePullBackOff/ErrImagePull
// is CURRENTLY observed" -- it does NOT prove the Deployment is
// otherwise healthy, e.g. Pending/scaling for an unrelated reason).
type KubernetesCapabilityResponse struct {
	ActionType         string   `json:"action_type"`
	Target             string   `json:"target"`
	TargetCluster      string   `json:"target_cluster"`
	PreconditionMet    bool     `json:"precondition_met"`
	DeploymentUID      string   `json:"deployment_uid,omitempty"`
	FailingPodUIDs     []string `json:"failing_pod_uids,omitempty"`
	GenerationCaughtUp bool     `json:"generation_caught_up"`
	ReadyReplicas      int32    `json:"ready_replicas"`
	Replicas           int32    `json:"replicas"`
	AvailableReplicas  int32    `json:"available_replicas"`
	Available          bool     `json:"available"`
}

// KubernetesCapabilityHandler backs
// GET /api/v1/remediation-capabilities/kubernetes -- a SEPARATE route
// from the payment capability above (never overloading that
// contract), guarded by the SAME TOOL_GATEWAY_EXECUTION_TOKEN (see
// server.go). Uses the executor's own READ methods only -- this
// handler never calls PatchDeploymentRestartAnnotation; reporting a
// capability is never itself an action.
func KubernetesCapabilityHandler(k8sExecutor *kubernetes.Executor, readClient *kubernetes.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if readClient == nil {
			// Not configured at all -- honest, explicit unavailability,
			// never a fabricated "precondition not met" (which an
			// agent-runtime policy could misread as "nothing to do").
			writeError(w, http.StatusServiceUnavailable, "the Kubernetes capability check is not configured")
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()

		deployment, err := readClient.GetDeployment(ctx, kubernetes.DeploymentName)
		switch {
		case errors.Is(err, kubernetes.ErrUnavailable), errors.Is(err, kubernetes.ErrForbidden):
			writeError(w, http.StatusServiceUnavailable, "the Kubernetes API server is temporarily unavailable or forbidden")
			return
		case err != nil:
			writeError(w, http.StatusBadGateway, "the Kubernetes API server returned an unexpected response")
			return
		}

		replicaSetUIDs, rsComplete, rsErr := readClient.ReplicaSetUIDsOwnedBy(ctx, deployment.Metadata.UID)
		pods, podsComplete, podsErr := readClient.ListPods(ctx)
		if errors.Is(podsErr, kubernetes.ErrUnavailable) || errors.Is(rsErr, kubernetes.ErrUnavailable) {
			writeError(w, http.StatusServiceUnavailable, "the Kubernetes API server is temporarily unavailable")
			return
		}
		if podsErr != nil || rsErr != nil {
			writeError(w, http.StatusBadGateway, "the Kubernetes API server returned an unexpected response")
			return
		}
		// Correction round (Issue 4): an incomplete collection must
		// NEVER be reported as a definitive precondition_met=false (a
		// false-healthy result) -- fail closed instead.
		if !podsComplete || !rsComplete {
			writeError(w, http.StatusServiceUnavailable, "the pod/replicaset collection was incomplete (pagination not fully followed); cannot reliably report a capability right now")
			return
		}

		var failingPodUIDs []string
		for _, p := range pods {
			if replicaSetUIDs[p.OwnerReplicaSetUID] && isConfirmedTargetedFailure(p.WaitingReason) {
				failingPodUIDs = append(failingPodUIDs, p.UID)
			}
		}

		// Correction round (Issue 5): the SAME readiness/availability
		// evidence checkRecoveryOnce independently requires for
		// VERIFIED_RECOVERED -- never just "no confirmed failure
		// reason is currently observed".
		var replicas int32
		if deployment.Spec.Replicas != nil {
			replicas = *deployment.Spec.Replicas
		}
		var availableStatus string
		for _, c := range deployment.Status.Conditions {
			if c.Type == "Available" {
				availableStatus = c.Status
				break
			}
		}

		writeJSON(w, http.StatusOK, KubernetesCapabilityResponse{
			ActionType:         allowlist.ActionRestartAllowlistedDeployment,
			Target:             allowlist.TargetCrashloopDemoDeployment,
			TargetCluster:      allowlist.TargetClusterKindReliabilityLab,
			PreconditionMet:    len(failingPodUIDs) > 0,
			DeploymentUID:      deployment.Metadata.UID,
			FailingPodUIDs:     failingPodUIDs,
			GenerationCaughtUp: deployment.Status.ObservedGeneration == deployment.Metadata.Generation,
			ReadyReplicas:      deployment.Status.ReadyReplicas,
			Replicas:           replicas,
			AvailableReplicas:  deployment.Status.AvailableReplicas,
			Available:          availableStatus == "True",
		})
	}
}

func isConfirmedTargetedFailure(waitingReason string) bool {
	switch waitingReason {
	case "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull":
		return true
	default:
		return false
	}
}
