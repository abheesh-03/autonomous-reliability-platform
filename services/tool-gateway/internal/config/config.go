// Package config reads tool-gateway's environment-variable settings.
//
// Phase 8 credential boundary (see
// docs/architecture/phase-8-human-approval-remediation.md): this
// service holds EXACTLY THREE secrets --
// TOOL_GATEWAY_EXECUTION_TOKEN (what callers, i.e.
// agent-runtime-service, must present to it),
// CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN (what it presents to
// control-plane), and PAYMENT_REMEDIATION_TOKEN (what it presents to
// payment-service). It is never given
// CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN,
// CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN,
// CONTROL_PLANE_LIFECYCLE_TOKEN, PAYMENT_FAULT_INJECTION_TOKEN, any
// database credential, or the Docker socket -- this module simply
// never reads any of those environment variables at all, by
// construction, not merely by convention.
package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Settings is every environment-derived setting this service needs.
// No field has a default that silently widens trust -- an unset
// token means its own endpoint(s) always fail closed (401), exactly
// the same non-blocking-startup, fail-closed philosophy every Python
// service in this platform already follows for its own Bearer
// tokens.
type Settings struct {
	ListenAddr string

	ExecutionToken string

	ControlPlaneBaseURL      string
	RemediationExecutorToken string

	PaymentBaseURL          string
	PaymentRemediationToken string

	RequestTimeout time.Duration
}

func getEnv(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func getEnvDuration(name string, fallbackSeconds int) time.Duration {
	raw := os.Getenv(name)
	if raw == "" {
		return time.Duration(fallbackSeconds) * time.Second
	}
	seconds, err := strconv.Atoi(raw)
	if err != nil || seconds <= 0 {
		return time.Duration(fallbackSeconds) * time.Second
	}
	return time.Duration(seconds) * time.Second
}

// FromEnv reads every setting from the process environment. Never
// panics and never exits the process -- an unconfigured token is a
// valid (if permanently-fail-closed) configuration, not a startup
// error, consistent with every other service in this platform.
func FromEnv() Settings {
	return Settings{
		ListenAddr:               getEnv("TOOL_GATEWAY_LISTEN_ADDR", "0.0.0.0:8004"),
		ExecutionToken:           os.Getenv("TOOL_GATEWAY_EXECUTION_TOKEN"),
		ControlPlaneBaseURL:      getEnv("TOOL_GATEWAY_CONTROL_PLANE_URL", "http://control-plane:8000"),
		RemediationExecutorToken: os.Getenv("CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN"),
		PaymentBaseURL:           getEnv("TOOL_GATEWAY_PAYMENT_URL", "http://payment-service:8081"),
		PaymentRemediationToken:  os.Getenv("PAYMENT_REMEDIATION_TOKEN"),
		RequestTimeout:           getEnvDuration("TOOL_GATEWAY_REQUEST_TIMEOUT_SECONDS", 10),
	}
}

// ValidateNoTokenCollisions is a runtime, fail-closed guard (Phase 8
// correction round, finding #3) over this service's own three
// credentials: TOOL_GATEWAY_EXECUTION_TOKEN (the ONE token a caller --
// agent-runtime-service -- must present TO this service),
// CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN, and
// PAYMENT_REMEDIATION_TOKEN (what this service itself presents
// DOWNSTREAM). scripts/init-remediation-secrets.sh already generates
// these as distinct secrets, but that script is defense-in-depth, not
// the authoritative boundary -- an operator can hand-edit .env or wire
// up a different deployment system entirely. If the INBOUND execution
// token were ever equal to either OUTBOUND credential, agent-runtime-
// service (which legitimately holds the inbound token) would
// implicitly also hold a credential for a capability it was never
// meant to have. Unlike payment-service's own collision guard (which
// deliberately keeps running with the colliding capability disabled,
// to preserve unrelated availability), tool-gateway is a dedicated,
// single-purpose mutation service: failing CLOSED at startup here is
// strictly safer than silently widening privilege, and there is no
// unrelated functionality this service would otherwise need to keep
// serving.
func (s Settings) ValidateNoTokenCollisions() error {
	type pair struct {
		aName, bName   string
		aValue, bValue string
	}
	pairs := []pair{
		{"TOOL_GATEWAY_EXECUTION_TOKEN", "CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN", s.ExecutionToken, s.RemediationExecutorToken},
		{"TOOL_GATEWAY_EXECUTION_TOKEN", "PAYMENT_REMEDIATION_TOKEN", s.ExecutionToken, s.PaymentRemediationToken},
		{"CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN", "PAYMENT_REMEDIATION_TOKEN", s.RemediationExecutorToken, s.PaymentRemediationToken},
	}
	for _, p := range pairs {
		if p.aValue != "" && p.bValue != "" && p.aValue == p.bValue {
			// Never logs/returns either token VALUE -- variable names only.
			return fmt.Errorf("%s and %s must not be configured with the same value", p.aName, p.bName)
		}
	}
	return nil
}
