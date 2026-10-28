import Link from "next/link";
import { ShieldX } from "lucide-react";
import { buttonVariants } from "../../components/ui/button";

/**
 * Phase 14 Gate 9: a dedicated forbidden/unauthorized state, distinct
 * from a 404. Most backend permission denials render inline via
 * components/BackendFailure.tsx ("forbidden" kind) right where the
 * action was attempted; this page exists for the general case (e.g.
 * a stale bookmark to a page that now redirects here in a future
 * extension of this console).
 */
export default function UnauthorizedPage() {
  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-3 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-critical-soft-bg text-critical-fg">
        <ShieldX className="h-6 w-6" aria-hidden="true" />
      </div>
      <h1 className="text-lg font-semibold text-fg">Not authorized</h1>
      <p className="text-sm text-fg-muted">
        You do not have permission to view this page, or your organization membership no longer grants it.
      </p>
      <Link href="/organizations" className={buttonVariants({ variant: "secondary", className: "mt-2" })}>
        Switch organization
      </Link>
    </div>
  );
}
