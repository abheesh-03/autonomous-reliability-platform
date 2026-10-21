"""Gate D + Gate H (Phase 12A): the real classification logic for all
5 Kubernetes failure detectors, against representative fixtures --
every scenario named in the task's own required fixture list."""

from detectors.kubernetes.detectors import (
    detect_crash_loop_backoff,
    detect_deployment_rollout_failure,
    detect_image_pull_failures,
    detect_oom_killed,
    detect_pod_readiness_degradation,
)
from detectors.schemas.kubernetes import (
    ContainerResourceLimits,
    ContainerStatusObservation,
    ContainerTerminatedState,
    ContainerWaitingState,
    DeploymentConditionObservation,
    DeploymentObservation,
    EventObservation,
    K8sDetectionResult,
    PodConditionObservation,
    PodObservation,
)

NS = "reliability-sandbox"


def _pod(name, container_statuses, conditions=None, phase="Running"):
    return PodObservation(namespace=NS, name=name, phase=phase, container_statuses=container_statuses, conditions=conditions or [])


def _event(name, reason, type_="Warning"):
    return EventObservation(namespace=NS, involved_object_kind="Pod", involved_object_name=name, reason=reason, type=type_)


# ---------------------------------------------------------------------
# Healthy baselines -- must produce ZERO findings
# ---------------------------------------------------------------------


def test_healthy_pod_produces_no_findings_from_any_detector():
    pod = _pod(
        "healthy-web-abc",
        [ContainerStatusObservation(container_name="nginx", ready=True, restart_count=0, running=True)],
        conditions=[PodConditionObservation(type="Ready", status="True")],
    )
    assert detect_image_pull_failures([pod], []) == []
    assert detect_crash_loop_backoff([pod], []) == []
    assert detect_oom_killed([pod]) == []
    assert detect_pod_readiness_degradation([pod], []) == []


def test_healthy_deployment_produces_no_rollout_finding():
    d = DeploymentObservation(
        namespace=NS, name="healthy-web", generation=1, observed_generation=1,
        replicas=1, ready_replicas=1, available_replicas=1, updated_replicas=1,
        conditions=[
            DeploymentConditionObservation(type="Available", status="True", reason="MinimumReplicasAvailable"),
            DeploymentConditionObservation(type="Progressing", status="True", reason="NewReplicaSetAvailable"),
        ],
    )
    assert detect_deployment_rollout_failure([d]) == []


# ---------------------------------------------------------------------
# A. ImagePullBackOff / ErrImagePull
# ---------------------------------------------------------------------


def test_image_pull_backoff_is_confirmed():
    pod = _pod(
        "image-pull-demo-x",
        [ContainerStatusObservation(container_name="nginx", image="nginx:doesnotexist", waiting=ContainerWaitingState(reason="ImagePullBackOff", message="Back-off pulling image"))],
    )
    events = [_event("image-pull-demo-x", "Failed"), _event("image-pull-demo-x", "BackOff")]
    findings = detect_image_pull_failures([pod], events)
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert findings[0].evidence["waiting_reason"] == "ImagePullBackOff"
    assert set(findings[0].supporting_event_reasons) == {"Failed", "BackOff"}


def test_err_image_pull_is_confirmed():
    pod = _pod(
        "image-pull-demo-y",
        [ContainerStatusObservation(container_name="nginx", image="totally/bogus:tag", waiting=ContainerWaitingState(reason="ErrImagePull", message="rpc error: not found"))],
    )
    findings = detect_image_pull_failures([pod], [])
    assert len(findings) == 1
    assert findings[0].evidence["waiting_reason"] == "ErrImagePull"


# ---------------------------------------------------------------------
# B. CrashLoopBackOff
# ---------------------------------------------------------------------


def test_crash_loop_backoff_confirmed_via_waiting_reason():
    pod = _pod(
        "crashloop-demo-x",
        [ContainerStatusObservation(container_name="app", restart_count=6, waiting=ContainerWaitingState(reason="CrashLoopBackOff"), last_terminated=ContainerTerminatedState(reason="Error", exit_code=1))],
    )
    findings = detect_crash_loop_backoff([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED


def test_repeated_exit_code_1_startup_failures_confirmed_without_waiting_reason():
    """Must not depend on the waiting.reason being exactly
    'CrashLoopBackOff' at the instant of collection -- repeated
    terminations with a real exit code are sufficient."""
    pod = _pod(
        "crashloop-demo-y",
        [ContainerStatusObservation(container_name="app", restart_count=4, running=True, last_terminated=ContainerTerminatedState(reason="Error", exit_code=1, started_at="t1", finished_at="t2"))],
    )
    findings = detect_crash_loop_backoff([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert findings[0].evidence["last_termination_exit_code"] == "1"


def test_high_restart_count_without_termination_evidence_is_insufficient():
    pod = _pod("crashloop-demo-z", [ContainerStatusObservation(container_name="app", restart_count=5, running=True)])
    findings = detect_crash_loop_backoff([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE


def test_low_restart_count_is_not_a_crash_loop():
    pod = _pod("ok-pod", [ContainerStatusObservation(container_name="app", restart_count=1, running=True)])
    assert detect_crash_loop_backoff([pod], []) == []


def test_recovered_running_and_ready_container_is_not_confirmed_crash_looping():
    """Correction round, Issue 3: a container that is CURRENTLY
    running=True and ready=True has recovered -- a historical
    restart_count/last_terminated exit code is never, on its own,
    proof of an ACTIVE crash loop once the container is healthy again."""
    pod = _pod(
        "recovered-pod",
        [
            ContainerStatusObservation(
                container_name="app", running=True, ready=True, restart_count=5,
                last_terminated=ContainerTerminatedState(reason="Error", exit_code=1),
            )
        ],
    )
    findings = detect_crash_loop_backoff([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE
    assert "recovered" in findings[0].decision_rationale
    # Historical evidence is still honestly preserved, not discarded.
    assert findings[0].evidence["restart_count"] == "5"
    assert findings[0].evidence["last_termination_exit_code"] == "1"


def test_genuine_active_crash_loop_without_waiting_reason_is_still_confirmed_when_unhealthy():
    """A container NOT currently running+ready (unhealthy/uncertain
    current state) with repeated bad terminations is still a genuine,
    confirmable crash loop -- the Issue 3 fix must not regress this."""
    pod = _pod(
        "still-crashing-pod",
        [
            ContainerStatusObservation(
                container_name="app", running=False, ready=False, restart_count=6,
                last_terminated=ContainerTerminatedState(reason="Error", exit_code=1),
            )
        ],
    )
    findings = detect_crash_loop_backoff([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED


# ---------------------------------------------------------------------
# C. OOMKilled
# ---------------------------------------------------------------------


def test_oom_killed_confirmed_via_explicit_reason():
    """Grounded in the real evidence captured in
    ~/kubernetes-reliability-lab/evidence/oom-demo/pod.yaml: reason
    OOMKilled, exitCode 137, with a real memory limit."""
    pod = _pod(
        "oom-demo-mjbwl",
        [
            ContainerStatusObservation(
                container_name="memory-hog",
                terminated=ContainerTerminatedState(reason="OOMKilled", exit_code=137, started_at="2026-10-20T13:48:16Z", finished_at="2026-10-20T13:48:18Z"),
                limits=ContainerResourceLimits(cpu="100m", memory="48Mi"),
            )
        ],
        phase="Failed",
    )
    findings = detect_oom_killed([pod])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert findings[0].evidence["exit_code"] == "137"
    assert findings[0].evidence["memory_limit"] == "48Mi"


def test_exit_137_without_oomkilled_reason_is_insufficient_not_confirmed():
    """Exit code 137 alone must never be sufficient proof."""
    pod = _pod(
        "some-pod",
        [ContainerStatusObservation(container_name="app", terminated=ContainerTerminatedState(reason="Error", exit_code=137))],
    )
    findings = detect_oom_killed([pod])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE
    assert "never sufficient proof" in findings[0].decision_rationale


def test_oom_killed_via_last_terminated_when_currently_running_again():
    pod = _pod(
        "restarted-after-oom",
        [ContainerStatusObservation(container_name="app", running=True, restart_count=1, last_terminated=ContainerTerminatedState(reason="OOMKilled", exit_code=137))],
    )
    findings = detect_oom_killed([pod])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert findings[0].evidence["termination_source"] == "last"


def test_non_oom_termination_with_different_exit_code_produces_no_finding():
    pod = _pod("normal-exit", [ContainerStatusObservation(container_name="app", terminated=ContainerTerminatedState(reason="Completed", exit_code=0))])
    assert detect_oom_killed([pod]) == []


# ---------------------------------------------------------------------
# D. Deployment rollout failure
# ---------------------------------------------------------------------


def test_rollout_in_progress_is_not_a_confirmed_failure():
    """Briefly-unavailable-but-progressing must never be CONFIRMED."""
    d = DeploymentObservation(
        namespace=NS, name="rolling-out", generation=2, observed_generation=2,
        replicas=3, ready_replicas=2, available_replicas=2,
        conditions=[
            DeploymentConditionObservation(type="Progressing", status="True", reason="ReplicaSetUpdated"),
            DeploymentConditionObservation(type="Available", status="True", reason="MinimumReplicasAvailable"),
        ],
    )
    assert detect_deployment_rollout_failure([d]) == []


def test_progress_deadline_exceeded_is_confirmed():
    d = DeploymentObservation(
        namespace=NS, name="stuck-rollout", generation=5, observed_generation=5,
        replicas=3, ready_replicas=1, available_replicas=1,
        conditions=[
            DeploymentConditionObservation(type="Progressing", status="False", reason="ProgressDeadlineExceeded", message="deployment exceeded its progress deadline"),
            DeploymentConditionObservation(type="Available", status="False", reason="MinimumReplicasUnavailable"),
        ],
    )
    findings = detect_deployment_rollout_failure([d])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert findings[0].evidence["progressing_reason"] == "ProgressDeadlineExceeded"


def test_unavailable_with_generation_caught_up_but_no_deadline_exceeded_is_insufficient():
    d = DeploymentObservation(
        namespace=NS, name="odd-state", generation=3, observed_generation=3,
        replicas=2, ready_replicas=0, available_replicas=0,
        conditions=[DeploymentConditionObservation(type="Available", status="False", reason="MinimumReplicasUnavailable")],
    )
    findings = detect_deployment_rollout_failure([d])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE


def test_generation_not_yet_observed_produces_no_confirmed_failure():
    """The controller has not even caught up to the latest spec yet --
    ambiguous, never confirmed as a failure on generation mismatch alone."""
    d = DeploymentObservation(namespace=NS, name="just-updated", generation=4, observed_generation=3, replicas=2, ready_replicas=2, available_replicas=2)
    findings = detect_deployment_rollout_failure([d])
    assert all(f.result != K8sDetectionResult.CONFIRMED for f in findings)


def test_stale_progress_deadline_exceeded_condition_is_not_confirmed():
    """Correction round, Issue 4: observedGeneration (5) is BEHIND the
    current generation (6) -- the ProgressDeadlineExceeded condition
    may belong to the PRIOR generation's (already-resolved) rollout
    and must not confirm a failure of the new one."""
    d = DeploymentObservation(
        namespace=NS, name="stale-condition", generation=6, observed_generation=5,
        replicas=3, ready_replicas=1, available_replicas=1,
        conditions=[
            DeploymentConditionObservation(type="Progressing", status="False", reason="ProgressDeadlineExceeded"),
            DeploymentConditionObservation(type="Available", status="False", reason="MinimumReplicasUnavailable"),
        ],
    )
    findings = detect_deployment_rollout_failure([d])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE
    assert "prior" in findings[0].decision_rationale.lower()


def test_matching_generation_progress_deadline_exceeded_is_still_confirmed():
    """Regression guard: when observedGeneration DOES match generation,
    ProgressDeadlineExceeded must still CONFIRM (Issue 4 must not
    weaken the genuine-failure case)."""
    d = DeploymentObservation(
        namespace=NS, name="current-condition", generation=6, observed_generation=6,
        replicas=3, ready_replicas=1, available_replicas=1,
        conditions=[DeploymentConditionObservation(type="Progressing", status="False", reason="ProgressDeadlineExceeded")],
    )
    findings = detect_deployment_rollout_failure([d])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED


def test_missing_generation_fields_with_progress_deadline_exceeded_is_not_confirmed():
    """Correction round, Issue 4: generation/observedGeneration
    entirely absent means currentness can never be established --
    represented as uncertainty, never silently promoted to CONFIRMED."""
    d = DeploymentObservation(
        namespace=NS, name="no-generation-info", replicas=3, ready_replicas=1, available_replicas=1,
        conditions=[DeploymentConditionObservation(type="Progressing", status="False", reason="ProgressDeadlineExceeded")],
    )
    findings = detect_deployment_rollout_failure([d])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------
# E. Pod readiness / health degradation
# ---------------------------------------------------------------------


def test_readiness_degradation_confirmed_without_fabricating_a_cause():
    pod = _pod(
        "degraded-pod",
        [ContainerStatusObservation(container_name="app", ready=False)],
        conditions=[PodConditionObservation(type="Ready", status="False", reason="ContainersNotReady", message="containers with unready status: [app]")],
    )
    findings = detect_pod_readiness_degradation([pod], [])
    assert len(findings) == 1
    assert findings[0].result == K8sDetectionResult.CONFIRMED
    assert "no specific root cause is inferred" in findings[0].uncertainty_notes


def test_ready_true_produces_no_finding():
    pod = _pod("ready-pod", [ContainerStatusObservation(container_name="app", ready=True)], conditions=[PodConditionObservation(type="Ready", status="True")])
    assert detect_pod_readiness_degradation([pod], []) == []


def test_pending_phase_is_not_readiness_degradation():
    """A pod still Pending/scheduling is not yet a degraded-while-running pod."""
    pod = _pod("pending-pod", [], conditions=[PodConditionObservation(type="Ready", status="False", reason="ContainersNotReady")], phase="Pending")
    assert detect_pod_readiness_degradation([pod], []) == []


# ---------------------------------------------------------------------
# Missing evidence / unknown reasons / multiple unrelated failures
# ---------------------------------------------------------------------


def test_missing_events_does_not_prevent_classification():
    pod = _pod("image-pull-demo-no-events", [ContainerStatusObservation(container_name="nginx", waiting=ContainerWaitingState(reason="ImagePullBackOff"))])
    findings = detect_image_pull_failures([pod], events=[])
    assert len(findings) == 1
    assert findings[0].supporting_event_reasons == []


def test_unknown_waiting_reason_produces_no_image_pull_or_crash_loop_finding():
    pod = _pod("unknown-reason-pod", [ContainerStatusObservation(container_name="app", restart_count=0, waiting=ContainerWaitingState(reason="SomeTotallyNewReason"))])
    assert detect_image_pull_failures([pod], []) == []
    assert detect_crash_loop_backoff([pod], []) == []


def test_multiple_unrelated_pods_each_produce_their_own_distinct_finding():
    pods = [
        _pod("img-fail", [ContainerStatusObservation(container_name="app", waiting=ContainerWaitingState(reason="ImagePullBackOff"))]),
        _pod("oom-fail", [ContainerStatusObservation(container_name="app", terminated=ContainerTerminatedState(reason="OOMKilled", exit_code=137))]),
    ]
    image_findings = detect_image_pull_failures(pods, [])
    oom_findings = detect_oom_killed(pods)
    assert {f.resource_name for f in image_findings} == {"img-fail"}
    assert {f.resource_name for f in oom_findings} == {"oom-fail"}


def test_repeated_identical_input_yields_identical_findings():
    pod = _pod(
        "crashloop-demo-det",
        [ContainerStatusObservation(container_name="app", restart_count=6, waiting=ContainerWaitingState(reason="CrashLoopBackOff"), last_terminated=ContainerTerminatedState(reason="Error", exit_code=1))],
    )
    events = [_event("crashloop-demo-det", "BackOff")]
    findings_1 = detect_crash_loop_backoff([pod], events)
    findings_2 = detect_crash_loop_backoff([pod], events)
    assert [f.model_dump() for f in findings_1] == [f.model_dump() for f in findings_2]
