package config

import "testing"

// Phase 8 correction round (finding #3): a runtime, fail-closed guard
// over scripts/init-remediation-secrets.sh's own distinctness
// guarantee -- these tests exercise Settings.ValidateNoTokenCollisions
// directly, independent of any .env file.

func baseSettings() Settings {
	return Settings{
		ExecutionToken:           "exec-token",
		RemediationExecutorToken: "executor-token",
		PaymentRemediationToken:  "payment-token",
	}
}

func TestValidateNoTokenCollisions_DistinctTokensPass(t *testing.T) {
	if err := baseSettings().ValidateNoTokenCollisions(); err != nil {
		t.Fatalf("expected no error for three distinct tokens, got %v", err)
	}
}

func TestValidateNoTokenCollisions_ExecutionAndExecutorCollide(t *testing.T) {
	s := baseSettings()
	s.RemediationExecutorToken = s.ExecutionToken
	if err := s.ValidateNoTokenCollisions(); err == nil {
		t.Fatal("expected an error when TOOL_GATEWAY_EXECUTION_TOKEN == CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN")
	}
}

func TestValidateNoTokenCollisions_ExecutionAndPaymentCollide(t *testing.T) {
	s := baseSettings()
	s.PaymentRemediationToken = s.ExecutionToken
	if err := s.ValidateNoTokenCollisions(); err == nil {
		t.Fatal("expected an error when TOOL_GATEWAY_EXECUTION_TOKEN == PAYMENT_REMEDIATION_TOKEN")
	}
}

func TestValidateNoTokenCollisions_ExecutorAndPaymentCollide(t *testing.T) {
	s := baseSettings()
	s.PaymentRemediationToken = s.RemediationExecutorToken
	if err := s.ValidateNoTokenCollisions(); err == nil {
		t.Fatal("expected an error when CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN == PAYMENT_REMEDIATION_TOKEN")
	}
}

func TestValidateNoTokenCollisions_ErrorNeverContainsTokenValue(t *testing.T) {
	s := baseSettings()
	s.RemediationExecutorToken = s.ExecutionToken
	err := s.ValidateNoTokenCollisions()
	if err == nil {
		t.Fatal("expected an error")
	}
	// Never logs/returns the actual (shared) token value -- variable
	// names only.
	if containsSubstring(err.Error(), s.ExecutionToken) {
		t.Fatalf("error message must never contain the actual token value, got %q", err.Error())
	}
}

func TestValidateNoTokenCollisions_UnconfiguredTokensNeverCollide(t *testing.T) {
	// Empty/unconfigured tokens are a normal (if fully fail-closed via
	// RequireExecutionToken) startup state, never a "collision" --
	// two blank strings carry no shared secret.
	s := Settings{}
	if err := s.ValidateNoTokenCollisions(); err != nil {
		t.Fatalf("expected no error for three unconfigured tokens, got %v", err)
	}
}

func containsSubstring(haystack, needle string) bool {
	if needle == "" {
		return false
	}
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
