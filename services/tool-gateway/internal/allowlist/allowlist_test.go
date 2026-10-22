package allowlist

import "testing"

func TestIsAllowed_PaymentPair(t *testing.T) {
	if !IsAllowed(ActionClearPaymentAuthorizationFault, TargetPaymentService) {
		t.Fatal("expected the payment action/target pair to be allowed")
	}
}

func TestIsAllowed_KubernetesPair(t *testing.T) {
	if !IsAllowed(ActionRestartAllowlistedDeployment, TargetCrashloopDemoDeployment) {
		t.Fatal("expected the kubernetes action/target pair to be allowed")
	}
}

func TestIsAllowed_RejectsCrossProduct(t *testing.T) {
	cases := []struct {
		action, target string
	}{
		{ActionRestartAllowlistedDeployment, TargetPaymentService},
		{ActionClearPaymentAuthorizationFault, TargetCrashloopDemoDeployment},
	}
	for _, c := range cases {
		if IsAllowed(c.action, c.target) {
			t.Fatalf("expected (%q, %q) to be rejected -- no cross-product combination is permitted", c.action, c.target)
		}
	}
}

func TestIsAllowed_RejectsUnknownActionOrTarget(t *testing.T) {
	if IsAllowed("delete_everything", TargetPaymentService) {
		t.Fatal("expected an unknown action to be rejected")
	}
	if IsAllowed(ActionRestartAllowlistedDeployment, "Deployment/reliability-sandbox/some-other-deployment") {
		t.Fatal("expected an unsupported deployment target to be rejected")
	}
	if IsAllowed(ActionRestartAllowlistedDeployment, "Deployment/other-namespace/crashloop-demo") {
		t.Fatal("expected an unsupported namespace target to be rejected")
	}
}

func TestIsAllowedKubernetesTarget_RequiresExactCluster(t *testing.T) {
	if !IsAllowedKubernetesTarget(ActionRestartAllowlistedDeployment, TargetCrashloopDemoDeployment, TargetClusterKindReliabilityLab) {
		t.Fatal("expected the exact allowlisted cluster to be accepted")
	}
	if IsAllowedKubernetesTarget(ActionRestartAllowlistedDeployment, TargetCrashloopDemoDeployment, "some-other-cluster") {
		t.Fatal("expected an unsupported cluster to be rejected")
	}
	if IsAllowedKubernetesTarget(ActionClearPaymentAuthorizationFault, TargetPaymentService, TargetClusterKindReliabilityLab) {
		t.Fatal("expected the payment action to never be accepted as a kubernetes target, regardless of cluster")
	}
}
