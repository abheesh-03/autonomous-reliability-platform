"""Gate E: the detector family registry -- a catalog of detection
CAPABILITIES, not implementations. Every entry here describes what a
family of detectors COULD look for and what it would need, never what
currently exists. `implemented=False` on every entry in this starting
registry is the honest, correct default: see
`catalog/coverage/tracker.py` (Gate F) for the ONLY mechanism that may
ever mark detection as actually validated, and it requires real
evidence to do so -- a registry entry alone never counts.

This is a STARTING set of families (per Gate E's own instruction: "not
closed/exhaustive"). Adding a new family never requires touching the
800 catalogued scenarios -- see
`test_registry.py::test_new_detector_family_can_be_added_without_
modifying_scenarios`.
"""

from pydantic import BaseModel, ConfigDict, Field


class DetectorFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector_family_id: str
    display_name: str
    intended_failure_signals: list[str]
    required_telemetry_sources: list[str]
    optional_telemetry_sources: list[str] = Field(default_factory=list)
    detection_prerequisites: list[str]
    expected_observation_schema: str
    supported_incident_categories: list[str]
    gaps_and_limitations: list[str]
    planned_verification_approach: str
    implemented: bool = False


DETECTOR_FAMILIES: tuple[DetectorFamily, ...] = (
    DetectorFamily(
        detector_family_id="availability_failures",
        display_name="Availability / timeout failures",
        intended_failure_signals=["error rate spikes", "connection timeouts", "health check failures"],
        required_telemetry_sources=["uptime/health-check probes", "load balancer error logs"],
        optional_telemetry_sources=["synthetic transaction monitors"],
        detection_prerequisites=["a defined health-check endpoint per service"],
        expected_observation_schema="time-windowed error-rate / probe-failure-rate series per service",
        supported_incident_categories=["Availability / timeouts"],
        gaps_and_limitations=["no implementation yet; no real signal processing exists"],
        planned_verification_approach="replay recorded outage fixtures against the detector offline",
    ),
    DetectorFamily(
        detector_family_id="api_error_rates",
        display_name="API error-rate anomalies",
        intended_failure_signals=["4xx/5xx rate increase", "new error code appearing"],
        required_telemetry_sources=["API gateway / service access logs"],
        detection_prerequisites=["consistent status-code logging across services"],
        expected_observation_schema="per-endpoint status-code distribution over time",
        supported_incident_categories=["Availability / timeouts", "External dependency / integration"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="unit tests against synthetic log fixtures with injected error bursts",
    ),
    DetectorFamily(
        detector_family_id="latency_anomalies",
        display_name="Latency anomalies",
        intended_failure_signals=["p95/p99 latency increase", "queue-age growth"],
        required_telemetry_sources=["distributed tracing spans", "request-duration histograms"],
        detection_prerequisites=["tracing instrumentation on the request path"],
        expected_observation_schema="per-endpoint latency percentile series vs. rolling baseline",
        supported_incident_categories=["Latency / capacity"],
        gaps_and_limitations=["no implementation yet; baseline-drift handling undesigned"],
        planned_verification_approach="replay recorded latency-degradation traces offline",
    ),
    DetectorFamily(
        detector_family_id="resource_saturation",
        display_name="Resource saturation",
        intended_failure_signals=["OOM kills", "disk pressure", "connection-pool exhaustion", "FD exhaustion"],
        required_telemetry_sources=["host/container resource metrics"],
        detection_prerequisites=["resource metrics exported per service instance"],
        expected_observation_schema="per-instance resource-utilization series with configured thresholds",
        supported_incident_categories=["Resource exhaustion"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic load-injection fixtures in a sandboxed test environment",
    ),
    DetectorFamily(
        detector_family_id="process_service_health",
        display_name="Process / service health",
        intended_failure_signals=["crash loops", "unexpected restarts", "liveness probe failures"],
        required_telemetry_sources=["orchestrator (e.g. container runtime) restart/event logs"],
        detection_prerequisites=["restart events are emitted with timestamps and reason codes"],
        expected_observation_schema="restart-count and reason-code series per service instance",
        supported_incident_categories=["Availability / timeouts", "Rollout / compatibility"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic crash-loop fixture replay",
    ),
    DetectorFamily(
        detector_family_id="deployment_regressions",
        display_name="Deployment regressions",
        intended_failure_signals=["error-rate or latency change correlated with a release boundary"],
        required_telemetry_sources=["deployment/release event log", "service error and latency metrics"],
        detection_prerequisites=["deployment events are timestamped and linkable to a service version"],
        expected_observation_schema="pre/post-release metric comparison windowed around a deploy event",
        supported_incident_categories=["Rollout / compatibility"],
        gaps_and_limitations=["no implementation yet; correlation != causation must be enforced explicitly"],
        planned_verification_approach="A/B replay of pre- and post-deploy synthetic metric fixtures",
    ),
    DetectorFamily(
        detector_family_id="database_performance",
        display_name="Database performance degradation",
        intended_failure_signals=["slow query rate increase", "lock wait growth", "connection pool saturation"],
        required_telemetry_sources=["database query/slow-log telemetry", "connection pool metrics"],
        detection_prerequisites=["slow-query logging enabled with duration thresholds"],
        expected_observation_schema="query-duration and lock-wait distributions over time",
        supported_incident_categories=["Latency / capacity", "Resource exhaustion"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic slow-query fixture replay",
    ),
    DetectorFamily(
        detector_family_id="database_integrity",
        display_name="Database integrity anomalies",
        intended_failure_signals=["constraint violations", "unexpected null/duplicate rates", "referential drift"],
        required_telemetry_sources=["database constraint/error logs", "data-quality check results"],
        detection_prerequisites=["data-quality checks exist and are run on a schedule"],
        expected_observation_schema="data-quality check pass/fail series with violation counts",
        supported_incident_categories=["Data integrity / mapping", "Consistency / duplicate processing"],
        gaps_and_limitations=["no implementation yet; never performs destructive writes to investigate"],
        planned_verification_approach="synthetic corrupted-row fixture against a non-production database",
    ),
    DetectorFamily(
        detector_family_id="concurrency_idempotency",
        display_name="Concurrency / idempotency violations",
        intended_failure_signals=["duplicate processing", "race-condition-induced inconsistent state"],
        required_telemetry_sources=["idempotency-key logs", "event/message processing logs"],
        detection_prerequisites=["requests/events carry a stable idempotency key"],
        expected_observation_schema="idempotency-key reuse and conflicting-outcome counts over time",
        supported_incident_categories=["Race / concurrent state", "Consistency / duplicate processing"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic concurrent-request replay fixture",
    ),
    DetectorFamily(
        detector_family_id="data_freshness",
        display_name="Data freshness / staleness",
        intended_failure_signals=["cache staleness", "stale replica reads", "delayed ETL/materialization"],
        required_telemetry_sources=["cache/replica lag metrics", "pipeline last-updated timestamps"],
        detection_prerequisites=["a defined freshness SLA per data source"],
        expected_observation_schema="age-since-last-update series per data source vs. SLA",
        supported_incident_categories=["Staleness / cache"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic stale-cache fixture replay",
    ),
    DetectorFamily(
        detector_family_id="async_event_processing",
        display_name="Async event-processing anomalies",
        intended_failure_signals=["out-of-order delivery", "consumer lag growth", "event loss"],
        required_telemetry_sources=["message broker consumer-lag metrics", "event sequence/offset logs"],
        detection_prerequisites=["events carry a sequence number or monotonic offset"],
        expected_observation_schema="consumer-lag and out-of-order-event-rate series per topic/queue",
        supported_incident_categories=["Event ordering / async workflow"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic out-of-order event-stream fixture replay",
    ),
    DetectorFamily(
        detector_family_id="queue_saturation_dlq",
        display_name="Queue saturation / dead-letter growth",
        intended_failure_signals=["queue depth growth", "DLQ message-rate increase"],
        required_telemetry_sources=["message broker queue-depth and DLQ metrics"],
        detection_prerequisites=["DLQ is configured and monitored per queue"],
        expected_observation_schema="queue-depth and DLQ-rate series per queue",
        supported_incident_categories=["Event ordering / async workflow", "Resource exhaustion"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic queue-backpressure fixture replay",
    ),
    DetectorFamily(
        detector_family_id="business_invariant_violations",
        display_name="Business invariant violations",
        intended_failure_signals=["a defined business rule is violated (e.g. balance mismatch, duplicate charge)"],
        required_telemetry_sources=["domain event logs", "ledger/state reconciliation reports"],
        detection_prerequisites=["the business invariant is formally defined and checkable from recorded events"],
        expected_observation_schema="invariant-check pass/fail series with violation detail",
        supported_incident_categories=["Financial / numeric correctness", "Consistency / duplicate processing"],
        gaps_and_limitations=[
            "no implementation yet; this family can NEVER authorize a corrective financial write on its own "
            "-- see Gate G"
        ],
        planned_verification_approach="synthetic reconciliation-mismatch fixture against a non-production ledger",
    ),
    DetectorFamily(
        detector_family_id="auth_anomalies",
        display_name="Authentication / authorization anomalies",
        intended_failure_signals=["auth failure rate spike", "privilege-check bypass pattern", "token anomalies"],
        required_telemetry_sources=["auth service logs", "access-control decision logs"],
        detection_prerequisites=["auth decisions are logged with outcome and principal"],
        expected_observation_schema="auth failure/success rate and decision-outcome series",
        supported_incident_categories=["Authentication / credentials", "Privacy / authorization"],
        gaps_and_limitations=["no implementation yet; never performs credential or access changes itself"],
        planned_verification_approach="synthetic credential-anomaly fixture replay",
    ),
    DetectorFamily(
        detector_family_id="upstream_dependency_failures",
        display_name="Upstream / external dependency failures",
        intended_failure_signals=["third-party API error-rate or latency increase", "circuit-breaker trips"],
        required_telemetry_sources=["outbound call logs/metrics per dependency"],
        detection_prerequisites=["outbound calls are tagged with a dependency identifier"],
        expected_observation_schema="per-dependency error-rate/latency series",
        supported_incident_categories=["External dependency / integration"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic upstream-degradation fixture replay",
    ),
    DetectorFamily(
        detector_family_id="distributed_trace_anomalies",
        display_name="Distributed trace anomalies",
        intended_failure_signals=["unusual span topology", "orphaned spans", "cross-service error propagation"],
        required_telemetry_sources=["distributed trace data (spans/trace ids)"],
        detection_prerequisites=["tracing is propagated consistently across service boundaries"],
        expected_observation_schema="trace-topology and span-error-rate summaries",
        supported_incident_categories=["Latency / capacity", "External dependency / integration"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic trace-fixture replay with injected span anomalies",
    ),
    DetectorFamily(
        detector_family_id="incident_correlation",
        display_name="Incident correlation",
        intended_failure_signals=["multiple findings sharing a trace id, time window, or dependency"],
        required_telemetry_sources=["prior FailureFinding records", "shared trace/alert identifiers"],
        detection_prerequisites=["findings carry comparable identifiers (trace ids, alert ids, timestamps)"],
        expected_observation_schema="grouped-finding clusters with shared-identifier evidence",
        supported_incident_categories=["cross-cutting -- not tied to one failure class"],
        gaps_and_limitations=[
            "no implementation yet; correlation is explicitly NEVER treated as proof of a shared root cause"
        ],
        planned_verification_approach="synthetic multi-finding correlation fixture replay",
    ),
    DetectorFamily(
        detector_family_id="configuration_credential_failures",
        display_name="Configuration / credential failures",
        intended_failure_signals=["expired certificate/secret", "misconfigured env var", "config drift"],
        required_telemetry_sources=["config-management audit logs", "certificate/secret expiry metadata"],
        detection_prerequisites=["configuration changes and secret expiry are tracked centrally"],
        expected_observation_schema="config-change and expiry-countdown series",
        supported_incident_categories=["Authentication / credentials", "Rollout / compatibility"],
        gaps_and_limitations=["no implementation yet; never reads or exposes actual secret values"],
        planned_verification_approach="synthetic expiring-certificate fixture replay",
    ),
    DetectorFamily(
        detector_family_id="monitoring_blind_spots",
        display_name="Monitoring blind-spot detection",
        intended_failure_signals=["a service/path with no alerting coverage", "a metric that silently stopped reporting"],
        required_telemetry_sources=["service registry", "alert-rule inventory", "metric heartbeat/liveness"],
        detection_prerequisites=["a registry of expected services and expected metrics exists"],
        expected_observation_schema="coverage-gap list: expected-but-missing alert rules or stale metrics",
        supported_incident_categories=["cross-cutting -- meta-detection of missing detection"],
        gaps_and_limitations=["no implementation yet"],
        planned_verification_approach="synthetic fixture with a deliberately unmonitored service",
    ),
)


def get_detector_family(detector_family_id: str) -> DetectorFamily | None:
    for family in DETECTOR_FAMILIES:
        if family.detector_family_id == detector_family_id:
            return family
    return None
