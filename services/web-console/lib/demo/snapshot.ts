// Phase 18: the real, sanitized public recorded-demo snapshot.
// Every value below is sourced from one real, verified test run --
// never invented. See docs/demo-snapshot-provenance.md for the full
// capture record (commands, raw endpoint responses, evidence bar).
//
// One deliberate redaction beyond lib/demo/types.ts's own field
// allowlist: the real investigation_report's evidence array included
// 20 raw Loki log-line entries (Java stack traces with internal file
// paths, a Docker container hostname, local IP:port pairs) alongside
// the control-plane/Prometheus/Tempo evidence. Those 20 entries
// (originally ids E8-E27) are omitted entirely below -- "raw private
// logs"/"internal addresses" are explicitly excluded from this public
// snapshot. Nothing else was altered, and no remaining evidence id was
// renumbered (gaps in the E-number sequence are real and intentional,
// not an error). The one observation that cites evidence only cites
// E1, which is retained, so no reference is left dangling.
import type { DemoSnapshot } from "./types";

export const demoSnapshot: DemoSnapshot = {
  provenance: {
    captured_at: "2026-11-01",
    incident_scenario_source:
      "Produced by this repository's own phase9-workflow.spec.ts Playwright acceptance test, run against an isolated disposable Docker Compose stack (fresh checkout, fresh Postgres volume, every host port offset, independently generated secrets) in control-plane's documented legacy local-development mode (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=false, the fixed legacy local-development organization) -- not a live or multi-tenant run. Real controlled payment-authorization fault injection drove a real sustained CheckoutServerErrors Prometheus alert, a real Alertmanager webhook, a real incident, a real AI investigation, a real human approval click, real tool-gateway execution, and real automatic recovery verification end to end.",
    telemetry_scenario_source:
      "A separate real capture on the same disposable stack: a real sign-up, real logged-link email verification, a freshly self-service-created organization (distinct from the legacy incident org above), a real registered service, a real integration credential, and one real metric exported with the official OpenTelemetry Python SDK to control-plane's local-dev OTLP endpoint. This is the external-tenant OTLP metrics path, not the alert/remediation path above -- it never involved tool-gateway or human approval.",
    investigator_provider: "stub",
  },
  dashboard_counts: {
    open: 0,
    acknowledged: 0,
    investigating: 0,
    remediating: 0,
    resolved: 1,
    closed: 0,
    active_critical: 0,
  },
  incident_scenario: {
    incident: {
      id: "e05f2bc4-f3e2-446c-a4e6-56bb0f0903f3",
      title: "checkout-service is returning HTTP 5xx errors",
      description:
        "checkout-service has served HTTP 5xx responses at a nonzero average rate over the last 5 minutes, sustained for at least 2 minutes. A genuine client-side 4xx (e.g. a failed request validation) never triggers this rule — only http_response_status_code=~\"5..\" is counted.",
      severity: "critical",
      status: "resolved",
      source: "alertmanager",
      first_seen_at: "2026-11-01T17:46:10.774000Z",
      last_seen_at: "2026-11-01T17:46:20.873719Z",
      resolved_at: "2026-11-01T17:51:10.774000Z",
      created_at: "2026-11-01T17:46:20.869851Z",
    },
    events: [
      {
        id: 1,
        event_type: "created",
        actor_type: "alertmanager",
        previous_status: null,
        new_status: "open",
        occurred_at: "2026-11-01T17:46:20.887913Z",
      },
      {
        id: 2,
        event_type: "status_transition",
        actor_type: "operator",
        previous_status: "open",
        new_status: "investigating",
        occurred_at: "2026-11-01T17:46:25.141069Z",
      },
      {
        id: 3,
        event_type: "status_transition",
        actor_type: "operator",
        previous_status: "investigating",
        new_status: "remediating",
        occurred_at: "2026-11-01T17:46:27.066072Z",
      },
      {
        id: 4,
        event_type: "status_transition",
        actor_type: "alertmanager",
        previous_status: "remediating",
        new_status: "resolved",
        occurred_at: "2026-11-01T17:51:20.850283Z",
      },
    ],
    agent_run: {
      run_id: "f57c5d6e-4f96-4a7f-a730-b2016c3f42bd",
      status: "completed",
      started_at: "2026-11-01T17:46:25.184176Z",
      updated_at: "2026-11-01T17:46:27.383232Z",
      completed_at: "2026-11-01T17:46:27.383232Z",
      current_node: "finalize",
      completed_nodes: [
        "load_incident",
        "run_investigation",
        "evaluate_investigation",
        "propose_remediation",
        "await_human_approval",
        "execute_remediation",
        "verify_recovery",
        "finalize",
      ],
      investigation_report: {
        incident_id: "e05f2bc4-f3e2-446c-a4e6-56bb0f0903f3",
        investigated_at: "2026-11-01T17:46:26.211271Z",
        incident_status_at_investigation: "investigating",
        summary: "Validated observations: A real incident record was retrieved and is described in E1. (evidence: E1).",
        observations: [
          {
            statement: "A real incident record was retrieved and is described in E1.",
            evidence_ids: ["E1"],
          },
        ],
        hypotheses: [],
        missing_evidence: [],
        suggested_checks: [],
        evidence: [
          {
            id: "E1",
            source: "control_plane",
            observed_at: "2026-11-01T17:46:10.774000Z",
            window_start: "2026-11-01T17:46:10.774000Z",
            window_end: null,
            summary:
              "Incident e05f2bc4-f3e2-446c-a4e6-56bb0f0903f3: 'checkout-service is returning HTTP 5xx errors' (severity=critical, status=investigating)",
            detail:
              'source=alertmanager source_fingerprint=f5429f5dc378f6c8 description=\'checkout-service has served HTTP 5xx responses at a nonzero average rate over the last 5 minutes, sustained for at least 2 minutes. A genuine client-side 4xx (e.g. a failed request validation) never triggers this rule — only http_response_status_code=~"5.."is counted.\' first_seen_at=2026-11-01T17:46:10.774000+00:00 last_seen_at=2026-11-01T17:46:20.873719+00:00 resolved_at=null',
            reference: { endpoint: "GET /api/v1/incidents/{id}" },
          },
          {
            id: "E2",
            source: "control_plane",
            observed_at: "2026-11-01T17:46:20.887913Z",
            window_start: null,
            window_end: null,
            summary: "Audit event: created by alertmanager (null -> open)",
            detail: 'metadata={"observed_starts_at": "2026-11-01T17:46:10.774000+00:00", "source_fingerprint": "f5429f5dc378f6c8"}',
            reference: { endpoint: "GET /api/v1/incidents/{id}/events", event_id: "1" },
          },
          {
            id: "E3",
            source: "control_plane",
            observed_at: "2026-11-01T17:46:25.141069Z",
            window_start: null,
            window_end: null,
            summary: "Audit event: status_transition by operator (open -> investigating)",
            detail: "metadata={}",
            reference: { endpoint: "GET /api/v1/incidents/{id}/events", event_id: "2" },
          },
          {
            id: "E4",
            source: "prometheus",
            observed_at: null,
            window_start: "2026-11-01T17:31:10.774000Z",
            window_end: "2026-11-01T18:01:20.873719Z",
            summary: "Prometheus: checkout-service HTTP 5xx rate (underlies CheckoutServerErrors)",
            detail: "2 sample(s); 2 of interest (nonzero rate / below-1 availability); extreme value 0.1044 at 2026-11-01T17:46:15.774000+00:00; last value 0.08488",
            reference: {
              promql: 'sum(rate(http_server_request_duration_seconds_count{service_name="checkout-service",http_response_status_code=~"5.."}[5m]))',
            },
          },
          {
            id: "E5",
            source: "prometheus",
            observed_at: null,
            window_start: "2026-11-01T17:31:10.774000Z",
            window_end: "2026-11-01T18:01:20.873719Z",
            summary: "Prometheus: checkout-service POST /checkouts p95 latency (underlies CheckoutHighLatency)",
            detail: "2 sample(s); 2 of interest (nonzero rate / below-1 availability); extreme value 0.06625 at 2026-11-01T17:49:16.774000+00:00; last value 0.06625",
            reference: {
              promql: 'histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="checkout-service",http_route="/checkouts"}[5m])))',
            },
          },
          {
            id: "E6",
            source: "prometheus",
            observed_at: null,
            window_start: "2026-11-01T17:31:10.774000Z",
            window_end: "2026-11-01T18:01:20.873719Z",
            summary: "Prometheus: otel-collector / otel-collector-app-metrics scrape availability (underlies TelemetryPipelineUnavailable)",
            detail: "8 sample(s); 0 of interest (nonzero rate / below-1 availability); extreme value 1 at 2026-11-01T17:40:13.774000+00:00; last value 1",
            reference: { promql: 'up{job=~"otel-collector|otel-collector-app-metrics"}' },
          },
          {
            id: "E7",
            source: "prometheus",
            observed_at: null,
            window_start: "2026-11-01T17:31:10.774000Z",
            window_end: "2026-11-01T18:01:20.873719Z",
            summary: "Prometheus: otel-collector refused spans/metric points rate (underlies CollectorRefusingTelemetry)",
            detail: "4 sample(s); 0 of interest (nonzero rate / below-1 availability); extreme value 0 at 2026-11-01T17:40:13.774000+00:00; last value 0",
            reference: {
              promql: 'sum(rate(otelcol_receiver_refused_spans{job="otel-collector"}[5m])) + sum(rate(otelcol_receiver_refused_metric_points{job="otel-collector"}[5m]))',
            },
          },
          {
            id: "E28",
            source: "tempo",
            observed_at: "2026-11-01T17:40:15.781344Z",
            window_start: null,
            window_end: null,
            summary: "Candidate trace rooted at checkout-service (15ms)",
            detail:
              "trace_id=4283b0c66fdd375cf0408a6322adab2a root_trace_name='GET /actuator/health'; 1 real span(s) across 1 service(s) (checkout-service); root span service(s): checkout-service -- time+service match only; application logs carry no trace ID today, so this is NOT a confirmed causal link to this incident, only a candidate in the same window",
            reference: { trace_id: "4283b0c66fdd375cf0408a6322adab2a" },
          },
          {
            id: "E29",
            source: "tempo",
            observed_at: "2026-11-01T17:38:49.619564Z",
            window_start: null,
            window_end: null,
            summary: "Candidate trace rooted at checkout-service (14ms)",
            detail:
              "trace_id=cc2a8083272f0e3a7ce469d72b9e50d1 root_trace_name='GET /actuator/health'; 1 real span(s) across 1 service(s) (checkout-service); root span service(s): checkout-service -- time+service match only; application logs carry no trace ID today, so this is NOT a confirmed causal link to this incident, only a candidate in the same window",
            reference: { trace_id: "cc2a8083272f0e3a7ce469d72b9e50d1" },
          },
          {
            id: "E30",
            source: "tempo",
            observed_at: "2026-11-01T17:38:44.549097Z",
            window_start: null,
            window_end: null,
            summary: "Candidate trace rooted at checkout-service (8ms)",
            detail:
              "trace_id=f4b0ca5f77fb86cf0f26298b7fd1b7d3 root_trace_name='GET /actuator/health'; 1 real span(s) across 1 service(s) (checkout-service); root span service(s): checkout-service -- time+service match only; application logs carry no trace ID today, so this is NOT a confirmed causal link to this incident, only a candidate in the same window",
            reference: { trace_id: "f4b0ca5f77fb86cf0f26298b7fd1b7d3" },
          },
          {
            id: "E31",
            source: "tempo",
            observed_at: "2026-11-01T17:38:39.474155Z",
            window_start: null,
            window_end: null,
            summary: "Candidate trace rooted at checkout-service (28ms)",
            detail:
              "trace_id=726288121498eeaaacd642a5e089627c root_trace_name='GET /actuator/health'; 1 real span(s) across 1 service(s) (checkout-service); root span service(s): checkout-service -- time+service match only; application logs carry no trace ID today, so this is NOT a confirmed causal link to this incident, only a candidate in the same window",
            reference: { trace_id: "726288121498eeaaacd642a5e089627c" },
          },
          {
            id: "E32",
            source: "tempo",
            observed_at: "2026-11-01T17:38:34.309663Z",
            window_start: null,
            window_end: null,
            summary: "Candidate trace rooted at checkout-service (112ms)",
            detail:
              "trace_id=bf598f318e4bfd20c579f909bc732583 root_trace_name='GET /actuator/health'; 1 real span(s) across 1 service(s) (checkout-service); root span service(s): checkout-service -- time+service match only; application logs carry no trace ID today, so this is NOT a confirmed causal link to this incident, only a candidate in the same window",
            reference: { trace_id: "bf598f318e4bfd20c579f909bc732583" },
          },
        ],
        source_outcomes: [
          {
            source: "control_plane",
            status: "ok",
            detail: "incident retrieved; all 2 of 2 real audit event(s) retrieved",
            query_summary: "GET /api/v1/incidents/{id}, GET /api/v1/incidents/{id}/events",
          },
          {
            source: "prometheus",
            status: "ok",
            detail: "at least one of the four monitored metrics showed activity in this window",
            query_summary: "4 allowlisted range queries",
          },
          {
            source: "loki",
            status: "ok",
            detail: "20 log line(s) retrieved across the four application services",
            query_summary: "application service logs in the incident window",
          },
          {
            source: "tempo",
            status: "ok",
            detail: "5 candidate trace(s) found rooted at checkout-service in this window (time+service correlation only, not a confirmed causal link)",
            query_summary: "Tempo tag search: service.name=checkout-service",
          },
        ],
        retrieval_context: {
          knowledge: [],
          historical_incidents: [],
          outcome: "no_data",
          detail: "retrieval-service returned no matching context",
        },
        provider: { configured: true, provider: "stub", model: "stub-deterministic-v1" },
        validation_notes: [
          "replaced the provider's free-text summary with one built only from the validated, citation-backed observations/hypotheses below -- the provider's own summary is never retained as-is, since it cannot be semantically verified and could otherwise repeat a claim rejected above",
        ],
      },
      result_quality: "partial",
      resumable: false,
      remediation_proposal_id: "b68abf69-1843-4a2d-b61f-be094ed59488",
      remediation_action_type: "clear_payment_authorization_fault",
      remediation_target: "payment-service",
      remediation_status: "succeeded",
      execution_result: { status: "succeeded", detail: null },
      recovery_verification: { proposal_succeeded: true, fault_inactive: true, target_healthy: true },
    },
    remediation_proposal: {
      id: "b68abf69-1843-4a2d-b61f-be094ed59488",
      action_type: "clear_payment_authorization_fault",
      target: "payment-service",
      reason:
        "deterministic policy match: alertmanager-sourced critical incident matching the CheckoutServerErrors condition, with an existing investigation and tool-gateway independently reporting the controlled payment authorization fault as active",
      status: "succeeded",
      proposed_at: "2026-11-01T17:46:26.255826Z",
      decided_at: "2026-11-01T17:46:27.048645Z",
      decision_comment: null,
      execution_started_at: "2026-11-01T17:46:27.319415Z",
      execution_completed_at: "2026-11-01T17:46:27.334222Z",
    },
    remediation_events: [
      { id: 1, event_type: "proposed", actor_type: "agent", occurred_at: "2026-11-01T17:46:26.261856Z" },
      { id: 2, event_type: "approved", actor_type: "operator", occurred_at: "2026-11-01T17:46:27.064306Z" },
      { id: 3, event_type: "execution_started", actor_type: "executor", occurred_at: "2026-11-01T17:46:27.324570Z" },
      { id: 4, event_type: "execution_succeeded", actor_type: "executor", occurred_at: "2026-11-01T17:46:27.335891Z" },
    ],
  },
  telemetry_scenario: {
    service: {
      id: "413c286a-32c7-41f1-9137-c9be85b92f5f",
      name: "Phase 18 Demo API",
      kind: "rest_api",
      language: "Python",
      description: "Public recorded-demo example service.",
      created_at: "2026-11-01T17:53:41.791600Z",
    },
    credential: {
      id: "51bb8915-f10a-436d-95e5-7491b1964191",
      credential_id: "cred_02Wfpb8cw2dudRD0wxJALQ",
      status: "active",
      created_at: "2026-11-01T17:53:41.857860Z",
      last_verified_telemetry_at: "2026-11-01T17:54:26.403431Z",
    },
    summary: {
      service_id: "413c286a-32c7-41f1-9137-c9be85b92f5f",
      status: "receiving_telemetry",
      window_minutes: 15,
      request_count: 2,
      error_count: 0,
      request_rate_per_minute: 0.1,
      error_rate: 0,
      mean_latency_seconds: 0.0395,
      last_observed_at: "2026-11-01T17:54:26.342794Z",
      generated_at: "2026-11-01T17:54:37Z",
    },
  },
};
