import { headers as nextHeaders } from "next/headers";
import Link from "next/link";
import { auth } from "../../lib/auth/auth";
import { getSessionUser, resolveActor } from "../../lib/server/actor";
import { VerifyEmailBanner } from "../auth/VerifyEmailBanner";
import { AppShell } from "./app-shell";
import { DemoShell } from "../demo/demo-shell";
import { ThemeToggle } from "../theme/theme-toggle";

/**
 * Phase 15: the one place that decides which of three real,
 * session-derived layouts to render. All three read the EXACT same
 * real resolveActor()/getSessionUser() this console's protected pages
 * already use (lib/server/actor.ts) -- this component only decides
 * what CHROME to show around whatever the page itself renders; it is
 * never itself a security boundary (Gate 9: the real boundary is each
 * protected page's own requireActorOrRedirect() call, and
 * independently, the backend's own assertion verification).
 *
 *   1. No session at all -> a minimal, centered layout with no
 *      sidebar (sign-in/register/unauthorized pages).
 *   2. A real session but no resolved organization membership -> a
 *      minimal top bar only (the /organizations page itself is the
 *      only reasonable destination here).
 *   3. A real, fully resolved actor -> the full application shell.
 *
 * Phase 18, deliberately: a FOURTH, explicit branch for `/demo` and
 * everything under it, checked FIRST and BEFORE any session/actor
 * resolution runs at all. This is the one intentional exception to
 * "never a fourth, separate demo layout" above -- a public, read-only
 * recorded demo genuinely needs chrome that does not depend on who
 * (if anyone) is signed in: a signed-in visitor must never see their
 * own real organization's sidebar/nav/org name wrapped around
 * recorded-demo content (it would look like the demo data belongs to
 * their account), and an anonymous visitor needs real navigation
 * between the demo's own views, which the plain centered
 * sign-in/register shell (branch 1) was never designed to provide.
 * This performs no authentication decision of its own -- every
 * existing protected route below is completely unaffected, still
 * resolves actor/session exactly as before, and `/demo`'s own pages
 * read only the bundled, static `lib/demo/snapshot.ts` (see that
 * file), never a live backend call. The pathname itself comes from
 * `middleware.ts`'s own narrow `x-pathname` header -- that file's
 * only job, and the only reason this console has a middleware.ts at
 * all.
 */
export async function RootShell({ children }: { children: React.ReactNode }) {
  const requestHeaders = await nextHeaders();
  const pathname = requestHeaders.get("x-pathname") ?? "";
  if (pathname === "/demo" || pathname.startsWith("/demo/")) {
    return <DemoShell>{children}</DemoShell>;
  }

  const [actor, sessionUser] = await Promise.all([resolveActor(), getSessionUser()]);

  if (!sessionUser) {
    return (
      <div className="flex min-h-screen flex-col">
        <div className="flex justify-end px-4 py-3">
          <ThemeToggle />
        </div>
        <main className="flex flex-1 items-center justify-center px-4 pb-16">{children}</main>
      </div>
    );
  }

  if (!actor) {
    return (
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-3 lg:px-6">
          <Link href="/" className="text-sm font-semibold text-fg">
            Reliability Console
          </Link>
          <ThemeToggle />
        </header>
        {!sessionUser.emailVerified && <VerifyEmailBanner email={sessionUser.email} />}
        <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-8">{children}</main>
      </div>
    );
  }

  const organizationName = await resolveOrganizationName(actor.organizationId);

  return (
    <AppShell email={sessionUser.email} role={actor.role} organizationName={organizationName}>
      {!sessionUser.emailVerified && <VerifyEmailBanner email={sessionUser.email} />}
      {children}
    </AppShell>
  );
}

async function resolveOrganizationName(organizationId: string): Promise<string> {
  try {
    const requestHeaders = await nextHeaders();
    const organizations = await auth.api.listOrganizations({ headers: requestHeaders });
    const active = organizations?.find((org) => org.id === organizationId);
    return active?.name ?? "Organization";
  } catch {
    // Cosmetic only (Gate 9) -- never blocks rendering the real page
    // behind it over a display-name lookup failure.
    return "Organization";
  }
}
