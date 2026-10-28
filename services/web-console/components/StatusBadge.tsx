import { Badge, type BadgeProps } from "./ui/badge";

const SEVERITY_TONE: Record<string, BadgeProps["tone"]> = {
  critical: "critical",
  warning: "warning",
  info: "info",
};

const STATUS_TONE: Record<string, BadgeProps["tone"]> = {
  open: "critical",
  acknowledged: "warning",
  investigating: "info",
  remediating: "violet",
  resolved: "success",
  closed: "neutral",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity] ?? "neutral"}>{severity}</Badge>;
}

export function StatusBadgePill({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status}</Badge>;
}
