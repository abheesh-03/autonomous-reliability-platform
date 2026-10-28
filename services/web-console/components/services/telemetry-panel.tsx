import { Activity, AlertTriangle, Clock, Gauge } from "lucide-react";
import { Badge, type BadgeProps } from "../ui/badge";
import { Card, CardContent } from "../ui/card";
import { formatTimestamp } from "../../lib/format";
import type { TelemetrySummary } from "../../lib/types/telemetry";
import type { ConnectionStatus } from "../../lib/types/telemetry";

/**
 * Phase 16 Gate 5: renders ONLY what the backend's own real, bounded
 * aggregate actually reports -- never a fabricated metric, never a
 * hardcoded uptime percentage, never "healthy" inferred merely from
 * the absence of an incident. Every one of Gate 5's six required
 * connection states is a distinct, honest rendering -- see
 * STATUS_COPY below.
 */

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  not_configured: "Not configured",
  configured_awaiting_data: "Configured — awaiting data",
  receiving_telemetry: "Receiving telemetry",
  stale_data: "Stale data",
  connection_error: "Connection error",
  revoked: "Revoked",
};

const STATUS_TONE: Record<ConnectionStatus, BadgeProps["tone"]> = {
  not_configured: "neutral",
  configured_awaiting_data: "info",
  receiving_telemetry: "success",
  stale_data: "warning",
  connection_error: "critical",
  revoked: "critical",
};

const STATUS_DESCRIPTION: Record<ConnectionStatus, string> = {
  not_configured: "No integration credential has been generated for this service yet.",
  configured_awaiting_data: "A credential exists, but no telemetry has been accepted from it yet.",
  receiving_telemetry: "Real telemetry was observed recently — the measurements below reflect it.",
  stale_data: "Telemetry was observed before, but none recently — this service may have stopped reporting.",
  connection_error: "This console could not reach the backend to check this service's telemetry.",
  revoked: "Every credential for this service has been revoked — no new telemetry can be accepted.",
};

function formatSeconds(value: number | null): string {
  if (value === null) return "—";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  return `${value.toFixed(2)} s`;
}

function MetricTile({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-sunken p-3">
      <div className="flex items-center gap-1.5 text-xs text-fg-muted">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </div>
      <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
    </div>
  );
}

export function TelemetryPanel({ summary }: { summary: TelemetrySummary }) {
  const hasData = summary.request_count > 0;

  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge tone={STATUS_TONE[summary.status]} dot>
            {STATUS_LABEL[summary.status]}
          </Badge>
          <span className="text-xs text-fg-subtle">
            Last {summary.window_minutes} min · generated {formatTimestamp(summary.generated_at)}
          </span>
        </div>

        <p className="text-sm text-fg-muted">{STATUS_DESCRIPTION[summary.status]}</p>

        {hasData ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <MetricTile icon={Activity} label="Request rate" value={`${summary.request_rate_per_minute.toFixed(1)}/min`} />
            <MetricTile
              icon={AlertTriangle}
              label="Error rate"
              value={summary.error_rate !== null ? `${(summary.error_rate * 100).toFixed(1)}%` : "—"}
            />
            <MetricTile icon={Gauge} label="Mean latency" value={formatSeconds(summary.mean_latency_seconds)} />
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-fg-subtle">
            No measurements in the selected window.
          </div>
        )}

        <p className="flex items-center gap-1.5 text-xs text-fg-subtle">
          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
          Last observed telemetry: {summary.last_observed_at ? formatTimestamp(summary.last_observed_at) : "never"}
        </p>
      </CardContent>
    </Card>
  );
}
