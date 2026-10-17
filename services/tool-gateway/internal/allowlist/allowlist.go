// Package allowlist is the hard, compiled-in allowlist of remediation
// actions tool-gateway may ever execute (Phase 8 §NEW SERVICE —
// TOOL-GATEWAY). Deliberately NOT a generic command runner: there is
// no map keyed by an arbitrary caller-supplied action string, no
// reflection-based dispatch, and no configuration file a caller could
// influence. Adding a second real action requires a code change here
// (and a matching change to the CHECK constraints in
// database/migrations/V6__create_remediation_schema.sql and to
// agent-runtime-service's own deterministic policy) -- never a data
// change alone.
package allowlist

// ActionClearPaymentAuthorizationFault is the ONE executable
// remediation Phase 8 defines.
const ActionClearPaymentAuthorizationFault = "clear_payment_authorization_fault"

// TargetPaymentService is the ONE allowlisted target.
const TargetPaymentService = "payment-service"

// IsAllowed reports whether (actionType, target) is the allowlisted
// pair -- the ONLY thing this package knows how to say yes to. There
// is no partial match: an otherwise-correct action against the wrong
// target (or vice versa) is refused.
func IsAllowed(actionType, target string) bool {
	return actionType == ActionClearPaymentAuthorizationFault && target == TargetPaymentService
}
