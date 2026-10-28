import type { LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../ui/card";
import { Badge, type BadgeProps } from "../ui/badge";
import { SetupGuideDialog, type GuidedStep } from "./setup-guide-dialog";

export type IntegrationStatus =
  | "available"
  | "configuration_required"
  | "connected"
  | "no_recent_data"
  | "connection_error"
  | "operator_only"
  | "not_yet_supported";

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  available: "Available",
  configuration_required: "Configuration required",
  connected: "Connected",
  no_recent_data: "No recent data",
  connection_error: "Connection error",
  // Gate 7 visual polish: a dedicated status, distinct from
  // "not_yet_supported" -- a real, operator-level read-only observer
  // capability for this integration DOES exist (Kubernetes/AWS), just
  // not self-service, organization-scoped enrollment yet. "Not yet
  // supported" alone would wrongly imply the capability is wholly
  // absent; this status names the real, narrower gap honestly without
  // ever implying a customer connection exists.
  operator_only: "Operator-managed only",
  not_yet_supported: "Not yet supported",
};

const STATUS_TONE: Record<IntegrationStatus, BadgeProps["tone"]> = {
  available: "info",
  configuration_required: "warning",
  connected: "success",
  no_recent_data: "warning",
  connection_error: "critical",
  operator_only: "info",
  not_yet_supported: "neutral",
};

export type { GuidedStep };

// A Server Component (the icon prop, a component reference, can
// never cross into a Client Component's serialized props -- see
// SetupGuideDialog, which owns the one genuinely interactive piece
// and receives only plain, serializable data).
export function IntegrationCard({
  icon: Icon,
  name,
  description,
  status,
  blocker,
  steps,
}: {
  icon: LucideIcon;
  name: string;
  description: string;
  status: IntegrationStatus;
  /** Shown only when status is honestly not fully available -- the
   * real backend reason, never a vague "coming soon". */
  blocker?: string;
  steps: GuidedStep[];
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <CardTitle>{name}</CardTitle>
            <Badge tone={STATUS_TONE[status]} dot className="mt-1">
              {STATUS_LABEL[status]}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <CardDescription>{description}</CardDescription>
        {blocker && <p className="text-xs text-fg-subtle">{blocker}</p>}
        <SetupGuideDialog name={name} steps={steps} />
      </CardContent>
    </Card>
  );
}
