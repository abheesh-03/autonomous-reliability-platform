import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

export const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium leading-5 whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-surface-hover text-fg-muted border border-border",
        accent: "bg-accent-soft-bg text-accent-soft-fg",
        critical: "bg-critical-soft-bg text-critical-fg",
        warning: "bg-warning-soft-bg text-warning-fg",
        info: "bg-info-soft-bg text-info-fg",
        success: "bg-success-soft-bg text-success-fg",
        violet: "bg-violet-soft-bg text-violet-fg",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

export function Badge({ className, tone, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  );
}
