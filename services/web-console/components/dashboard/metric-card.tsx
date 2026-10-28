import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { Card } from "../ui/card";
import { cn } from "../../lib/cn";

export function MetricCard({
  label,
  value,
  icon: Icon,
  href,
  tone = "neutral",
}: {
  label: string;
  value: number;
  icon: LucideIcon;
  href?: string;
  tone?: "neutral" | "critical" | "warning" | "accent";
}) {
  const toneClasses: Record<string, string> = {
    neutral: "bg-surface-hover text-fg-muted",
    critical: "bg-critical-soft-bg text-critical-fg",
    warning: "bg-warning-soft-bg text-warning-fg",
    accent: "bg-accent-soft-bg text-accent-soft-fg",
  };

  const content = (
    <Card className={cn("flex items-center gap-4 p-5 transition-colors", href && "hover:bg-surface-hover")}>
      <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", toneClasses[tone])}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <div>
        <p className="text-2xl font-semibold leading-none text-fg">{value}</p>
        <p className="mt-1 text-sm text-fg-muted">{label}</p>
      </div>
    </Card>
  );

  if (!href) return content;
  return (
    <Link href={href} className="block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent) rounded-xl">
      {content}
    </Link>
  );
}
