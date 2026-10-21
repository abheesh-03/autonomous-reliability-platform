"""Gate D (Phase 12A): deterministic classification of 5 Kubernetes
failure patterns, against ALREADY-COLLECTED, already-parsed
observations (pure functions -- no I/O here at all). Every CONFIRMED
or INSUFFICIENT_EVIDENCE finding carries real evidence fields read
directly off the object; nothing here invents a cause that was not
actually observed.

A detector returns an EMPTY list for a genuinely healthy resource --
there is no "NOT_PRESENT" finding object emitted per healthy pod (that
would be pure noise at scale); absence of a finding IS the healthy
result, same as Phase 11B's own propagation-path builder only ever
emitting entries when real evidence exists.
"""

from detectors.schemas.kubernetes import (
    DeploymentObservation,
    EventObservation,
    K8sDetectionFinding,
    K8sDetectionResult,
    PodObservation,
    ReplicaSetObservation,
)

_IMAGE_PULL_WAITING_REASONS = frozenset({"ImagePullBackOff", "ErrImagePull"})
_IMAGE_PULL_EVENT_REASONS = frozenset({"Failed", "BackOff", "ErrImagePull", "InspectFailed"})
_CRASH_LOOP_EVENT_REASONS = frozenset({"BackOff", "Unhealthy"})
_MIN_CRASH_LOOP_RESTARTS = 3


def _events_for_pod(events: list[EventObservation], pod: PodObservation, reasons: frozenset[str]) -> list[EventObservation]:
    return [
        e
        for e in events
        if e.involved_object_kind == "Pod"
        and e.involved_object_name == pod.name
        and e.namespace == pod.namespace
        and e.reason in reasons
    ]


# ---------------------------------------------------------------------
# A. ImagePullBackOff / ErrImagePull
# ---------------------------------------------------------------------


def detect_image_pull_failures(pods: list[PodObservation], events: list[EventObservation]) -> list[K8sDetectionFinding]:
    findings: list[K8sDetectionFinding] = []
    for pod in pods:
        for cs in pod.container_statuses:
            if cs.waiting is None or cs.waiting.reason not in _IMAGE_PULL_WAITING_REASONS:
                continue
            matching_events = _events_for_pod(events, pod, _IMAGE_PULL_EVENT_REASONS)
            findings.append(
                K8sDetectionFinding(
                    detector_id="image_pull_backoff",
                    resource_kind="Pod",
                    namespace=pod.namespace,
                    resource_name=pod.name,
                    container_name=cs.container_name,
                    result=K8sDetectionResult.CONFIRMED,
                    evidence={
                        "waiting_reason": cs.waiting.reason or "",
                        "waiting_message": cs.waiting.message or "",
                        "image": cs.image or "",
                        "pod_creation_timestamp": pod.creation_timestamp or "",
                    },
                    supporting_event_reasons=sorted({e.reason for e in matching_events if e.reason}),
                    decision_rationale=(
                        f"container {cs.container_name!r} has waiting.reason={cs.waiting.reason!r}, a direct, "
                        f"unambiguous Kubernetes-reported image pull failure"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------
# B. CrashLoopBackOff
# ---------------------------------------------------------------------


def detect_crash_loop_backoff(pods: list[PodObservation], events: list[EventObservation]) -> list[K8sDetectionFinding]:
    """Never depends solely on `waiting.reason == "CrashLoopBackOff"`
    being present at the exact instant of collection -- a pod can be
    genuinely crash-looping (high restart count, repeated non-zero
    terminations) even when momentarily observed in a different
    transient state.

    Correction round (Issue 3): restart-count/last-termination
    evidence is used CONSERVATIVELY -- it only CONFIRMS a crash loop
    when the container's CURRENT state is itself unhealthy or
    uncertain. A container currently observed `running=True` AND
    `ready=True` has RECOVERED; historical restarts/terminations alone
    are never, by themselves, proof of an ACTIVE crash loop once the
    container is healthy again -- that case is reported as
    INSUFFICIENT_EVIDENCE, with the historical evidence preserved
    honestly rather than discarded."""
    findings: list[K8sDetectionFinding] = []
    for pod in pods:
        for cs in pod.container_statuses:
            restart_count = cs.restart_count or 0
            waiting_is_crashloop = cs.waiting is not None and cs.waiting.reason == "CrashLoopBackOff"
            has_bad_last_termination = (
                cs.last_terminated is not None
                and cs.last_terminated.exit_code is not None
                and cs.last_terminated.exit_code != 0
            )
            currently_healthy = cs.running is True and cs.ready is True
            repeated_restarts_with_termination_evidence = restart_count >= _MIN_CRASH_LOOP_RESTARTS and has_bad_last_termination

            if waiting_is_crashloop or (repeated_restarts_with_termination_evidence and not currently_healthy):
                matching_events = _events_for_pod(events, pod, _CRASH_LOOP_EVENT_REASONS)
                evidence = {"restart_count": str(restart_count)}
                rationale_bits = []
                if waiting_is_crashloop:
                    evidence["waiting_reason"] = cs.waiting.reason or ""
                    rationale_bits.append("waiting.reason == 'CrashLoopBackOff'")
                if cs.last_terminated is not None:
                    evidence["last_termination_reason"] = cs.last_terminated.reason or ""
                    evidence["last_termination_exit_code"] = str(cs.last_terminated.exit_code)
                    evidence["last_termination_finished_at"] = cs.last_terminated.finished_at or ""
                    rationale_bits.append(
                        f"last termination exit_code={cs.last_terminated.exit_code} with restart_count={restart_count}"
                    )
                findings.append(
                    K8sDetectionFinding(
                        detector_id="crash_loop_backoff",
                        resource_kind="Pod",
                        namespace=pod.namespace,
                        resource_name=pod.name,
                        container_name=cs.container_name,
                        result=K8sDetectionResult.CONFIRMED,
                        evidence=evidence,
                        supporting_event_reasons=sorted({e.reason for e in matching_events if e.reason}),
                        decision_rationale="; ".join(rationale_bits),
                    )
                )
                continue

            if repeated_restarts_with_termination_evidence and currently_healthy:
                # The container has RECOVERED (currently Running and
                # Ready). restart_count/last_terminated are real,
                # historical evidence and are preserved honestly below,
                # but they are never, on their own, proof of a crash
                # loop that is still ACTIVE.
                matching_events = _events_for_pod(events, pod, _CRASH_LOOP_EVENT_REASONS)
                findings.append(
                    K8sDetectionFinding(
                        detector_id="crash_loop_backoff",
                        resource_kind="Pod",
                        namespace=pod.namespace,
                        resource_name=pod.name,
                        container_name=cs.container_name,
                        result=K8sDetectionResult.INSUFFICIENT_EVIDENCE,
                        evidence={
                            "restart_count": str(restart_count),
                            "last_termination_reason": cs.last_terminated.reason or "",
                            "last_termination_exit_code": str(cs.last_terminated.exit_code),
                            "last_termination_finished_at": cs.last_terminated.finished_at or "",
                        },
                        supporting_event_reasons=sorted({e.reason for e in matching_events if e.reason}),
                        decision_rationale=(
                            f"container {cs.container_name!r} is CURRENTLY running and ready despite a historical "
                            f"restart_count={restart_count} and a nonzero last termination exit_code "
                            f"({cs.last_terminated.exit_code}) -- the container has recovered"
                        ),
                        uncertainty_notes=(
                            "historical restart/termination evidence alone does not confirm an ACTIVE crash loop "
                            "once the container is observed running and ready"
                        ),
                    )
                )
                continue

            if restart_count >= _MIN_CRASH_LOOP_RESTARTS:
                # Still suspicious (many restarts) but no termination
                # evidence at all to corroborate it -- insufficient,
                # never silently dropped.
                matching_events = _events_for_pod(events, pod, _CRASH_LOOP_EVENT_REASONS)
                findings.append(
                    K8sDetectionFinding(
                        detector_id="crash_loop_backoff",
                        resource_kind="Pod",
                        namespace=pod.namespace,
                        resource_name=pod.name,
                        container_name=cs.container_name,
                        result=K8sDetectionResult.INSUFFICIENT_EVIDENCE,
                        evidence={"restart_count": str(restart_count), "pod_creation_timestamp": pod.creation_timestamp or ""},
                        supporting_event_reasons=sorted({e.reason for e in matching_events if e.reason}),
                        decision_rationale=(
                            f"container {cs.container_name!r} has a high restart_count ({restart_count}) but "
                            "no last termination state was available to corroborate a crash loop"
                        ),
                        uncertainty_notes="restart count alone, without termination evidence, is not sufficient proof",
                    )
                )
    return findings


# ---------------------------------------------------------------------
# C. OOMKilled
# ---------------------------------------------------------------------


def detect_oom_killed(pods: list[PodObservation]) -> list[K8sDetectionFinding]:
    """CONFIRMED requires the real, explicit `terminated.reason ==
    'OOMKilled'` field -- exit code 137 ALONE (which many unrelated
    signals, e.g. SIGKILL from other causes, also produce) is never
    treated as proof on its own."""
    findings: list[K8sDetectionFinding] = []
    for pod in pods:
        for cs in pod.container_statuses:
            for label, state in (("current", cs.terminated), ("last", cs.last_terminated)):
                if state is None:
                    continue
                evidence = {
                    "termination_source": label,
                    "exit_code": str(state.exit_code) if state.exit_code is not None else "",
                    "started_at": state.started_at or "",
                    "finished_at": state.finished_at or "",
                }
                if cs.limits is not None and cs.limits.memory:
                    evidence["memory_limit"] = cs.limits.memory

                if state.reason == "OOMKilled":
                    findings.append(
                        K8sDetectionFinding(
                            detector_id="oom_killed",
                            resource_kind="Pod",
                            namespace=pod.namespace,
                            resource_name=pod.name,
                            container_name=cs.container_name,
                            result=K8sDetectionResult.CONFIRMED,
                            evidence=evidence,
                            decision_rationale=(
                                f"{label} termination state reports reason='OOMKilled' explicitly "
                                f"(exit_code={state.exit_code})"
                            ),
                        )
                    )
                elif state.exit_code == 137:
                    findings.append(
                        K8sDetectionFinding(
                            detector_id="oom_killed",
                            resource_kind="Pod",
                            namespace=pod.namespace,
                            resource_name=pod.name,
                            container_name=cs.container_name,
                            result=K8sDetectionResult.INSUFFICIENT_EVIDENCE,
                            evidence=evidence,
                            decision_rationale=(
                                f"{label} termination exit_code=137 (SIGKILL) but reason={state.reason!r}, not "
                                "'OOMKilled' -- exit code 137 alone is never sufficient proof of an OOM kill"
                            ),
                            uncertainty_notes="exit code 137 can result from causes other than OOM (e.g. an external SIGKILL)",
                        )
                    )
    return findings


# ---------------------------------------------------------------------
# D. Deployment rollout failure
# ---------------------------------------------------------------------


def _condition(deployment: DeploymentObservation, type_: str):
    return next((c for c in deployment.conditions if c.type == type_), None)


def detect_deployment_rollout_failure(deployments: list[DeploymentObservation]) -> list[K8sDetectionFinding]:
    """Never treats a BRIEFLY-unavailable-but-still-progressing
    rollout as a confirmed failure -- only `ProgressDeadlineExceeded`
    (Kubernetes' own official terminal failure signal) or a
    generation mismatch combined with an unavailable, non-progressing
    deployment counts as CONFIRMED.

    Correction round (Issue 4): a `ProgressDeadlineExceeded` condition
    is only trustworthy evidence about the CURRENT spec generation if
    `status.observedGeneration == metadata.generation` -- the
    condition itself carries no generation stamp of its own, so a
    controller that has NOT yet processed the latest generation could
    still be reporting a condition left over from a PRIOR generation's
    (already-resolved) failure. `ProgressDeadlineExceeded` therefore
    only CONFIRMS when the generation is confirmed caught-up; a stale
    or unknown/missing generation is represented as uncertainty, never
    silently promoted to CONFIRMED."""
    findings: list[K8sDetectionFinding] = []
    for d in deployments:
        progressing = _condition(d, "Progressing")
        available = _condition(d, "Available")
        generation_caught_up = d.generation is not None and d.observed_generation is not None and d.generation == d.observed_generation

        evidence = {
            "generation": str(d.generation) if d.generation is not None else "",
            "observed_generation": str(d.observed_generation) if d.observed_generation is not None else "",
            "replicas": str(d.replicas) if d.replicas is not None else "",
            "ready_replicas": str(d.ready_replicas) if d.ready_replicas is not None else "",
            "available_replicas": str(d.available_replicas) if d.available_replicas is not None else "",
        }
        if progressing is not None:
            evidence["progressing_status"] = progressing.status or ""
            evidence["progressing_reason"] = progressing.reason or ""
            evidence["progressing_last_transition_time"] = progressing.last_transition_time or ""
        if available is not None:
            evidence["available_status"] = available.status or ""
            evidence["available_last_transition_time"] = available.last_transition_time or ""

        if progressing is not None and progressing.status == "False" and progressing.reason == "ProgressDeadlineExceeded":
            if generation_caught_up:
                findings.append(
                    K8sDetectionFinding(
                        detector_id="deployment_rollout_failure",
                        resource_kind="Deployment",
                        namespace=d.namespace,
                        resource_name=d.name,
                        result=K8sDetectionResult.CONFIRMED,
                        evidence=evidence,
                        decision_rationale=(
                            "Progressing condition is False with reason=ProgressDeadlineExceeded, and "
                            "observedGeneration matches generation -- Kubernetes' own terminal rollout-failure "
                            "signal, confirmed applicable to the current spec"
                        ),
                    )
                )
            else:
                findings.append(
                    K8sDetectionFinding(
                        detector_id="deployment_rollout_failure",
                        resource_kind="Deployment",
                        namespace=d.namespace,
                        resource_name=d.name,
                        result=K8sDetectionResult.INSUFFICIENT_EVIDENCE,
                        evidence=evidence,
                        decision_rationale=(
                            "a Progressing condition reports reason=ProgressDeadlineExceeded, but observedGeneration "
                            f"({d.observed_generation!r}) does not confirm the controller has processed the current "
                            f"generation ({d.generation!r}) -- this condition may belong to a prior, already-resolved "
                            "generation"
                        ),
                        uncertainty_notes=(
                            "a stale or unknown generation means this condition cannot be trusted as evidence about "
                            "the CURRENT deployment spec"
                        ),
                    )
                )
            continue

        unavailable_and_caught_up = (
            generation_caught_up
            and available is not None
            and available.status == "False"
            and (progressing is None or progressing.status != "True")
        )
        if unavailable_and_caught_up:
            findings.append(
                K8sDetectionFinding(
                    detector_id="deployment_rollout_failure",
                    resource_kind="Deployment",
                    namespace=d.namespace,
                    resource_name=d.name,
                    result=K8sDetectionResult.INSUFFICIENT_EVIDENCE,
                    evidence=evidence,
                    decision_rationale=(
                        "observedGeneration matches generation (the controller has processed the latest spec) and "
                        "Available=False, but no ProgressDeadlineExceeded was reported -- suspicious, not confirmed"
                    ),
                    uncertainty_notes="a deployment can be briefly unavailable during a normal, still-progressing rollout",
                )
            )
    return findings


# ---------------------------------------------------------------------
# E. Pod readiness / health degradation
# ---------------------------------------------------------------------


def detect_pod_readiness_degradation(pods: list[PodObservation], events: list[EventObservation]) -> list[K8sDetectionFinding]:
    """Reports the OBSERVED fact (Ready=False while Running) only --
    never fabricates a specific cause. See `uncertainty_notes`: a
    caller should cross-reference the OTHER detectors' findings for
    this same pod before assuming any particular explanation."""
    findings: list[K8sDetectionFinding] = []
    for pod in pods:
        if pod.phase not in ("Running", None):
            continue
        ready_condition = next((c for c in pod.conditions if c.type == "Ready"), None)
        if ready_condition is None or ready_condition.status != "False":
            continue

        not_ready_containers = [cs.container_name for cs in pod.container_statuses if cs.ready is False]
        matching_events = [e for e in events if e.involved_object_kind == "Pod" and e.involved_object_name == pod.name and e.namespace == pod.namespace]

        findings.append(
            K8sDetectionFinding(
                detector_id="pod_readiness_degradation",
                resource_kind="Pod",
                namespace=pod.namespace,
                resource_name=pod.name,
                result=K8sDetectionResult.CONFIRMED,
                evidence={
                    "phase": pod.phase or "",
                    "ready_condition_reason": ready_condition.reason or "",
                    "ready_condition_message": ready_condition.message or "",
                    "ready_condition_last_transition_time": ready_condition.last_transition_time or "",
                    "not_ready_containers": ",".join(not_ready_containers),
                },
                supporting_event_reasons=sorted({e.reason for e in matching_events if e.reason}),
                decision_rationale="pod phase is Running but the Ready condition reports status=False",
                uncertainty_notes=(
                    "this reports the OBSERVED readiness degradation only -- no specific root cause is inferred "
                    "from readiness=False alone; cross-reference other detector findings for this same pod"
                ),
            )
        )
    return findings
