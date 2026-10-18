const SEVERITY_COLORS: Record<string, string> = {
  critical: "#f3c9c9",
  warning: "#f3e2a8",
  info: "#a8d4f3",
};

const STATUS_COLORS: Record<string, string> = {
  open: "#f3c9c9",
  acknowledged: "#f3e2a8",
  investigating: "#a8d4f3",
  remediating: "#c9a8f3",
  resolved: "#a8f3c0",
  closed: "#9fb3c8",
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.6rem",
        borderRadius: 999,
        fontSize: "0.8rem",
        color: "#0b0f14",
        background: color,
      }}
    >
      {label}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge label={severity} color={SEVERITY_COLORS[severity] ?? "#9fb3c8"} />;
}

export function StatusBadgePill({ status }: { status: string }) {
  return <Badge label={status} color={STATUS_COLORS[status] ?? "#9fb3c8"} />;
}
