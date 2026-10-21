"""Gate F: the single top-level entry point tying
`collect_and_detect` (I/O) and `build_findings_from_*` (pure) together,
plus a deterministic, human-readable investigation summary -- the
pipeline's own "READ-ONLY INVESTIGATION SUMMARY" stage."""

from dataclasses import dataclass, field
from datetime import datetime

from catalog.schemas.finding import FailureFinding
from detectors.clients.control_plane_client import ControlPlaneClient
from detectors.clients.kubernetes_client import KubernetesClient
from detectors.clients.prometheus_client import PrometheusClient
from detectors.clients.tempo_client import TempoClient
from detectors.kubernetes.findings import build_findings_from_kubernetes
from detectors.pipeline.findings import build_findings_from_anomalies, build_findings_from_invariant_violations
from detectors.pipeline.orchestrator import PipelineConfig, RawPipelineResult, collect_and_detect
from detectors.schemas.anomaly import AnomalyDetectionResult, DetectionResult
from detectors.schemas.correlation import CorrelationGroup, TentativeAssociation
from detectors.schemas.dependency import DependencyGraph, PropagationPath
from detectors.schemas.invariant import InvariantCheckReport, InvariantCheckResult
from detectors.schemas.kubernetes import CollectionResult, K8sDetectionFinding, K8sDetectionResult


@dataclass
class PipelineReport:
    findings: list[FailureFinding]
    anomaly_results: list[AnomalyDetectionResult]
    dependency_graph: DependencyGraph | None
    propagation_paths: list[PropagationPath]
    invariant_reports: list[InvariantCheckReport]
    k8s_collection_results: list[CollectionResult]
    k8s_findings: list[K8sDetectionFinding]
    correlation_groups: list[CorrelationGroup]
    tentative_associations: list[TentativeAssociation]
    checks_executed: list[str]
    checks_not_executed: list[tuple[str, str]]
    summary: str


def build_summary(raw: RawPipelineResult, findings: list[FailureFinding]) -> str:
    lines = [
        f"Investigation window: {raw.boundary.isoformat()} -> {raw.window_end.isoformat()} "
        f"(baseline since {raw.window_start.isoformat()})",
        f"Checks executed: {len(raw.checks_executed)}; checks NOT executed: {len(raw.checks_not_executed)}",
    ]
    for name, reason in raw.checks_not_executed:
        lines.append(f"  - NOT EXECUTED: {name} ({reason})")

    anomaly_count = sum(1 for r in raw.anomaly_results if r.result == DetectionResult.ANOMALY_DETECTED)
    insufficient_count = sum(1 for r in raw.anomaly_results if r.result == DetectionResult.INSUFFICIENT_DATA)
    unavailable_count = sum(1 for r in raw.anomaly_results if r.result == DetectionResult.TELEMETRY_UNAVAILABLE)
    lines.append(
        f"Anomaly checks run: {len(raw.anomaly_results)} ({anomaly_count} ANOMALY_DETECTED, "
        f"{insufficient_count} INSUFFICIENT_DATA, {unavailable_count} TELEMETRY_UNAVAILABLE)"
    )

    if raw.dependency_graph is not None:
        lines.append(
            f"Dependency graph: {len(raw.dependency_graph.edges)} observed edge(s) across "
            f"{raw.dependency_graph.traces_considered} trace(s) "
            f"({raw.dependency_graph.traces_with_cycles_skipped} skipped for cycles)"
        )
    if raw.propagation_paths:
        lines.append(f"Candidate propagation paths: {len(raw.propagation_paths)} (never an established root cause)")

    violated = sum(1 for r in raw.invariant_reports if r.result == InvariantCheckResult.VIOLATED)
    lines.append(f"Invariant checks run: {len(raw.invariant_reports)} ({violated} VIOLATED)")

    if raw.k8s_collection_results:
        outcomes = ", ".join(f"{cr.resource_kind}={cr.outcome.value}" for cr in raw.k8s_collection_results)
        confirmed = sum(1 for f in raw.k8s_findings if f.result == K8sDetectionResult.CONFIRMED)
        insufficient = sum(1 for f in raw.k8s_findings if f.result == K8sDetectionResult.INSUFFICIENT_EVIDENCE)
        lines.append(f"Kubernetes collection: {outcomes}")
        lines.append(f"Kubernetes findings: {len(raw.k8s_findings)} ({confirmed} CONFIRMED, {insufficient} INSUFFICIENT_EVIDENCE)")

    lines.append(f"Correlation groups: {len(raw.correlation_groups)}")
    lines.append(f"Tentative (weak, unmerged) associations: {len(raw.tentative_associations)}")
    lines.append(
        f"Failure findings produced: {len(findings)} (a catalog scenario match is never required to produce one)"
    )
    return "\n".join(lines)


async def run_pipeline(
    *,
    prometheus_client: PrometheusClient | None,
    tempo_client: TempoClient | None,
    control_plane_client: ControlPlaneClient | None,
    kubernetes_client: KubernetesClient | None = None,
    config: PipelineConfig = PipelineConfig(),
    now: datetime | None = None,
) -> PipelineReport:
    raw = await collect_and_detect(
        prometheus_client=prometheus_client,
        tempo_client=tempo_client,
        control_plane_client=control_plane_client,
        kubernetes_client=kubernetes_client,
        config=config,
        now=now,
    )
    collected_at = raw.window_end.isoformat()
    findings = (
        build_findings_from_anomalies(raw.anomaly_results, raw.propagation_paths, raw.correlation_group_by_item_id)
        + build_findings_from_invariant_violations(raw.invariant_reports)
        + build_findings_from_kubernetes(raw.k8s_findings, collected_at)
    )
    summary = build_summary(raw, findings)

    return PipelineReport(
        findings=findings,
        anomaly_results=raw.anomaly_results,
        dependency_graph=raw.dependency_graph,
        propagation_paths=raw.propagation_paths,
        invariant_reports=raw.invariant_reports,
        k8s_collection_results=raw.k8s_collection_results,
        k8s_findings=raw.k8s_findings,
        correlation_groups=raw.correlation_groups,
        tentative_associations=raw.tentative_associations,
        checks_executed=raw.checks_executed,
        checks_not_executed=raw.checks_not_executed,
        summary=summary,
    )
