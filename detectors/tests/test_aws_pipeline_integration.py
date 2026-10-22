"""Phase 13, Gate 1-3: end-to-end AWS observation integration tests --
real pipeline code (`detectors.pipeline.run.run_pipeline`), a plain
in-test fake implementing `AwsClientProtocol`, NEVER `Boto3AwsClient`
and NEVER a real network/credential dependency anywhere in this file.
Mirrors `test_kubernetes_pipeline_integration.py`'s own structure and
intent exactly -- this IS Gate 3's "deterministic offline replay using
captured-shape synthetic AWS fixtures" requirement, satisfied the same
way Phase 12A satisfied it for Kubernetes (a Python-level fake driving
the real pipeline, not the CLI's `replay --fixture` JSON mechanism,
which never included Kubernetes either -- see
`detectors/cli/fixture_loader.py`)."""

from datetime import UTC, datetime, timedelta

from detectors.clients.aws_client import (
    AwsForbiddenError,
    AwsIdentityMismatchError,
    AwsObserverScope,
    AwsUnavailableError,
)
from detectors.pipeline.run import run_pipeline
from detectors.schemas.aws import AwsCollectionOutcome

NOW = datetime.now(UTC) - timedelta(minutes=1)
ACCOUNT_ID = "123456789012"
REGION = "us-east-1"


class FakeAwsClient:
    """A plain, hand-rolled fake implementing `AwsClientProtocol` --
    never boto3, never a network call. `raise_error`, if set, is raised
    by every method (modeling a single failure mode uniformly for a
    given test)."""

    def __init__(
        self,
        scope: AwsObserverScope,
        *,
        live_account_id: str | None = None,
        alarms: list[dict] | None = None,
        instances: list[dict] | None = None,
        instance_statuses: list[dict] | None = None,
        ecs_services_by_cluster: dict[str, list[dict]] | None = None,
        cloudtrail_events: list[dict] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._scope = scope
        self._live_account_id = live_account_id if live_account_id is not None else scope.account_id
        self._alarms = alarms or []
        self._instances = instances or []
        self._instance_statuses = instance_statuses or []
        self._ecs_services_by_cluster = ecs_services_by_cluster or {}
        self._cloudtrail_events = cloudtrail_events or []
        self._raise_error = raise_error

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def verify_identity(self) -> str:
        if self._raise_error:
            raise self._raise_error
        if self._live_account_id != self._scope.account_id:
            raise AwsIdentityMismatchError(
                f"configured account_id {self._scope.account_id!r} does not match live account {self._live_account_id!r}"
            )
        return self._live_account_id

    async def describe_alarms(self, *, next_token: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        return {"MetricAlarms": self._alarms, "NextToken": None}

    async def get_metric_data(self, queries: list[dict], *, start_time=None, end_time=None) -> dict:
        if self._raise_error:
            raise self._raise_error
        return {"MetricDataResults": []}

    async def lookup_events(self, *, start_time, end_time, next_token: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        return {"Events": self._cloudtrail_events, "NextToken": None}

    async def describe_instances(self, *, next_token: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        return {"Reservations": [{"Instances": self._instances}], "NextToken": None}

    async def describe_instance_status(self, *, next_token: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        return {"InstanceStatuses": self._instance_statuses, "NextToken": None}

    async def list_services(self, cluster: str, *, next_token: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        names = [s["serviceName"] for s in self._ecs_services_by_cluster.get(cluster, [])]
        return {"serviceArns": names, "nextToken": None}

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        if self._raise_error:
            raise self._raise_error
        all_services = self._ecs_services_by_cluster.get(cluster, [])
        matched = [s for s in all_services if s["serviceName"] in service_names]
        missing = [n for n in service_names if n not in {s["serviceName"] for s in all_services}]
        return {"services": matched, "failures": [{"arn": m, "reason": "MISSING"} for m in missing]}


def _scope(**overrides) -> AwsObserverScope:
    fields = {"account_id": ACCOUNT_ID, "region": REGION}
    fields.update(overrides)
    return AwsObserverScope(**fields)


def _alarm(name, state="ALARM"):
    return {"AlarmName": name, "AlarmArn": f"arn:aws:cloudwatch:{REGION}:{ACCOUNT_ID}:alarm:{name}", "StateValue": state, "StateReason": "reason", "StateUpdatedTimestamp": NOW}


def _instance(instance_id, state="running", instance_status=None, system_status=None):
    rec = {"InstanceId": instance_id, "State": {"Name": state}}
    status = {"InstanceId": instance_id, "InstanceState": {"Name": state}}
    if instance_status:
        status["InstanceStatus"] = {"Status": instance_status}
    if system_status:
        status["SystemStatus"] = {"Status": system_status}
    return rec, status


def _ecs_service(name, cluster_arn, desired=1, running=1, rollout_state="COMPLETED"):
    return {
        "serviceName": name, "clusterArn": cluster_arn, "status": "ACTIVE",
        "desiredCount": desired, "runningCount": running, "pendingCount": 0,
        "deployments": [{"status": "PRIMARY", "rolloutState": rollout_state}],
        "events": [],
    }


# ---------------------------------------------------------------------
# No AWS client supplied -- honest "not executed", never a failure of
# other stages.
# ---------------------------------------------------------------------


async def test_no_aws_client_means_not_executed_never_a_failure_of_other_stages():
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=None, now=NOW)
    assert ("aws_observation", "no AWS client was supplied") in report.checks_not_executed
    assert report.aws_findings == []
    assert report.aws_collection_results == []
    assert report.summary


# ---------------------------------------------------------------------
# Identity verification -- fail closed on account mismatch
# ---------------------------------------------------------------------


async def test_account_mismatch_blocks_the_whole_aws_stage():
    scope = _scope(enrolled_alarm_names=("my-alarm",))
    client = FakeAwsClient(scope, live_account_id="999999999999", alarms=[_alarm("my-alarm")])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []
    assert report.aws_collection_results == []
    assert any("identity verification failed" in reason for name, reason in report.checks_not_executed if name == "aws_observation")


async def test_identity_verification_unavailable_blocks_the_whole_aws_stage():
    scope = _scope(enrolled_alarm_names=("my-alarm",))
    client = FakeAwsClient(scope, raise_error=AwsUnavailableError("network down"))
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []
    assert report.aws_collection_results == []


# ---------------------------------------------------------------------
# CloudWatch alarms end to end
# ---------------------------------------------------------------------


async def test_cloudwatch_alarm_in_alarm_state_produces_a_real_finding_end_to_end():
    scope = _scope(enrolled_alarm_names=("checkout-high-error-rate",))
    client = FakeAwsClient(scope, alarms=[_alarm("checkout-high-error-rate", state="ALARM")])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)

    assert len(report.aws_findings) == 1
    assert report.aws_findings[0].detector_id == "cloudwatch_alarm_in_alarm_state"
    assert len(report.findings) == 1
    assert report.findings[0].observed_service_or_resource == f"aws/{ACCOUNT_ID}/{REGION}/CloudWatchAlarm/checkout-high-error-rate"
    assert report.findings[0].candidate_known_scenario_matches == []
    assert report.findings[0].remediation_proposals == []


async def test_cloudwatch_alarm_ok_produces_zero_findings():
    scope = _scope(enrolled_alarm_names=("healthy-alarm",))
    client = FakeAwsClient(scope, alarms=[_alarm("healthy-alarm", state="OK")])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []
    collection = {cr.resource_kind: cr.outcome for cr in report.aws_collection_results}
    assert collection["CloudWatchAlarm"] == AwsCollectionOutcome.SUCCESS


async def test_cloudwatch_alarm_insufficient_data_produces_an_insufficient_evidence_finding():
    scope = _scope(enrolled_alarm_names=("new-alarm",))
    client = FakeAwsClient(scope, alarms=[_alarm("new-alarm", state="INSUFFICIENT_DATA")])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert len(report.aws_findings) == 1
    from detectors.schemas.aws import AwsDetectionResult

    assert report.aws_findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------
# EC2 impaired vs intentional shutdown
# ---------------------------------------------------------------------


async def test_ec2_impaired_running_instance_is_confirmed():
    instance, status = _instance("i-0123456789abcdef0", state="running", instance_status="impaired", system_status="ok")
    scope = _scope(enrolled_instance_ids=("i-0123456789abcdef0",))
    client = FakeAwsClient(scope, instances=[instance], instance_statuses=[status])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert len(report.aws_findings) == 1
    assert report.aws_findings[0].detector_id == "ec2_failed_status_check"


async def test_ec2_intentionally_stopped_instance_produces_zero_findings():
    instance, status = _instance("i-0123456789abcdef0", state="stopped")
    scope = _scope(enrolled_instance_ids=("i-0123456789abcdef0",))
    client = FakeAwsClient(scope, instances=[instance], instance_statuses=[status])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []


async def test_ec2_healthy_running_instance_produces_zero_findings():
    instance, status = _instance("i-0123456789abcdef0", state="running", instance_status="ok", system_status="ok")
    scope = _scope(enrolled_instance_ids=("i-0123456789abcdef0",))
    client = FakeAwsClient(scope, instances=[instance], instance_statuses=[status])
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []


# ---------------------------------------------------------------------
# ECS desired-vs-running degradation vs desired=0
# ---------------------------------------------------------------------


async def test_ecs_service_task_degradation_is_confirmed():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    svc = _ecs_service("checkout", cluster_arn, desired=3, running=1, rollout_state="COMPLETED")
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = FakeAwsClient(scope, ecs_services_by_cluster={"prod": [svc]})
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert len(report.aws_findings) == 1
    assert report.aws_findings[0].detector_id == "ecs_service_task_degradation"


async def test_ecs_service_zero_desired_count_produces_zero_findings():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    svc = _ecs_service("scaled-down", cluster_arn, desired=0, running=0)
    scope = _scope(enrolled_ecs_services=(("prod", "scaled-down"),))
    client = FakeAwsClient(scope, ecs_services_by_cluster={"prod": [svc]})
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []


async def test_ecs_service_in_progress_rollout_shortfall_is_insufficient_evidence():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    svc = _ecs_service("rolling", cluster_arn, desired=3, running=1, rollout_state="IN_PROGRESS")
    scope = _scope(enrolled_ecs_services=(("prod", "rolling"),))
    client = FakeAwsClient(scope, ecs_services_by_cluster={"prod": [svc]})
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert len(report.aws_findings) == 1
    from detectors.schemas.aws import AwsDetectionResult

    assert report.aws_findings[0].result == AwsDetectionResult.INSUFFICIENT_EVIDENCE


async def test_enrolled_ecs_cluster_without_a_named_service_discovers_services_via_list_services():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    svc = _ecs_service("checkout", cluster_arn, desired=2, running=0, rollout_state="FAILED")
    scope = _scope(enrolled_ecs_clusters=("prod",))
    client = FakeAwsClient(scope, ecs_services_by_cluster={"prod": [svc]})
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert len(report.aws_findings) == 1


# ---------------------------------------------------------------------
# Forbidden / unavailable never produce a false healthy result
# ---------------------------------------------------------------------


async def test_forbidden_aws_api_never_produces_a_false_healthy_result():
    scope = _scope(enrolled_alarm_names=("my-alarm",))
    client = FakeAwsClient(scope)
    client._raise_error = None  # identity check succeeds
    client.describe_alarms = _raise_forbidden  # type: ignore[method-assign]
    report = await run_pipeline(prometheus_client=None, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.aws_findings == []
    assert any(cr.outcome == AwsCollectionOutcome.FORBIDDEN for cr in report.aws_collection_results)
    assert any("aws_cloudwatch_detector" in name for name, _ in report.checks_not_executed)


async def _raise_forbidden(*, next_token=None):
    raise AwsForbiddenError("AWS API returned AccessDenied")


# ---------------------------------------------------------------------
# CloudTrail/correlation
# ---------------------------------------------------------------------


async def test_aws_findings_are_never_auto_correlated_with_prometheus():
    import httpx

    from detectors.clients.prometheus_client import PrometheusClient

    def prom_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    scope = _scope(enrolled_alarm_names=("my-alarm",))
    client = FakeAwsClient(scope, alarms=[_alarm("my-alarm", state="ALARM")])
    prom_client = PrometheusClient("http://prometheus.invalid", transport=httpx.MockTransport(prom_handler))
    report = await run_pipeline(prometheus_client=prom_client, tempo_client=None, control_plane_client=None, aws_client=client, now=NOW)
    assert report.correlation_groups == []
