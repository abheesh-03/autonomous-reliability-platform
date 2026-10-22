package kubernetes

import (
	"context"
	"errors"
	"fmt"
	"time"
)

// RecoveryOutcome is Gate 7's own required vocabulary -- a Kubernetes
// API write succeeding is NEVER, by itself, treated as recovery.
type RecoveryOutcome string

const (
	VerifiedRecovered         RecoveryOutcome = "VERIFIED_RECOVERED"
	StillUnhealthy            RecoveryOutcome = "STILL_UNHEALTHY"
	VerificationInconclusive  RecoveryOutcome = "VERIFICATION_INCONCLUSIVE"
	RecoverySourceUnavailable RecoveryOutcome = "SOURCE_UNAVAILABLE"
	TimedOut                  RecoveryOutcome = "TIMED_OUT"
)

// ExecutionOutcome classifies what RestartAndVerify actually did,
// BEFORE any recovery-verification outcome is even considered --
// identity/precondition failures, dry-run, and "no longer applicable"
// are all distinct from "the patch was actually attempted".
type ExecutionOutcome string

const (
	// OutcomeDryRun: identity/precondition checks passed, but
	// execution is disabled -- no mutation was performed, and the
	// caller's proposal is left exactly where it was (never marked
	// succeeded or failed).
	OutcomeDryRun ExecutionOutcome = "dry_run"
	// OutcomeIdentityMismatch: the CURRENT Deployment's UID does not
	// match the proposal's own expected_resource_uid -- the target was
	// recreated (or never matched) between approval and execution;
	// refused outright, never silently retargeted.
	OutcomeIdentityMismatch ExecutionOutcome = "identity_mismatch"
	// OutcomeNoLongerApplicable (correction round, Issue 2): the
	// identity matches, but an immediate, independent recheck of the
	// targeted failure condition shows the Deployment's owned pods are
	// ALREADY healthy -- no patch is ever sent in this case. This is
	// NEVER reported as a recovered remediation (no action was
	// performed, so nothing was "recovered" by this proposal); the
	// caller records it as a definitive, honest non-success so the
	// owning incident is not falsely left in a "remediated" state based
	// on evidence that may already be stale.
	OutcomeNoLongerApplicable ExecutionOutcome = "no_longer_applicable"
	// OutcomeExecuted: the patch was applied (or was already applied
	// for this exact proposal id -- idempotent retry), and
	// Recovery/RecoveryDetail describe the independent, fresh
	// verification outcome.
	OutcomeExecuted ExecutionOutcome = "executed"
)

// ExecutionResult is RestartAndVerify's bounded, structured result --
// never a raw API response body.
type ExecutionResult struct {
	Outcome        ExecutionOutcome
	Detail         string
	Recovery       RecoveryOutcome
	ObservedUID    string
	AlreadyApplied bool // true if this exact proposal's patch had already been applied (idempotent retry)
}

// Executor ties Client (transport) to the Gate 6/7 business logic:
// identity binding, idempotent at-most-one-rollout-per-proposal
// patching, and bounded, polled recovery verification. Deliberately a
// separate type from Client itself -- Client knows only how to shape
// and send bounded HTTP requests; Executor is where the "is this
// actually safe and correct to do" decisions live, mirroring this
// service's own api/execute.go separation between payment.Client (a
// thin transport) and the decision logic in that handler.
type Executor struct {
	client       *Client
	enabled      bool
	pollInterval time.Duration
	pollDeadline time.Duration
	now          func() time.Time
	sleep        func(time.Duration)
}

// NewExecutor builds an Executor. `enabled=false` is DRY-RUN mode --
// the documented default (Gate 6: "Default mode: DISABLED/DRY-RUN/NO
// MUTATION") -- identity/precondition checks still run and are still
// reported, but PatchDeploymentRestartAnnotation is never called.
func NewExecutor(client *Client, enabled bool, pollInterval, pollDeadline time.Duration) *Executor {
	return &Executor{
		client:       client,
		enabled:      enabled,
		pollInterval: pollInterval,
		pollDeadline: pollDeadline,
		now:          time.Now,
		sleep:        time.Sleep,
	}
}

// Enabled reports whether this executor will actually perform a
// write if asked -- callers (api/execute.go) check this BEFORE ever
// transitioning a proposal to 'executing', so a dry-run request never
// mutates the proposal's own durable state either.
func (e *Executor) Enabled() bool {
	return e.enabled
}

// DeploymentName is the ONE allowlisted Deployment name this executor
// will ever act on -- a bare constant, never derived from caller
// input (the caller, api/execute.go, has already independently
// verified the full allowlist.IsAllowedKubernetesTarget pair before
// this is ever invoked).
const DeploymentName = "crashloop-demo"

// ErrIncompleteCollection is returned when a Pod/ReplicaSet collection
// could not be completely read -- Issue 4:
// "fail closed as INCOMPLETE" rather than silently treating partial
// data as the whole truth. Treated by every caller in this file as
// equivalent to a transient read failure -- never as evidence of
// health OR of failure.
var ErrIncompleteCollection = errors.New("kubernetes pod/replicaset collection was incomplete")

// ownedPodFailureState independently (re-)establishes whether ANY pod
// currently owned by the Deployment with the given UID is reporting a
// confirmed targeted failure reason. Returns ErrIncompleteCollection
// (never a fabricated true/false) if either list could not be
// completely read.
func (e *Executor) ownedPodFailureState(ctx context.Context, deploymentUID string) (failing bool, err error) {
	replicaSetUIDs, rsComplete, rsErr := e.client.ReplicaSetUIDsOwnedBy(ctx, deploymentUID)
	if rsErr != nil {
		return false, rsErr
	}
	if !rsComplete {
		return false, ErrIncompleteCollection
	}

	pods, podsComplete, podsErr := e.client.ListPods(ctx)
	if podsErr != nil {
		return false, podsErr
	}
	if !podsComplete {
		return false, ErrIncompleteCollection
	}

	ownedCount := 0
	for _, p := range pods {
		if !replicaSetUIDs[p.OwnerReplicaSetUID] {
			continue
		}
		ownedCount++
		// Correction round (Issue 1): ONLY a confirmed targeted failure
		// reason authorizes a restart here -- mirrors
		// api/kubernetes_capability.go's own isConfirmedTargetedFailure
		// policy exactly. Mere not-readiness (mid-startup, mid-rollout,
		// a failing readiness probe with no supported WaitingReason) is
		// NEVER, by itself, sufficient: a restart is a targeted fix for
		// CrashLoopBackOff/ImagePullBackOff/ErrImagePull, not a generic
		// "something looks unready" trigger.
		if unhealthyWaitingReasons[p.WaitingReason] {
			return true, nil
		}
	}
	if ownedCount == 0 {
		// No owned pods observed at all -- distinct from "observed
		// pods, all healthy". Treated as NOT currently failing (there
		// is nothing to remediate), but this is also surfaced to the
		// caller via the zero-owned-pods case being indistinguishable
		// from "genuinely healthy" for THIS method's purposes; callers
		// needing to tell these apart use the pod/replicaset data
		// directly (see checkRecoveryOnce).
		return false, nil
	}
	return false, nil
}

// RestartAndVerify performs the full Gate 6/7 flow for ONE proposal.
// `expectedUID` is the proposal's own durably-recorded
// expected_resource_uid (Gate 6: "Recheck UID ... between approval and
// execution"; "Reject target changes between approval/execution").
func (e *Executor) RestartAndVerify(ctx context.Context, proposalID, expectedUID string) (ExecutionResult, error) {
	current, err := e.client.GetDeployment(ctx, DeploymentName)
	if err != nil {
		return ExecutionResult{}, err
	}

	if current.Metadata.UID != expectedUID {
		return ExecutionResult{
			Outcome:     OutcomeIdentityMismatch,
			Detail:      fmt.Sprintf("expected Deployment UID %q, observed %q -- the target may have been recreated; refusing to act", expectedUID, current.Metadata.UID),
			ObservedUID: current.Metadata.UID,
		}, nil
	}

	if !e.enabled {
		return ExecutionResult{
			Outcome:     OutcomeDryRun,
			Detail:      "Kubernetes execution is disabled (dry-run mode) -- identity/precondition checks passed, but no mutation was performed",
			ObservedUID: current.Metadata.UID,
		}, nil
	}

	alreadyApplied := current.Spec.Template.Metadata.Annotations[RestartedForProposalAnnotation] == proposalID

	if !alreadyApplied {
		// Correction round, Issue 2: independently recheck the ACTUAL
		// targeted failure condition immediately before ever patching
		// -- the proposal may have been approved minutes or hours ago,
		// and the underlying issue may have already resolved itself
		// (or been fixed by something else) in the meantime. A healthy
		// Deployment is NEVER patched, regardless of what an earlier
		// capability read (at proposal-creation time) once reported.
		failing, failureErr := e.ownedPodFailureState(ctx, current.Metadata.UID)
		if failureErr != nil {
			if errors.Is(failureErr, ErrIncompleteCollection) {
				return ExecutionResult{}, fmt.Errorf("%w: cannot safely decide whether to restart without a complete pod/replicaset read", ErrIncompleteCollection)
			}
			return ExecutionResult{}, failureErr
		}
		if !failing {
			return ExecutionResult{
				Outcome:     OutcomeNoLongerApplicable,
				Detail:      "the target Deployment's owned pods are already healthy -- no targeted failure reason is currently observed, so no restart was performed",
				ObservedUID: current.Metadata.UID,
			}, nil
		}

		restartedAt := e.now().UTC().Format(time.RFC3339)
		_, patchErr := e.client.PatchDeploymentRestartAnnotation(
			ctx, DeploymentName, restartedAt, proposalID, current.Metadata.UID, current.Metadata.ResourceVersion,
		)
		if patchErr != nil {
			// Correction round, Issue 3: ErrConflict means the
			// resourceVersion precondition failed atomically at the
			// API server -- the resource changed between our GET and
			// this PATCH. Never retried blindly within this call;
			// propagated so the caller treats it the same as any other
			// transient failure (a FRESH execute() call re-reads
			// current state from scratch).
			return ExecutionResult{}, patchErr
		}
	}

	recovery, detail := e.verifyRecovery(ctx, expectedUID)
	return ExecutionResult{
		Outcome:        OutcomeExecuted,
		Detail:         detail,
		Recovery:       recovery,
		ObservedUID:    current.Metadata.UID,
		AlreadyApplied: alreadyApplied,
	}, nil
}

func conditionStatus(d *Deployment, conditionType string) (string, bool) {
	for _, c := range d.Status.Conditions {
		if c.Type == conditionType {
			return c.Status, true
		}
	}
	return "", false
}

// unhealthyWaitingReasons mirrors detectors/kubernetes/detectors.py's
// own confirmed-failure vocabulary -- a Pod still showing one of these
// is the targeted failure CONTINUING, never proof of recovery.
var unhealthyWaitingReasons = map[string]bool{
	"CrashLoopBackOff": true,
	"ImagePullBackOff": true,
	"ErrImagePull":     true,
}

// verifyRecovery is Gate 7's own bounded, polled, independent
// verification -- NEVER trusts the PATCH response alone. Every fact
// checked here is re-fetched FRESH on every iteration.
func (e *Executor) verifyRecovery(ctx context.Context, expectedUID string) (RecoveryOutcome, string) {
	deadline := e.now().Add(e.pollDeadline)

	for {
		outcome, detail, decided := e.checkRecoveryOnce(ctx, expectedUID, deadline)
		if decided {
			return outcome, detail
		}
		if e.now().After(deadline) {
			return TimedOut, "recovery verification deadline elapsed without a confident result"
		}
		e.sleep(e.pollInterval)
	}
}

func (e *Executor) checkRecoveryOnce(ctx context.Context, expectedUID string, deadline time.Time) (RecoveryOutcome, string, bool) {
	d, err := e.client.GetDeployment(ctx, DeploymentName)
	if err != nil {
		if errors.Is(err, ErrUnavailable) || errors.Is(err, ErrForbidden) {
			// Transient/RBAC during verification -- never proof of
			// failure; keep polling until the deadline.
			return "", "", false
		}
		return RecoverySourceUnavailable, fmt.Sprintf("could not reliably re-read the Deployment: %v", err), true
	}
	if d.Metadata.UID != expectedUID {
		// The target was recreated DURING verification -- this
		// observation cannot be trusted as evidence about the
		// resource this proposal actually acted on.
		return VerificationInconclusive, "the Deployment's UID changed during recovery verification -- this observation cannot be attributed to the executed action", true
	}

	replicaSetUIDs, rsComplete, rsErr := e.client.ReplicaSetUIDsOwnedBy(ctx, expectedUID)
	pods, podsComplete, podsErr := e.client.ListPods(ctx)
	// Correction round, Issue 4: an incomplete OR failed collection is
	// NEVER silently treated as "no pods, so healthy" -- it is handled
	// identically to a transient read failure: keep polling until the
	// deadline, then TIMED_OUT (never VERIFIED_RECOVERED, never
	// STILL_UNHEALTHY, from incomplete evidence).
	if podsErr != nil || rsErr != nil {
		if (podsErr != nil && !errors.Is(podsErr, ErrUnavailable) && !errors.Is(podsErr, ErrForbidden)) ||
			(rsErr != nil && !errors.Is(rsErr, ErrUnavailable) && !errors.Is(rsErr, ErrForbidden)) {
			return RecoverySourceUnavailable, "could not reliably collect pod/replicaset evidence", true
		}
		return "", "", false
	}
	if !podsComplete || !rsComplete {
		return "", "", false
	}

	ownedPods := make([]PodSummary, 0, len(pods))
	for _, p := range pods {
		if replicaSetUIDs[p.OwnerReplicaSetUID] {
			ownedPods = append(ownedPods, p)
		}
	}

	generationCaughtUp := d.Status.ObservedGeneration == d.Metadata.Generation
	replicasReady := d.Spec.Replicas != nil && d.Status.ReadyReplicas == *d.Spec.Replicas && d.Status.AvailableReplicas == *d.Spec.Replicas
	availableStatus, hasAvailable := conditionStatus(d, "Available")
	available := hasAvailable && availableStatus == "True"

	anyStillFailing := false
	for _, p := range ownedPods {
		if unhealthyWaitingReasons[p.WaitingReason] || !p.ContainersReady {
			anyStillFailing = true
		}
	}

	if generationCaughtUp && replicasReady && available && !anyStillFailing && len(ownedPods) > 0 {
		return VerifiedRecovered, fmt.Sprintf("observedGeneration caught up, %d/%d replicas ready and available, Available=True, no owned pod reports a confirmed failure reason", d.Status.ReadyReplicas, *d.Spec.Replicas), true
	}

	// Not yet recovered -- but a rollout genuinely takes time. Only
	// commit to STILL_UNHEALTHY once the deadline has passed; before
	// that, this is simply "not yet", so keep polling.
	if e.now().After(deadline) {
		if anyStillFailing {
			return StillUnhealthy, "a pod owned by this Deployment still reports a confirmed targeted failure reason after the restart", true
		}
		return StillUnhealthy, "the Deployment did not reach a fully ready/available state within the verification deadline", true
	}
	return "", "", false
}
