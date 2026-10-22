// Package allowlist is the hard, compiled-in allowlist of remediation
// actions tool-gateway may ever execute (Phase 8 §NEW SERVICE —
// TOOL-GATEWAY, extended Phase 12B-D). Deliberately NOT a generic
// command runner: there is no map keyed by an arbitrary caller-supplied
// action string, no reflection-based dispatch, and no configuration
// file a caller could influence. Adding a third real action requires a
// code change here (and a matching change to the CHECK constraints in
// database/migrations/V7__add_kubernetes_remediation_action.sql and to
// agent-runtime-service's own deterministic policy) -- never a data
// change alone.
package allowlist

// ActionClearPaymentAuthorizationFault is Phase 8's ONE executable
// remediation action.
const ActionClearPaymentAuthorizationFault = "clear_payment_authorization_fault"

// TargetPaymentService is ActionClearPaymentAuthorizationFault's ONE
// allowlisted target.
const TargetPaymentService = "payment-service"

// ActionRestartAllowlistedDeployment is Phase 12B-D's ONE executable
// Kubernetes remediation action -- a bounded "rollout restart"
// (patching the pod template's restart annotation), never a generic
// Kubernetes write.
const ActionRestartAllowlistedDeployment = "restart_allowlisted_deployment"

// TargetCrashloopDemoDeployment is
// ActionRestartAllowlistedDeployment's ONE allowlisted target --
// mirrors database/migrations/V7__add_kubernetes_remediation_action.sql's
// own combined CHECK constraint exactly.
const TargetCrashloopDemoDeployment = "Deployment/reliability-sandbox/crashloop-demo"

// TargetClusterKindReliabilityLab is the ONE cluster
// ActionRestartAllowlistedDeployment may ever target.
const TargetClusterKindReliabilityLab = "kind-reliability-lab"

// IsAllowed reports whether (actionType, target) is one of the
// allowlisted pairs -- the ONLY thing this package knows how to say
// yes to. There is no partial match: an otherwise-correct action
// against the wrong target (or vice versa) is refused, and there is no
// cross-product between the two pairs (e.g. the Kubernetes action
// against the payment target is never allowed).
func IsAllowed(actionType, target string) bool {
	switch actionType {
	case ActionClearPaymentAuthorizationFault:
		return target == TargetPaymentService
	case ActionRestartAllowlistedDeployment:
		return target == TargetCrashloopDemoDeployment
	default:
		return false
	}
}

// IsAllowedKubernetesTarget additionally verifies the cluster --
// (actionType, target) alone is not a sufficient identity check for
// the Kubernetes action, since the SAME deployment name/namespace pair
// could theoretically exist in a different cluster. Never called for
// the payment action, which has no cluster concept at all.
func IsAllowedKubernetesTarget(actionType, target, targetCluster string) bool {
	return actionType == ActionRestartAllowlistedDeployment &&
		target == TargetCrashloopDemoDeployment &&
		targetCluster == TargetClusterKindReliabilityLab
}
