"""Gate F: the unified investigation pipeline.

READ-ONLY TELEMETRY COLLECTION -> STATISTICAL ANOMALY DETECTION ->
TRACE + DEPENDENCY ANALYSIS -> BUSINESS INVARIANT CHECKS ->
DETERMINISTIC INCIDENT CORRELATION -> EVIDENCE-GROUNDED FAILURE
FINDINGS -> READ-ONLY INVESTIGATION SUMMARY.

Every client argument is OPTIONAL: a missing client means that stage's
checks could not run at all, recorded in `checks_not_executed` with an
explicit reason -- never silently skipped, and never a reason to fail
the whole pipeline (partial results are always returned). Every stage
failure (a bounded client-level exception) is caught per-check, so one
unavailable source never prevents every other independent source from
still contributing its own findings."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from detectors.anomaly.detector import (
    detect_error_rate_deviation,
    detect_latency_deviation,
    detect_telemetry_pipeline_health,
)
from detectors.clients.control_plane_client import ControlPlaneClient, ControlPlaneUnavailableError
from detectors.clients.prometheus_client import ALLOWED_SERVICES, PrometheusClient, PrometheusClientError, PrometheusUnavailableError
from detectors.clients.tempo_client import TempoClient, TempoClientError, TempoUnavailableError
from detectors.correlation.engine import correlate
from detectors.dependencies.graph import build_dependency_graph
from detectors.dependencies.propagation import build_propagation_paths
from detectors.invariants.lifecycle_checker import INVARIANT_DEFINITION, check_incident_lifecycle_consistency
from detectors.schemas.anomaly import AnomalyDetectionResult, DetectionResult
from detectors.schemas.correlation import CorrelationGroup, CorrelationInput, TentativeAssociation
from detectors.schemas.dependency import DependencyGraph, PropagationPath
from detectors.schemas.invariant import InvariantCheckReport, InvariantCheckResult


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
    correlation_groups: list[CorrelationGroup] = field(default_factory=list)
    tentative_associations: list[TentativeAssociation] = field(default_factory=list)
    correlation_group_by_item_id: dict[str, str] = field(default_factory=dict)
    checks_executed: list[str] = field(default_factory=list)
    checks_not_executed: list[tuple[str, str]] = field(default_factory=list)


async def collect_and_detect(
    *,
    prometheus_client: PrometheusClient | None,
    tempo_client: TempoClient | None,
    control_plane_client: ControlPlaneClient | None,
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
