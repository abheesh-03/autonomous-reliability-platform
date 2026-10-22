"""Phase 13, Gate 2: pure, deterministic detector-logic unit tests
against already-collected/already-parsed observations -- no I/O, no
client, mirrors `test_kubernetes_detectors.py`'s own structure."""

from detectors.aws.collector import _parse_cloudtrail_events
from detectors.aws.detectors import (
    detect_cloudwatch_alarms_in_alarm_state,
    detect_ec2_failed_status_checks,
    detect_ecs_service_task_degradation,
)
from detectors.schemas.aws import (
    AwsDetectionResult,
    CloudWatchAlarmObservation,
    Ec2InstanceObservation,
    EcsServiceObservation,
)

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"


# ---------------------------------------------------------------------
# A. CloudWatch alarm state
# ---------------------------------------------------------------------


def test_alarm_state_confirmed():
    alarm = CloudWatchAlarmObservation(alarm_name="high-5xx", state_value="ALARM", state_reason="Threshold crossed")
    findings = detect_cloudwatch_alarms_in_alarm_state([alarm], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.CONFIRMED
    assert findings[0].resource_id == "high-5xx"


def test_alarm_state_ok_produces_no_finding():
    alarm = CloudWatchAlarmObservation(alarm_name="healthy", state_value="OK")
    assert detect_cloudwatch_alarms_in_alarm_state([alarm], ACCOUNT_ID, REGION) == []


def test_alarm_state_insufficient_data_is_insufficient_evidence():
    alarm = CloudWatchAlarmObservation(alarm_name="new-alarm", state_value="INSUFFICIENT_DATA")
    findings = detect_cloudwatch_alarms_in_alarm_state([alarm], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE


def test_alarm_supporting_cloudtrail_event_is_attached_but_never_asserted_as_cause():
    alarm = CloudWatchAlarmObservation(alarm_name="high-5xx", state_value="ALARM")
    raw_events = [{"EventId": "e1", "EventName": "UpdateAlarm", "Username": "alice", "EventTime": "2026-04-01T09:00:00Z", "Resources": [{"ResourceName": "high-5xx"}]}]
    events, _ = _parse_cloudtrail_events(raw_events)
    findings = detect_cloudwatch_alarms_in_alarm_state([alarm], ACCOUNT_ID, REGION, events)
    assert findings[0].supporting_change_events == ["UpdateAlarm by alice at 2026-04-01T09:00:00Z"]
    assert findings[0].uncertainty_notes is not None
    assert "does not establish" in findings[0].uncertainty_notes


# ---------------------------------------------------------------------
# B. EC2 impaired vs intentional shutdown
# ---------------------------------------------------------------------


def test_ec2_running_impaired_is_confirmed():
    instance = Ec2InstanceObservation(instance_id="i-1", state_name="running", instance_status="impaired", system_status="ok")
    findings = detect_ec2_failed_status_checks([instance], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.CONFIRMED


def test_ec2_running_healthy_produces_no_finding():
    instance = Ec2InstanceObservation(instance_id="i-1", state_name="running", instance_status="ok", system_status="ok")
    assert detect_ec2_failed_status_checks([instance], ACCOUNT_ID, REGION) == []


def test_ec2_stopped_instance_is_never_a_failure_regardless_of_status():
    """Gate 2: intentional shutdowns exist and must never be
    misclassified -- a stopped instance produces NO finding even if
    (implausibly) its last-known status fields were 'impaired'."""
    instance = Ec2InstanceObservation(instance_id="i-1", state_name="stopped", instance_status="impaired")
    assert detect_ec2_failed_status_checks([instance], ACCOUNT_ID, REGION) == []


def test_ec2_running_with_unknown_status_is_insufficient_evidence_never_confirmed():
    instance = Ec2InstanceObservation(instance_id="i-1", state_name="running", instance_status=None, system_status=None)
    findings = detect_ec2_failed_status_checks([instance], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE


def test_ec2_pending_instance_is_never_a_failure():
    instance = Ec2InstanceObservation(instance_id="i-1", state_name="pending")
    assert detect_ec2_failed_status_checks([instance], ACCOUNT_ID, REGION) == []


# ---------------------------------------------------------------------
# C. ECS desired/running degradation vs desired=0
# ---------------------------------------------------------------------


def test_ecs_shortfall_with_completed_rollout_is_confirmed():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=1, deployment_rollout_state="COMPLETED")
    findings = detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.CONFIRMED


def test_ecs_shortfall_with_failed_rollout_is_confirmed():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=0, deployment_rollout_state="FAILED")
    findings = detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.CONFIRMED


def test_ecs_shortfall_with_in_progress_rollout_is_insufficient_evidence():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=1, deployment_rollout_state="IN_PROGRESS")
    findings = detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE


def test_ecs_missing_running_count_is_insufficient_evidence_never_confirmed():
    """Correction round, Issue 5: an unknown running_count must NEVER
    be substituted with zero and promoted to a confirmed shortfall."""
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=None)
    findings = detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE
    assert findings[0].evidence["running_count"] == ""


def test_ecs_missing_desired_count_is_never_a_failure():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="unknown", desired_count=None, running_count=None)
    assert detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION) == []


def test_ecs_confirmed_rationale_never_claims_a_sustained_or_causal_shortfall():
    """Correction round, Issue 5: a single point-in-time observation
    must never be described with duration ('sustained') or causation
    language it cannot support."""
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=1, deployment_rollout_state="COMPLETED")
    findings = detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION)
    assert len(findings) == 1
    assert "sustained" not in findings[0].decision_rationale.lower()
    assert "single observation" in findings[0].decision_rationale
    assert "not established" in findings[0].uncertainty_notes


def test_ecs_desired_zero_is_never_a_failure():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="scaled-down", desired_count=0, running_count=0)
    assert detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION) == []


def test_ecs_desired_none_is_never_a_failure():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="unknown", desired_count=None, running_count=0)
    assert detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION) == []


def test_ecs_running_meets_desired_is_never_a_failure():
    svc = EcsServiceObservation(cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/prod", service_name="checkout", desired_count=3, running_count=3)
    assert detect_ecs_service_task_degradation([svc], ACCOUNT_ID, REGION) == []


# ---------------------------------------------------------------------
# D. CloudTrail: missing/malformed data and redaction by omission
# ---------------------------------------------------------------------


def test_cloudtrail_malformed_item_is_skipped_never_fatal():
    raw_events = ["not-an-object", {"EventId": "e1", "EventName": "RunInstances"}]
    events, malformed_count = _parse_cloudtrail_events(raw_events)
    assert malformed_count == 1
    assert len(events) == 1
    assert events[0].event_name == "RunInstances"


def test_cloudtrail_event_missing_required_fields_is_skipped():
    raw_events = [{"EventId": "e1"}, {"EventName": "RunInstances"}]  # each missing the other required field
    events, malformed_count = _parse_cloudtrail_events(raw_events)
    assert events == []
    assert malformed_count == 2


def test_cloudtrail_parser_never_reads_the_raw_cloudtrailevent_blob():
    """Redaction by omission: even if the raw AWS response includes a
    'CloudTrailEvent' field carrying something sensitive-shaped (e.g.
    an access key id), this process never reads that field at all --
    it is structurally absent from the parsed observation."""
    raw_events = [
        {
            "EventId": "e1", "EventName": "ConsoleLogin", "Username": "alice",
            "CloudTrailEvent": '{"requestParameters": {"accessKeyId": "AKIAABCDEFGHIJKLMNOP"}}',
        }
    ]
    events, _ = _parse_cloudtrail_events(raw_events)
    assert len(events) == 1
    dumped = events[0].model_dump_json()
    assert "AKIAABCDEFGHIJKLMNOP" not in dumped
    assert "requestParameters" not in dumped
    assert "CloudTrailEvent" not in type(events[0]).model_fields
