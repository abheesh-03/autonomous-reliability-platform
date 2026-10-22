"""Phase 13, Gate 2: deterministic classification of AWS failure
patterns against ALREADY-COLLECTED, already-parsed observations (pure
functions -- no I/O here at all, exactly mirroring
`detectors.kubernetes.detectors`'s own discipline).

A detector returns an EMPTY list for a genuinely healthy/intentional-
state resource -- there is no "NOT_PRESENT" finding object emitted for
every healthy alarm/instance/service (pure noise at scale); absence of
a finding IS the healthy result. Detection and causal explanation are
kept separate: a CloudTrail management event near a resource's own
observation window is surfaced as bounded, attributed SUPPORTING
EVIDENCE only (`supporting_change_events`) -- it is NEVER promoted to
an assumed root cause by this module. Temporal proximity alone never
establishes causation.
"""

from detectors.schemas.aws import (
    AwsDetectionFinding,
    AwsDetectionResult,
    CloudTrailEventObservation,
    CloudWatchAlarmObservation,
    Ec2InstanceObservation,
    EcsServiceObservation,
)

# EC2 lifecycle states that are a NORMAL, often-intentional part of an
# instance's own lifecycle -- never classified as a failure on their
# own (Gate 2: "do not classify every stopped EC2 instance ... as a
# failure; intentional shutdowns ... exist").
_EC2_NON_FAILURE_STATES = frozenset({"stopped", "stopping", "shutting-down", "terminated", "pending"})

_MAX_SUPPORTING_EVENTS = 10


def _events_for_resource(events: list[CloudTrailEventObservation], resource_identifier: str) -> list[CloudTrailEventObservation]:
    return [e for e in events if resource_identifier in e.resource_names]


def _format_supporting_events(events: list[CloudTrailEventObservation]) -> list[str]:
    return [
        f"{e.event_name} by {e.username or 'unknown'} at {e.event_time or 'unknown time'}"
        for e in events[:_MAX_SUPPORTING_EVENTS]
    ]


# ---------------------------------------------------------------------
# A. CloudWatch alarm state
# ---------------------------------------------------------------------


def detect_cloudwatch_alarms_in_alarm_state(
    alarms: list[CloudWatchAlarmObservation],
    account_id: str,
    region: str,
    cloudtrail_events: list[CloudTrailEventObservation] | None = None,
) -> list[AwsDetectionFinding]:
    """CONFIRMED for an alarm CURRENTLY reporting StateValue=="ALARM" --
    a real, direct, CloudWatch-reported fact, never inferred. An alarm
    reporting "INSUFFICIENT_DATA" is a real, honestly weaker signal
    (CloudWatch itself cannot currently evaluate the condition) --
    INSUFFICIENT_EVIDENCE, never silently dropped. "OK" produces no
    finding at all (the healthy result)."""
    events = cloudtrail_events or []
    findings: list[AwsDetectionFinding] = []
    for alarm in alarms:
        if alarm.state_value == "ALARM":
            supporting = _events_for_resource(events, alarm.alarm_name)
            findings.append(
                AwsDetectionFinding(
                    detector_id="cloudwatch_alarm_in_alarm_state",
                    resource_kind="CloudWatchAlarm",
                    account_id=account_id,
                    region=region,
                    resource_id=alarm.alarm_name,
                    resource_arn=alarm.alarm_arn,
                    result=AwsDetectionResult.CONFIRMED,
                    evidence={
                        "state_value": alarm.state_value or "",
                        "state_reason": alarm.state_reason or "",
                        "state_updated_timestamp": alarm.state_updated_timestamp or "",
                        "namespace": alarm.namespace or "",
                        "metric_name": alarm.metric_name or "",
                        "comparison_operator": alarm.comparison_operator or "",
                        "threshold": str(alarm.threshold) if alarm.threshold is not None else "",
                    },
                    supporting_change_events=_format_supporting_events(supporting),
                    decision_rationale=(
                        f"CloudWatch alarm {alarm.alarm_name!r} currently reports StateValue=ALARM "
                        f"(updated {alarm.state_updated_timestamp or 'unknown time'}), a direct, "
                        "unambiguous CloudWatch-reported fact"
                    ),
                    uncertainty_notes=(
                        "a nearby CloudTrail management event (if any) is supporting context only -- "
                        "temporal proximity alone does not establish that it caused this alarm"
                        if supporting
                        else None
                    ),
                )
            )
        elif alarm.state_value == "INSUFFICIENT_DATA":
            findings.append(
                AwsDetectionFinding(
                    detector_id="cloudwatch_alarm_in_alarm_state",
                    resource_kind="CloudWatchAlarm",
                    account_id=account_id,
                    region=region,
                    resource_id=alarm.alarm_name,
                    resource_arn=alarm.alarm_arn,
                    result=AwsDetectionResult.INSUFFICIENT_EVIDENCE,
                    evidence={"state_value": alarm.state_value or "", "state_reason": alarm.state_reason or ""},
                    decision_rationale=(
                        f"CloudWatch alarm {alarm.alarm_name!r} currently reports StateValue=INSUFFICIENT_DATA -- "
                        "CloudWatch itself cannot currently evaluate this alarm's condition"
                    ),
                    uncertainty_notes="insufficient data is a real but inconclusive signal -- never treated as a confirmed failure",
                )
            )
    return findings


# ---------------------------------------------------------------------
# B. EC2 instance/system status checks (enrolled instances only)
# ---------------------------------------------------------------------


def detect_ec2_failed_status_checks(
    instances: list[Ec2InstanceObservation],
    account_id: str,
    region: str,
    cloudtrail_events: list[CloudTrailEventObservation] | None = None,
) -> list[AwsDetectionFinding]:
    """Only ever evaluates instances the caller already explicitly
    enrolled (the collector never returns instances outside that
    scope). A "stopped"/"stopping"/"shutting-down"/"terminated"/
    "pending" instance produces NO finding at all -- Gate 2's own
    explicit requirement that intentional shutdowns/normal lifecycle
    transitions are never misclassified as failures. Only a RUNNING
    instance's own status checks are ever evaluated."""
    events = cloudtrail_events or []
    findings: list[AwsDetectionFinding] = []
    for instance in instances:
        if instance.state_name in _EC2_NON_FAILURE_STATES:
            continue
        if instance.state_name != "running":
            # An unrecognized/future state value -- conservatively not
            # evaluated rather than guessed at.
            continue

        supporting = _events_for_resource(events, instance.instance_id)
        statuses = {"instance_status": instance.instance_status, "system_status": instance.system_status}
        impaired = [k for k, v in statuses.items() if v == "impaired"]
        insufficient = [k for k, v in statuses.items() if v == "insufficient-data"]
        unknown = [k for k, v in statuses.items() if v is None]

        evidence = {
            "state_name": instance.state_name or "",
            "instance_status": instance.instance_status or "",
            "system_status": instance.system_status or "",
        }

        if impaired:
            findings.append(
                AwsDetectionFinding(
                    detector_id="ec2_failed_status_check",
                    resource_kind="Ec2Instance",
                    account_id=account_id,
                    region=region,
                    resource_id=instance.instance_id,
                    result=AwsDetectionResult.CONFIRMED,
                    evidence=evidence,
                    supporting_change_events=_format_supporting_events(supporting),
                    decision_rationale=(
                        f"instance {instance.instance_id!r} is running but reports {', '.join(impaired)}="
                        "'impaired' -- a direct, AWS-reported status-check failure"
                    ),
                    uncertainty_notes=(
                        "a nearby CloudTrail management event (if any) is supporting context only -- "
                        "temporal proximity alone does not establish that it caused this status check failure"
                        if supporting
                        else None
                    ),
                )
            )
        elif insufficient or unknown:
            reason = (
                f"reports {', '.join(insufficient)}='insufficient-data'"
                if insufficient
                else f"status-check evidence ({', '.join(unknown)}) was not available"
            )
            findings.append(
                AwsDetectionFinding(
                    detector_id="ec2_failed_status_check",
                    resource_kind="Ec2Instance",
                    account_id=account_id,
                    region=region,
                    resource_id=instance.instance_id,
                    result=AwsDetectionResult.INSUFFICIENT_EVIDENCE,
                    evidence=evidence,
                    decision_rationale=f"instance {instance.instance_id!r} is running and {reason}",
                    uncertainty_notes="insufficient/missing status-check evidence is never treated as a confirmed failure",
                )
            )
    return findings


# ---------------------------------------------------------------------
# C. ECS service desired-vs-running task degradation
# ---------------------------------------------------------------------


def detect_ecs_service_task_degradation(
    services: list[EcsServiceObservation],
    account_id: str,
    region: str,
    cloudtrail_events: list[CloudTrailEventObservation] | None = None,
) -> list[AwsDetectionFinding]:
    """Excludes desired_count in (None, 0) entirely -- Gate 2's own
    explicit requirement ("excluding legitimate zero-desired-count
    cases"): a deliberately scaled-to-zero service is never a failure.

    Correction round, Issue 5: `running_count is None` (genuinely
    unknown -- not collected, or dropped by an incomplete observation)
    is NEVER substituted with 0 -- doing so previously made "we don't
    know how many tasks are running" indistinguishable from "zero
    tasks are running", which could promote missing data straight to
    a CONFIRMED shortfall. Unknown running_count is reported as its
    own INSUFFICIENT_EVIDENCE case instead.

    A running_count shortfall during an IN_PROGRESS rollout is
    INSUFFICIENT_EVIDENCE (a deployment genuinely takes time); a
    shortfall with a FAILED rollout, or a genuine CURRENT mismatch
    with no rollout in progress, is CONFIRMED -- described ONLY as
    what this single, point-in-time observation actually shows.
    `desired_count`/`running_count` are themselves point-in-time
    counts from ONE API call, never a time series this process has
    actually observed more than once -- duration ("sustained") and
    causation are never invented; only the current, observed mismatch
    is reported."""
    events = cloudtrail_events or []
    findings: list[AwsDetectionFinding] = []
    for svc in services:
        if not svc.desired_count:
            continue

        resource_id = f"{svc.cluster_arn}/{svc.service_name}"
        if svc.running_count is None:
            findings.append(
                AwsDetectionFinding(
                    detector_id="ecs_service_task_degradation",
                    resource_kind="EcsService",
                    account_id=account_id,
                    region=region,
                    resource_id=resource_id,
                    result=AwsDetectionResult.INSUFFICIENT_EVIDENCE,
                    evidence={
                        "desired_count": str(svc.desired_count),
                        "running_count": "",
                        "deployment_rollout_state": svc.deployment_rollout_state or "",
                    },
                    decision_rationale=(
                        f"service {svc.service_name!r} has a desired_count of {svc.desired_count}, but its "
                        "running_count was not available in this observation"
                    ),
                    uncertainty_notes=(
                        "a missing running_count is never treated as zero -- a genuine task shortfall cannot "
                        "be confirmed without it"
                    ),
                )
            )
            continue

        running = svc.running_count
        if running >= svc.desired_count:
            continue

        supporting = _events_for_resource(events, svc.service_name) + _events_for_resource(events, svc.cluster_arn)
        evidence = {
            "desired_count": str(svc.desired_count),
            "running_count": str(running),
            "pending_count": str(svc.pending_count) if svc.pending_count is not None else "",
            "deployment_rollout_state": svc.deployment_rollout_state or "",
            "recent_events": "; ".join(svc.recent_events[:5]),
        }

        if svc.deployment_rollout_state == "IN_PROGRESS":
            findings.append(
                AwsDetectionFinding(
                    detector_id="ecs_service_task_degradation",
                    resource_kind="EcsService",
                    account_id=account_id,
                    region=region,
                    resource_id=resource_id,
                    result=AwsDetectionResult.INSUFFICIENT_EVIDENCE,
                    evidence=evidence,
                    decision_rationale=(
                        f"service {svc.service_name!r} has {running}/{svc.desired_count} tasks running, but a "
                        "deployment rollout is still IN_PROGRESS -- a service can be briefly short of its "
                        "desired count during a normal, still-progressing deployment"
                    ),
                    uncertainty_notes="an in-progress rollout alone does not confirm a genuine degradation",
                )
            )
            continue

        # Correction round, Issue 5: describes ONLY what this single,
        # point-in-time observation actually shows -- never "sustained"
        # or any other duration claim (this process has not observed
        # this service more than once here), and never a causation
        # claim beyond the bare fact of the mismatch itself.
        rationale = (
            f"service {svc.service_name!r} currently reports {running}/{svc.desired_count} tasks running at this "
            "single observation"
            + (
                ", with its most recently recorded deployment rollout state FAILED"
                if svc.deployment_rollout_state == "FAILED"
                else ", with no deployment rollout currently in progress"
            )
        )
        uncertainty_bits = [
            "this reflects ONE point-in-time observation -- how long this mismatch has persisted, and its "
            "cause, are not established by this finding alone"
        ]
        if supporting:
            uncertainty_bits.append(
                "a nearby CloudTrail management event (if any) is supporting context only -- temporal "
                "proximity alone does not establish that it caused this mismatch"
            )
        findings.append(
            AwsDetectionFinding(
                detector_id="ecs_service_task_degradation",
                resource_kind="EcsService",
                account_id=account_id,
                region=region,
                resource_id=resource_id,
                result=AwsDetectionResult.CONFIRMED,
                evidence=evidence,
                supporting_change_events=_format_supporting_events(supporting),
                decision_rationale=rationale,
                uncertainty_notes="; ".join(uncertainty_bits),
            )
        )
    return findings
