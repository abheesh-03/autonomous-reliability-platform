"""Gate F: the unified investigation pipeline.

READ-ONLY TELEMETRY COLLECTION -> STATISTICAL ANOMALY DETECTION ->
TRACE + DEPENDENCY ANALYSIS -> BUSINESS INVARIANT CHECKS ->
KUBERNETES OBSERVATION (Phase 12A, additive, opt-in) ->
DETERMINISTIC INCIDENT CORRELATION -> EVIDENCE-GROUNDED FAILURE
FINDINGS -> READ-ONLY INVESTIGATION SUMMARY.

Every client argument is OPTIONAL: a missing client means that stage's
checks could not run at all, recorded in `checks_not_executed` with an
explicit reason -- never silently skipped, and never a reason to fail
the whole pipeline (partial results are always returned). Every stage
failure (a bounded client-level exception) is caught per-check, so one
unavailable source never prevents every other independent source from
still contributing its own findings.

Kubernetes observation (Phase 12A) is deliberately NOT fed into the
cross-system correlation engine in this round: the sandbox kind
cluster and the docker-compose Prometheus/Tempo/control-plane stack
are genuinely separate environments with no real shared trace id,
fingerprint, or observed dependency edge between them -- attempting to
correlate them would fabricate evidence that does not exist (see
`docs/architecture/phase-12a-kubernetes-observer.md`).

AWS observation (Phase 13) is additive, opt-in, and -- for the exact
same reason as Kubernetes above -- deliberately NOT fed into the
cross-system correlation engine: a real AWS account and this stack's
own sandbox/docker-compose services share no real trace id,
fingerprint, or observed dependency edge either (see
`docs/architecture/phase-13-aws-reliability-integration.md`)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from detectors.anomaly.detector import (
    detect_error_rate_deviation,
    detect_latency_deviation,
    detect_telemetry_pipeline_health,
)
from detectors.aws.collector import collect_cloudtrail_events, collect_cloudwatch_alarms, collect_ec2_instances, collect_ecs_services
from detectors.aws.detectors import (
    detect_cloudwatch_alarms_in_alarm_state,
    detect_ec2_failed_status_checks,
    detect_ecs_service_task_degradation,
)
from detectors.clients.aws_client import AwsClientProtocol
from detectors.clients.control_plane_client import ControlPlaneClient, ControlPlaneUnavailableError
from detectors.clients.kubernetes_client import KubernetesClient
from detectors.clients.prometheus_client import ALLOWED_SERVICES, PrometheusClient, PrometheusClientError, PrometheusUnavailableError
from detectors.clients.tempo_client import TempoClient, TempoClientError, TempoUnavailableError
from detectors.correlation.engine import correlate
from detectors.dependencies.graph import build_dependency_graph
from detectors.dependencies.propagation import build_propagation_paths
from detectors.invariants.lifecycle_checker import INVARIANT_DEFINITION, check_incident_lifecycle_consistency
from detectors.kubernetes.collector import collect_deployments, collect_events, collect_pods, collect_replicasets
from detectors.kubernetes.detectors import (
    detect_crash_loop_backoff,
    detect_deployment_rollout_failure,
    detect_image_pull_failures,
    detect_oom_killed,
    detect_pod_readiness_degradation,
)
from detectors.schemas.anomaly import AnomalyDetectionResult, DetectionResult
from detectors.schemas.aws import AwsCollectionOutcome, AwsCollectionResult, AwsDetectionFinding
from detectors.schemas.correlation import CorrelationGroup, CorrelationInput, TentativeAssociation
from detectors.schemas.dependency import DependencyGraph, PropagationPath
from detectors.schemas.invariant import InvariantCheckReport, InvariantCheckResult
from detectors.schemas.kubernetes import CollectionOutcome, CollectionResult, K8sDetectionFinding
from detectors.clients.aws_client import AwsIdentityMismatchError, AwsUnavailableError


@dataclass(frozen=True)
class PipelineConfig:
    services: tuple[str, ...] = tuple(sorted(ALLOWED_SERVICES))
    baseline_hours: float = 1.0
    observation_minutes: float = 10.0
    max_traces: int = 20
    max_incidents_for_invariant_check: int = 50


@dataclass
class RawPipelineResult:
    window_start: datetime
    boundary: datetime
    window_end: datetime
    anomaly_results: list[AnomalyDetectionResult] = field(default_factory=list)
    dependency_graph: DependencyGraph | None = None
    propagation_paths: list[PropagationPath] = field(default_factory=list)
    invariant_reports: list[InvariantCheckReport] = field(default_factory=list)
    k8s_collection_results: list[CollectionResult] = field(default_factory=list)
    k8s_findings: list[K8sDetectionFinding] = field(default_factory=list)
    aws_collection_results: list[AwsCollectionResult] = field(default_factory=list)
    aws_findings: list[AwsDetectionFinding] = field(default_factory=list)
    correlation_groups: list[CorrelationGroup] = field(default_factory=list)
    tentative_associations: list[TentativeAssociation] = field(default_factory=list)
    correlation_group_by_item_id: dict[str, str] = field(default_factory=dict)
    checks_executed: list[str] = field(default_factory=list)
    checks_not_executed: list[tuple[str, str]] = field(default_factory=list)


_USABLE_K8S_OUTCOMES = (CollectionOutcome.SUCCESS, CollectionOutcome.EMPTY, CollectionOutcome.PARTIAL)
_USABLE_AWS_OUTCOMES = (AwsCollectionOutcome.SUCCESS, AwsCollectionOutcome.EMPTY, AwsCollectionOutcome.PARTIAL)


async def collect_and_detect(
    *,
    prometheus_client: PrometheusClient | None,
    tempo_client: TempoClient | None,
    control_plane_client: ControlPlaneClient | None,
    kubernetes_client: KubernetesClient | None = None,
    aws_client: AwsClientProtocol | None = None,
    config: PipelineConfig = PipelineConfig(),
    now: datetime | None = None,
) -> RawPipelineResult:
    now = now or datetime.now(UTC)
    observation_end = now
    boundary = observation_end - timedelta(minutes=config.observation_minutes)
    baseline_start = boundary - timedelta(hours=config.baseline_hours)

    result = RawPipelineResult(window_start=baseline_start, boundary=boundary, window_end=observation_end)

    # -- STATISTICAL ANOMALY DETECTION --
    if prometheus_client is None:
        result.checks_not_executed.append(("anomaly_detection", "no Prometheus client was supplied"))
    else:
        for service in config.services:
            for name, coro in (
                ("error_rate_deviation", detect_error_rate_deviation(prometheus_client, service, baseline_start, boundary, observation_end)),
                ("latency_deviation", detect_latency_deviation(prometheus_client, service, baseline_start, boundary, observation_end)),
            ):
                try:
                    result.anomaly_results.append(await coro)
                    result.checks_executed.append(f"{name}:{service}")
                except (PrometheusClientError, PrometheusUnavailableError) as exc:
                    result.checks_not_executed.append((f"{name}:{service}", str(exc)))
        try:
            result.anomaly_results.append(
                await detect_telemetry_pipeline_health(prometheus_client, boundary, observation_end, baseline_start)
            )
            result.checks_executed.append("telemetry_pipeline_health")
        except (PrometheusClientError, PrometheusUnavailableError) as exc:
            result.checks_not_executed.append(("telemetry_pipeline_health", str(exc)))

    # -- TRACE + DEPENDENCY ANALYSIS --
    if tempo_client is None:
        result.checks_not_executed.append(("dependency_graph", "no Tempo client was supplied"))
    else:
        try:
            trace_ids = await tempo_client.search_window(
                int(baseline_start.timestamp()), int(observation_end.timestamp()), max_traces=config.max_traces
            )
            trace_results = []
            for trace_id in trace_ids:
                detail = await tempo_client.get_trace_detail(trace_id)
                if detail is not None:
                    trace_results.append(detail)
            result.dependency_graph = build_dependency_graph(trace_results, baseline_start, observation_end)
            result.checks_executed.append("dependency_graph")

            anomalous_services: dict[str, list[str]] = {}
            for r in result.anomaly_results:
                if r.result == DetectionResult.ANOMALY_DETECTED:
                    anomalous_services.setdefault(r.service, []).append(r.detector_id)
            result.propagation_paths = build_propagation_paths(result.dependency_graph, anomalous_services)
            result.checks_executed.append("propagation_paths")
        except (TempoClientError, TempoUnavailableError) as exc:
            result.checks_not_executed.append(("dependency_graph", str(exc)))

    # -- BUSINESS INVARIANT CHECKS --
    if control_plane_client is None:
        result.checks_not_executed.append((INVARIANT_DEFINITION.invariant_id, "no control-plane client was supplied"))
    else:
        try:
            incidents = await control_plane_client.list_incidents(max_incidents=config.max_incidents_for_invariant_check)
            report = await check_incident_lifecycle_consistency(
                control_plane_client, [i.id for i in incidents], baseline_start, observation_end
            )
            result.invariant_reports.append(report)
            if report.result == InvariantCheckResult.SOURCE_UNAVAILABLE:
                result.checks_not_executed.append((INVARIANT_DEFINITION.invariant_id, report.explanation))
            else:
                result.checks_executed.append(INVARIANT_DEFINITION.invariant_id)
        except ControlPlaneUnavailableError as exc:
            result.checks_not_executed.append((INVARIANT_DEFINITION.invariant_id, str(exc)))

    # -- KUBERNETES OBSERVATION (Phase 12A, additive, opt-in) --
    if kubernetes_client is None:
        result.checks_not_executed.append(("kubernetes_observation", "no Kubernetes client was supplied"))
    else:
        pods_result, pods = await collect_pods(kubernetes_client)
        deployments_result, deployments = await collect_deployments(kubernetes_client)
        _replicasets_result, _replicasets = await collect_replicasets(kubernetes_client)
        events_result, events = await collect_events(kubernetes_client)
        result.k8s_collection_results = [pods_result, deployments_result, _replicasets_result, events_result]

        for cr in result.k8s_collection_results:
            check_name = f"kubernetes_collect_{cr.resource_kind.lower()}"
            if cr.outcome in _USABLE_K8S_OUTCOMES:
                result.checks_executed.append(check_name)
                if cr.outcome == CollectionOutcome.PARTIAL:
                    # Correction round (Issue 1): classification still
                    # runs on whatever real evidence WAS collected, but
                    # incomplete coverage is propagated into pipeline
                    # status explicitly -- never silently absorbed into
                    # an unqualified "executed" result.
                    result.checks_not_executed.append((f"{check_name}_complete_coverage", f"partial collection: {cr.detail}"))
            else:
                result.checks_not_executed.append((check_name, f"{cr.outcome.value}: {cr.detail}"))

        # Classification only ever runs on a SUCCESS/EMPTY/PARTIAL
        # collection -- a failed (UNAVAILABLE/FORBIDDEN/MALFORMED/
        # NOT_FOUND) pod collection must NEVER be treated as "zero pods
        # exist" (a false healthy result). PARTIAL still carries real,
        # preserved evidence (Issues 1/2), so classification still runs
        # on it -- the incomplete-coverage caveat is propagated
        # separately, above, into `checks_not_executed`, never silently
        # dropped. Events are best-effort supporting evidence only, so
        # a failed events collection still lets pod-based classification
        # proceed (with empty supporting_event_reasons, never
        # fabricated ones).
        events_usable = events if events_result.outcome in _USABLE_K8S_OUTCOMES else []

        if pods_result.outcome in _USABLE_K8S_OUTCOMES:
            result.k8s_findings.extend(detect_image_pull_failures(pods, events_usable))
            result.k8s_findings.extend(detect_crash_loop_backoff(pods, events_usable))
            result.k8s_findings.extend(detect_oom_killed(pods))
            result.k8s_findings.extend(detect_pod_readiness_degradation(pods, events_usable))
            result.checks_executed.append("kubernetes_pod_detectors")
        else:
            result.checks_not_executed.append(
                ("kubernetes_pod_detectors", f"pod collection outcome was {pods_result.outcome.value}, not SUCCESS/EMPTY")
            )

        if deployments_result.outcome in _USABLE_K8S_OUTCOMES:
            result.k8s_findings.extend(detect_deployment_rollout_failure(deployments))
            result.checks_executed.append("kubernetes_deployment_detector")
        else:
            result.checks_not_executed.append(
                ("kubernetes_deployment_detector", f"deployment collection outcome was {deployments_result.outcome.value}")
            )

    # -- AWS OBSERVATION (Phase 13, additive, opt-in) --
    if aws_client is None:
        result.checks_not_executed.append(("aws_observation", "no AWS client was supplied"))
    else:
        try:
            await aws_client.verify_identity()
        except AwsIdentityMismatchError as exc:
            # Fail closed on the WHOLE AWS stage -- an account mismatch
            # means every subsequent call here could be observing the
            # wrong AWS account entirely; never silently proceed.
            result.checks_not_executed.append(("aws_observation", f"identity verification failed: {exc}"))
            aws_client = None  # type: ignore[assignment]
        except AwsUnavailableError as exc:
            result.checks_not_executed.append(("aws_observation", f"identity verification unavailable: {exc}"))
            aws_client = None  # type: ignore[assignment]

    if aws_client is not None:
        alarms_result, alarms = await collect_cloudwatch_alarms(aws_client)
        instances_result, instances = await collect_ec2_instances(aws_client)
        services_result, services = await collect_ecs_services(aws_client)
        cloudtrail_result, cloudtrail_events = await collect_cloudtrail_events(aws_client, start_time=boundary, end_time=observation_end)
        result.aws_collection_results = [alarms_result, instances_result, services_result, cloudtrail_result]

        for cr in result.aws_collection_results:
            check_name = f"aws_collect_{cr.resource_kind.lower()}"
            if cr.outcome in _USABLE_AWS_OUTCOMES:
                result.checks_executed.append(check_name)
                if cr.outcome == AwsCollectionOutcome.PARTIAL:
                    result.checks_not_executed.append((f"{check_name}_complete_coverage", f"partial collection: {cr.detail}"))
            else:
                result.checks_not_executed.append((check_name, f"{cr.outcome.value}: {cr.detail}"))

        # CloudTrail is best-effort SUPPORTING evidence only (Gate 2:
        # "never automatically assumed to be the root cause") -- a
        # failed CloudTrail collection never blocks the other three
        # detectors; they simply proceed with no supporting change
        # events attached (never fabricated ones).
        cloudtrail_usable = cloudtrail_events if cloudtrail_result.outcome in _USABLE_AWS_OUTCOMES else []

        if alarms_result.outcome in _USABLE_AWS_OUTCOMES:
            result.aws_findings.extend(detect_cloudwatch_alarms_in_alarm_state(alarms, aws_client.scope.account_id, aws_client.scope.region, cloudtrail_usable))
            result.checks_executed.append("aws_cloudwatch_detector")
        else:
            result.checks_not_executed.append(("aws_cloudwatch_detector", f"alarm collection outcome was {alarms_result.outcome.value}"))

        if instances_result.outcome in _USABLE_AWS_OUTCOMES:
            result.aws_findings.extend(detect_ec2_failed_status_checks(instances, aws_client.scope.account_id, aws_client.scope.region, cloudtrail_usable))
            result.checks_executed.append("aws_ec2_detector")
        else:
            result.checks_not_executed.append(("aws_ec2_detector", f"EC2 collection outcome was {instances_result.outcome.value}"))

        if services_result.outcome in _USABLE_AWS_OUTCOMES:
            result.aws_findings.extend(detect_ecs_service_task_degradation(services, aws_client.scope.account_id, aws_client.scope.region, cloudtrail_usable))
            result.checks_executed.append("aws_ecs_detector")
        else:
            result.checks_not_executed.append(("aws_ecs_detector", f"ECS collection outcome was {services_result.outcome.value}"))

    # -- DETERMINISTIC INCIDENT CORRELATION --
    correlation_items: list[CorrelationInput] = []
    for r in result.anomaly_results:
        if r.result == DetectionResult.ANOMALY_DETECTED:
            correlation_items.append(
                CorrelationInput(
                    item_id=f"anomaly:{r.detector_id}:{r.service}",
                    kind="anomaly",
                    services=frozenset({r.service}),
                    window_start=boundary,
                    window_end=observation_end,
                )
            )
    for report in result.invariant_reports:
        if report.result == InvariantCheckResult.VIOLATED:
            for v in report.violations:
                correlation_items.append(
                    CorrelationInput(
                        item_id=f"invariant:{report.invariant_id}:{v.subject_id}",
                        kind="invariant_violation",
                        services=frozenset({"control-plane"}),
                        window_start=baseline_start,
                        window_end=observation_end,
                    )
                )
    if correlation_items:
        result.correlation_groups, result.tentative_associations = correlate(correlation_items, result.dependency_graph)
        for group in result.correlation_groups:
            for item_id in group.grouped_finding_ids:
                result.correlation_group_by_item_id[item_id] = group.correlation_group_id
    result.checks_executed.append("correlation")

    return result
