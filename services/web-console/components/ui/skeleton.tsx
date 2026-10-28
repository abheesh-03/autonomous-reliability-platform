import { cn } from "../../lib/cn";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-surface-hover", className)}
      role="presentation"
      aria-hidden="true"
      {...props}
    />
  );
}
