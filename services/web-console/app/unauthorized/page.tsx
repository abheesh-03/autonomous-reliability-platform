import Link from "next/link";

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
    <main style={{ maxWidth: 480, margin: "0 auto", padding: "3rem 1.5rem" }}>
      <h1>Not authorized</h1>
      <p style={{ color: "#9fb3c8" }}>
        You do not have permission to view this page, or your organization membership no longer grants it.
      </p>
      <p>
        <Link href="/organizations">Switch organization</Link>
      </p>
    </main>
  );
}
