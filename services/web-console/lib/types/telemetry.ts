// Mirrors control-plane's real contract exactly
// (services/control-plane/src/control_plane/domain/telemetry.py).
// Every field is sourced from a real, bounded, organization-scoped SQL
// aggregate -- see that service's repositories/telemetry_repository.py.

export type ConnectionStatus =
  | "not_configured"
  | "configured_awaiting_data"
  | "receiving_telemetry"
  | "stale_data"
  | "connection_error"
  | "revoked";

export interface TelemetrySummary {
  service_id: string;
  status: ConnectionStatus;
  window_minutes: number;
  request_count: number;
  error_count: number;
  request_rate_per_minute: number;
  error_rate: number | null;
  // Correction round (item 4): the previous round exposed
  // p50/p95_latency_seconds computed as a percentile over each stored
  // row's own per-export-interval MEAN duration -- a percentile of
  // batch averages, not a request-level percentile. Replaced with one
  // real, correctly-weighted mean
  // (SUM(duration_sum_seconds) / SUM(request_count) across the window,
  // computed server-side) -- never presented as a percentile.
  mean_latency_seconds: number | null;
  last_observed_at: string | null;
  generated_at: string;
}
